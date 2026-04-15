"""Rickshaw Forex Engine Runner — Background daemon with Telegram heartbeat.

Run as: pythonw engine_runner.py           (background, silent)
    or: python engine_runner.py            (foreground/debug)
    or: python engine_runner.py --interval 60  (custom interval)

Every cycle:
  1. Check if forex market is open (24/5)
  2. Run tick() on all active forex strategies
  3. Send heartbeat to Telegram
  4. Sleep and repeat

Differences from stock engine:
  - Default 60s interval (forex moves faster)
  - 24/5 market (only sleeps on weekends)
  - Spread monitoring in heartbeat
  - Pip-based P&L reporting
"""
import argparse
import json
import os
import sys
import time
import logging
import requests
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PARENT_DIR)

CONFIG_FILE = os.path.join(PARENT_DIR, "trader", "trader_config.json")
LOG_FILE = os.path.join(SCRIPT_DIR, "forex_engine.log")
PID_FILE = os.path.join(SCRIPT_DIR, "forex_engine.pid")
HEARTBEAT_FILE = os.path.join(os.path.expanduser("~"), "telegram-to-powershell", "heartbeats.json")
RICKSHAW_DB = os.path.join(PARENT_DIR, "rickshaw.db")

DEFAULT_INTERVAL = 60  # 1 minute (forex moves faster than stocks)
HEARTBEAT_INTERVAL = 5  # send heartbeat every N cycles (5 min at 60s interval)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stderr),
    ],
)
log = logging.getLogger("forex-engine")


def load_tg_config():
    """Load Telegram bot config for heartbeat messages."""
    tg_config = os.path.join(os.path.expanduser("~"), "telegram-to-powershell", "config.json")
    if os.path.exists(tg_config):
        with open(tg_config) as f:
            cfg = json.load(f)
        if cfg.get("bot_token") and cfg.get("chat_id"):
            return cfg["bot_token"], int(cfg["chat_id"])

    # Fallback to rickshaw.db
    try:
        import sqlite3
        conn = sqlite3.connect(RICKSHAW_DB)
        token = conn.execute("SELECT value FROM config WHERE key='tg_bot_token'").fetchone()
        chat_id = conn.execute("SELECT value FROM config WHERE key='tg_chat_id'").fetchone()
        conn.close()
        if token and chat_id and token[0] and chat_id[0]:
            return token[0], int(chat_id[0])
    except Exception:
        pass

    return None, None


def send_heartbeat(token, chat_id, message):
    if not token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message[:4096]},
            timeout=10,
        )
    except Exception as e:
        log.error(f"Heartbeat send failed: {e}")


def write_heartbeat_file(status, message=""):
    beats = {}
    if os.path.exists(HEARTBEAT_FILE):
        try:
            with open(HEARTBEAT_FILE, "r") as f:
                beats = json.load(f)
        except Exception:
            pass
    beats["forex-engine"] = {
        "status": status,
        "message": message[:200],
        "time": time.time(),
        "time_str": time.strftime("%H:%M:%S"),
    }
    try:
        with open(HEARTBEAT_FILE, "w") as f:
            json.dump(beats, f, indent=2)
    except Exception:
        pass


def format_heartbeat(cycle, results, account, positions, strategies_active, spreads):
    """Format heartbeat for Claude terminal injection."""
    ts = datetime.now().strftime("%H:%M:%S")
    balance = float(account.get("balance", 0))
    nav = float(account.get("portfolio_value", 0))
    upl = float(account.get("unrealized_pl", 0))

    parts = [f"[FOREX HEARTBEAT {ts} cycle#{cycle}]"]
    parts.append(f"NAV: ${nav:,.0f} Bal: ${balance:,.0f}")

    if positions:
        pos_details = []
        for p in positions:
            inst = p["instrument"]
            pl = float(p["unrealized_pl"])
            pos_details.append(f"{inst}:{pl:+.2f}")
        parts.append(f"P&L: ${upl:+,.2f} [{' '.join(pos_details)}]")

    if spreads:
        spread_str = " ".join(f"{k}:{v:.1f}p" for k, v in spreads.items())
        parts.append(f"Spreads: {spread_str}")

    parts.append(f"Strategies: {strategies_active} active")

    if results:
        for r in results:
            for a in r["actions"]:
                parts.append(f"ACTION: [{r['strategy']}] {a['msg']}")

    parts.append("If anything needs attention, respond now. Otherwise ignore.")
    return " | ".join(parts)


def format_heartbeat_telegram(cycle, results, account, positions, strategies_active, spreads):
    """Longer format for Telegram (readable on phone)."""
    ts = datetime.now().strftime("%H:%M:%S")
    lines = [f"[Forex {ts}] cycle #{cycle}"]

    balance = float(account.get("balance", 0))
    nav = float(account.get("portfolio_value", 0))
    upl = float(account.get("unrealized_pl", 0))
    margin = float(account.get("margin_used", 0))

    lines.append(f"NAV: ${nav:,.2f} | Balance: ${balance:,.2f}")
    lines.append(f"Margin: ${margin:,.2f} | UPL: ${upl:+,.2f}")

    if positions:
        lines.append(f"Positions: {len(positions)}")
        for p in positions:
            pl = float(p["unrealized_pl"])
            long_u = float(p.get("long_units", 0))
            short_u = float(p.get("short_units", 0))
            units = long_u if long_u != 0 else short_u
            side = "LONG" if long_u > 0 else "SHORT"
            lines.append(f"  {p['instrument']}: {side} {abs(units):.0f}u ${pl:+,.2f}")
    else:
        lines.append("Positions: none")

    if spreads:
        spread_parts = [f"{k}:{v:.1f}p" for k, v in spreads.items()]
        lines.append(f"Spreads: {' '.join(spread_parts)}")

    lines.append(f"Strategies: {strategies_active} active")

    if results:
        lines.append("Actions:")
        for r in results:
            for a in r["actions"]:
                lines.append(f"  [{r['strategy']}] {a['msg']}")

    return "\n".join(lines)


def get_key_spreads(trader):
    """Get spreads for key pairs to monitor liquidity."""
    spreads = {}
    for pair in ["EUR_USD", "GBP_USD", "USD_JPY"]:
        try:
            q = trader.get_quote(pair)
            if "error" not in q:
                spreads[pair] = q["spread_pips"]
        except Exception:
            pass
    return spreads


def ai_heartbeat(cycle, results, account, positions, strategies_active, spreads):
    """Generate an AI-powered Telegram update via Qwen.

    Instead of raw numbers, Qwen reads the full state and writes
    a 2-4 sentence briefing: what's happening, why, what to watch.
    """
    from forex.brain import ask_brain
    from forex.strategies import get_active_session

    session = get_active_session()
    nav = float(account.get("portfolio_value", 0))
    balance = float(account.get("balance", 0))
    upl = float(account.get("unrealized_pl", 0))
    margin = float(account.get("margin_used", 0))

    # Build context
    pos_lines = []
    for p in positions:
        pl = float(p["unrealized_pl"])
        long_u = float(p.get("long_units", 0))
        short_u = float(p.get("short_units", 0))
        side = "LONG" if long_u > 0 else "SHORT"
        units = abs(long_u) if long_u != 0 else abs(short_u)
        pos_lines.append(f"{p['instrument']}: {side} {units:.0f}u P&L=${pl:+,.2f}")

    spread_lines = [f"{k}: {v:.1f}p" for k, v in spreads.items()]

    action_lines = []
    for r in results:
        for a in r["actions"]:
            action_lines.append(f"[{r['strategy']}] {a['msg']}")

    context = f"""Forex Trading Account Status (cycle #{cycle}):
NAV: ${nav:,.2f} | Balance: ${balance:,.2f} | UPL: ${upl:+,.2f} | Margin: ${margin:,.2f}
Active strategies: {strategies_active}
Session: {', '.join(session['sessions']) or 'gap'} (liquidity: {session['liquidity']:.0%})

Positions:
{chr(10).join(pos_lines) if pos_lines else 'None'}

Spreads: {', '.join(spread_lines)}

Actions this cycle:
{chr(10).join(action_lines) if action_lines else 'None'}"""

    question = """You are a forex trading assistant sending a Telegram update to the trader.
Write a brief 2-4 sentence update. Include:
- Overall status (are we making or losing money and why)
- Any positions that need attention
- Current session/liquidity context
- If actions happened, explain what and why

Keep it conversational and direct. No headers. No bullet points. Like texting a friend who trades.
Start with an emoji: green circle if profitable, red if losing, yellow if flat/mixed."""

    result = ask_brain(question, context, mode="qwen")
    answer = result.get("answer", "")

    if not answer or "error" in result:
        # Fallback to simple format
        return f"[Forex #{cycle}] NAV: ${nav:,.0f} UPL: ${upl:+,.2f} | {strategies_active} active | {', '.join(session['sessions']) or 'gap'}"

    return answer


def main():
    parser = argparse.ArgumentParser(description="Rickshaw Forex Engine Runner")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                        help=f"Check interval in seconds (default: {DEFAULT_INTERVAL})")
    parser.add_argument("--heartbeat-every", type=int, default=HEARTBEAT_INTERVAL,
                        help=f"Send heartbeat every N cycles (default: {HEARTBEAT_INTERVAL})")
    parser.add_argument("--always-heartbeat", action="store_true",
                        help="Send heartbeat every cycle")
    args = parser.parse_args()

    # Load config
    if not os.path.exists(CONFIG_FILE):
        log.error("No trader_config.json with OANDA keys. Run: python -m forex setup")
        sys.exit(1)

    with open(CONFIG_FILE) as f:
        cfg = json.load(f)

    if not cfg.get("oanda_api_key") or not cfg.get("oanda_account_id"):
        log.error("Missing OANDA keys in config. Run: python -m forex setup")
        sys.exit(1)

    from trader.oanda_client import OandaTrader
    from forex.strategies import tick, get_strategies, is_forex_open

    trader = OandaTrader(
        cfg["oanda_api_key"], cfg["oanda_account_id"],
        practice=cfg.get("oanda_practice", True),
    )

    tg_token, tg_chat = load_tg_config()

    # Write PID
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    log.info(f"Forex engine started (interval={args.interval}s, pid={os.getpid()})")
    log.info(f"Heartbeat: {'every cycle' if args.always_heartbeat else f'every {args.heartbeat_every} cycles'}")
    log.info(f"Telegram: {'configured' if tg_token else 'not configured'}")

    if tg_token:
        send_heartbeat(tg_token, tg_chat,
                       f"[Forex Engine] Started. Checking every {args.interval}s. "
                       f"Heartbeat every {args.heartbeat_every} cycles.")

    cycle = 0
    was_open = False

    SLEEP_OPEN = args.interval       # 60s during market
    SLEEP_WEEKEND = 600              # 10 min on weekends (just checking clock)

    while True:
        cycle += 1

        try:
            market_open = is_forex_open()

            # Market just opened (Sunday evening)
            if market_open and not was_open:
                log.info("Forex market opened!")
                if tg_token:
                    send_heartbeat(tg_token, tg_chat,
                                   "[Forex Engine] Market opened (Sunday). Strategies activating.")
                write_heartbeat_file("MARKET OPEN", "Forex market opened. Engine active.")
                was_open = True

            # Market just closed (Friday evening)
            if not market_open and was_open:
                log.info("Forex market closed (weekend).")
                try:
                    account = trader.get_account()
                    positions = trader.get_positions()
                    from forex.strategies import get_pnl_summary
                    pnl = get_pnl_summary()

                    eod = "[Forex Engine] Market closed (weekend).\n"
                    eod += f"Balance: ${float(account['balance']):,.2f}\n"
                    eod += f"NAV: ${float(account['portfolio_value']):,.2f}\n"
                    if positions:
                        upl = float(account["unrealized_pl"])
                        eod += f"Open positions: {len(positions)}, UPL: ${upl:+,.2f}\n"
                        eod += "WARNING: Positions open over weekend!\n"
                        for p in positions:
                            eod += f"  {p['instrument']}: ${float(p['unrealized_pl']):+,.2f}\n"
                    eod += f"Realized P&L: {pnl['realized_pnl_pips']:+.1f} pips"

                    if tg_token:
                        send_heartbeat(tg_token, tg_chat, eod)
                    write_heartbeat_file("WEEKEND", eod.replace("\n", " | "))
                    log.info(eod)
                except Exception as e:
                    log.error(f"Weekend summary failed: {e}")
                was_open = False

            # Weekend — sleep longer
            if not market_open:
                time.sleep(SLEEP_WEEKEND)
                continue

            # ── Auto-scanner (every 15 cycles = 15 min at 60s) ────
            if cycle % 15 == 0:
                try:
                    from forex.strategies import auto_scan_and_deploy
                    scan_results = auto_scan_and_deploy(trader, max_positions=6, risk_pct=0.01)
                    for a in scan_results:
                        if a["action"] not in ("skip",):
                            log.info(f"[AUTO-SCANNER] {a['msg']}")
                            if tg_token:
                                send_heartbeat(tg_token, tg_chat, f"[Forex Auto] {a['msg']}")
                except Exception as e:
                    log.error(f"Auto-scanner error: {e}")

            # Market open — run engine tick
            results = tick(trader)

            for r in results:
                for a in r["actions"]:
                    log.info(f"[{r['strategy']}] {a['msg']}")

            # Heartbeat
            should_heartbeat = args.always_heartbeat or (cycle % args.heartbeat_every == 0)
            has_actions = bool(results)

            if should_heartbeat or has_actions:
                account = trader.get_account()
                positions = trader.get_positions()
                spreads = get_key_spreads(trader)
                active = len(get_strategies(status="active"))

                tg_msg = format_heartbeat_telegram(
                    cycle, results, account, positions, active, spreads)
                prompt_msg = format_heartbeat(
                    cycle, results, account, positions, active, spreads)

                log.info(tg_msg)

                nav = float(account.get("portfolio_value", 0))
                upl = float(account.get("unrealized_pl", 0))
                write_heartbeat_file(
                    f"${nav:,.0f} UPL:${upl:+,.0f}",
                    prompt_msg,
                )

                if tg_token and has_actions:
                    # Immediate alert on any trade action
                    send_heartbeat(tg_token, tg_chat, tg_msg)

                if tg_token and should_heartbeat and cycle % 5 == 0:
                    # AI-powered update every 5 cycles (5 min)
                    try:
                        ai_msg = ai_heartbeat(
                            cycle, results, account, positions, active, spreads)
                        if ai_msg:
                            send_heartbeat(tg_token, tg_chat, ai_msg)
                    except Exception as e:
                        log.error(f"AI heartbeat failed: {e}")
                        send_heartbeat(tg_token, tg_chat, tg_msg)

        except KeyboardInterrupt:
            log.info("Shutting down...")
            break
        except Exception as e:
            log.error(f"Forex engine error: {e}")
            if tg_token:
                send_heartbeat(tg_token, tg_chat, f"[Forex Engine ERROR] {e}")

        time.sleep(SLEEP_OPEN)

    # Cleanup
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)
    log.info("Forex engine stopped.")


if __name__ == "__main__":
    main()
