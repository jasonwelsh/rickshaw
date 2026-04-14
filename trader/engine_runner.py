"""Rickshaw Engine Runner — Background engine with Telegram heartbeat.

Run as: pythonw engine_runner.py           (background)
    or: python engine_runner.py            (foreground/debug)
    or: python engine_runner.py --interval 60  (custom interval)

Every cycle:
  1. Check if market is open
  2. Run tick() on all active strategies
  3. Send heartbeat to Telegram (status + actions)
  4. Heartbeat gets injected into Claude's terminal via telegram-to-powershell

The engine is the autopilot. Telegram is the instrument panel.
Claude is the pilot who grabs the stick when needed.
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

CONFIG_FILE = os.path.join(SCRIPT_DIR, "trader_config.json")
TG_CONFIG = os.path.join(PARENT_DIR, "telegram-to-powershell", "config.json")
# Also check local rickshaw config for telegram
RICKSHAW_DB = os.path.join(PARENT_DIR, "rickshaw.db")
LOG_FILE = os.path.join(SCRIPT_DIR, "engine.log")
PID_FILE = os.path.join(SCRIPT_DIR, "engine.pid")

DEFAULT_INTERVAL = 300  # 5 minutes
HEARTBEAT_INTERVAL = 6  # send heartbeat every N cycles (30 min at 5 min interval)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stderr),
    ],
)
log = logging.getLogger("engine")


def load_tg_config():
    """Load Telegram bot config for heartbeat messages."""
    # Try telegram-to-powershell config first
    if os.path.exists(TG_CONFIG):
        with open(TG_CONFIG) as f:
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
    """Send heartbeat to Telegram."""
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


def format_heartbeat(cycle, results, account, positions, strategies_active):
    """Format a heartbeat message."""
    ts = datetime.now().strftime("%H:%M:%S")
    lines = [f"[Engine {ts}] cycle #{cycle}"]

    # Account summary
    cash = float(account.get("cash", 0))
    portfolio = float(account.get("portfolio_value", 0))
    lines.append(f"Portfolio: ${portfolio:,.0f} | Cash: ${cash:,.0f}")

    # Positions summary
    if positions:
        total_pl = sum(float(p.get("unrealized_pl", 0)) for p in positions)
        lines.append(f"Positions: {len(positions)} | Unrealized P&L: ${total_pl:+,.2f}")
    else:
        lines.append("Positions: none")

    # Active strategies
    lines.append(f"Strategies: {strategies_active} active")

    # Actions this cycle
    if results:
        lines.append("Actions:")
        for r in results:
            for a in r["actions"]:
                lines.append(f"  [{r['strategy']}] {a['msg']}")
    else:
        lines.append("No actions this cycle.")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Rickshaw Engine Runner")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                        help=f"Check interval in seconds (default: {DEFAULT_INTERVAL})")
    parser.add_argument("--heartbeat-every", type=int, default=HEARTBEAT_INTERVAL,
                        help=f"Send heartbeat every N cycles (default: {HEARTBEAT_INTERVAL})")
    parser.add_argument("--always-heartbeat", action="store_true",
                        help="Send heartbeat every cycle, not just every N")
    args = parser.parse_args()

    # Load configs
    if not os.path.exists(CONFIG_FILE):
        log.error("No trader_config.json. Run: python -m trader setup")
        sys.exit(1)

    with open(CONFIG_FILE) as f:
        cfg = json.load(f)

    from trader.alpaca_client import AlpacaTrader
    from trader.strategies import tick, get_strategies, is_market_open

    trader = AlpacaTrader(cfg["alpaca_api_key"], cfg["alpaca_secret_key"],
                          paper=cfg.get("paper", True))

    tg_token, tg_chat = load_tg_config()

    # Write PID
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    log.info(f"Engine runner started (interval={args.interval}s, pid={os.getpid()})")
    log.info(f"Heartbeat: {'every cycle' if args.always_heartbeat else f'every {args.heartbeat_every} cycles'}")
    log.info(f"Telegram: {'configured' if tg_token else 'not configured'}")

    if tg_token:
        send_heartbeat(tg_token, tg_chat,
                       f"[Engine] Started. Checking every {args.interval}s. "
                       f"Heartbeat every {args.heartbeat_every} cycles.")

    cycle = 0
    market_was_open = False

    while True:
        cycle += 1

        try:
            market_open = is_market_open()

            # Market just opened
            if market_open and not market_was_open:
                log.info("Market opened!")
                if tg_token:
                    send_heartbeat(tg_token, tg_chat, "[Engine] Market opened. Strategies activating.")
                market_was_open = True

            # Market just closed
            if not market_open and market_was_open:
                log.info("Market closed.")
                # Send end-of-day summary
                account = trader.get_account()
                positions = trader.get_positions()
                from trader.strategies import get_pnl_summary
                pnl = get_pnl_summary()

                eod = f"[Engine] Market closed.\n"
                eod += f"Portfolio: ${float(account['portfolio_value']):,.0f}\n"
                eod += f"Cash: ${float(account['cash']):,.0f}\n"
                if positions:
                    total_pl = sum(float(p["unrealized_pl"]) for p in positions)
                    eod += f"Open positions: {len(positions)}, unrealized P&L: ${total_pl:+,.2f}\n"
                eod += f"Realized P&L today: ${pnl['realized_pnl']:+,.2f}"

                if tg_token:
                    send_heartbeat(tg_token, tg_chat, eod)
                log.info(eod)
                market_was_open = False

            if not market_open:
                time.sleep(args.interval)
                continue

            # Run engine tick
            results = tick(trader)

            # Log actions
            for r in results:
                for a in r["actions"]:
                    log.info(f"[{r['strategy']}] {a['msg']}")

            # Send heartbeat
            should_heartbeat = args.always_heartbeat or (cycle % args.heartbeat_every == 0)
            has_actions = bool(results)

            if should_heartbeat or has_actions:
                account = trader.get_account()
                positions = trader.get_positions()
                active = len(get_strategies(status="active")) + len(get_strategies(status="pending_fill"))

                msg = format_heartbeat(cycle, results, account, positions, active)
                log.info(msg)

                if tg_token and (has_actions or should_heartbeat):
                    send_heartbeat(tg_token, tg_chat, msg)

        except KeyboardInterrupt:
            log.info("Shutting down...")
            break
        except Exception as e:
            log.error(f"Engine error: {e}")
            if tg_token:
                send_heartbeat(tg_token, tg_chat, f"[Engine ERROR] {e}")

        time.sleep(args.interval)

    # Cleanup
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)
    log.info("Engine stopped.")


if __name__ == "__main__":
    main()
