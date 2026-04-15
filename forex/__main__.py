"""Rickshaw Forex CLI — Currency trading from the command line.

Usage:
    python -m forex                       # Interactive REPL
    python -m forex account               # Show account info
    python -m forex buy EUR_USD 1000      # Buy 1000 units EUR/USD
    python -m forex sell GBP_USD 5000     # Sell 5000 units GBP/USD
    python -m forex quote EUR_USD         # Get current quote
    python -m forex positions             # Show open positions
    python -m forex trades                # Show open trades
    python -m forex pairs                 # List popular pairs
    python -m forex watch EUR_USD GBP_USD # Live quote watch
    python -m forex candles EUR_USD H1 20 # Historical candles
    python -m forex setup                 # Configure OANDA key
"""
import argparse
import json
import os
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PARENT_DIR)

CONFIG_FILE = os.path.join(PARENT_DIR, "trader", "trader_config.json")

# Colors
CYAN = "\033[36m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"

POPULAR_PAIRS = [
    ("EUR_USD", "Euro / US Dollar"),
    ("GBP_USD", "British Pound / US Dollar"),
    ("USD_JPY", "US Dollar / Japanese Yen"),
    ("USD_CHF", "US Dollar / Swiss Franc"),
    ("AUD_USD", "Australian Dollar / US Dollar"),
    ("USD_CAD", "US Dollar / Canadian Dollar"),
    ("NZD_USD", "New Zealand Dollar / US Dollar"),
    ("EUR_GBP", "Euro / British Pound"),
    ("EUR_JPY", "Euro / Japanese Yen"),
    ("GBP_JPY", "British Pound / Japanese Yen"),
    ("EUR_CHF", "Euro / Swiss Franc"),
    ("AUD_JPY", "Australian Dollar / Japanese Yen"),
]


def load_trader():
    from trader.oanda_client import OandaTrader
    if not os.path.exists(CONFIG_FILE):
        print(f"{RED}Not configured. Run: python -m forex setup{RESET}")
        sys.exit(1)
    with open(CONFIG_FILE) as f:
        cfg = json.load(f)
    key = cfg.get("oanda_api_key", "")
    account_id = cfg.get("oanda_account_id", "")
    practice = cfg.get("oanda_practice", True)
    if not key or not account_id:
        print(f"{RED}Missing OANDA keys. Run: python -m forex setup{RESET}")
        sys.exit(1)
    return OandaTrader(key, account_id, practice=practice), cfg


# ── Commands ─────────────────────────────────────────────────────────

def cmd_setup():
    print(f"\n{BOLD}Rickshaw Forex Setup{RESET}")
    print(f"{DIM}Get keys from oanda.com > Manage API Access{RESET}\n")

    key = input("  API Key (Bearer token): ").strip()
    account_id = input("  Account ID (e.g., 101-001-12345678-001): ").strip()
    practice_input = input("  Practice account? (y/n, default y): ").strip().lower()
    practice = practice_input != "n"

    # Test connection
    print(f"\n{DIM}Testing connection...{RESET}")
    try:
        from trader.oanda_client import OandaTrader
        trader = OandaTrader(key, account_id, practice=practice)
        acct = trader.get_account()
        print(f"{GREEN}Connected!{RESET}")
        print(f"  Balance:  ${float(acct['balance']):,.2f}")
        print(f"  Currency: {acct['currency']}")
        print(f"  Mode:     {'PRACTICE' if practice else 'LIVE'}")

        # Save to shared config
        cfg = {}
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE) as f:
                cfg = json.load(f)
        cfg["oanda_api_key"] = key
        cfg["oanda_account_id"] = account_id
        cfg["oanda_practice"] = practice
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
        print(f"\n{GREEN}Saved to {CONFIG_FILE}{RESET}\n")
    except Exception as e:
        print(f"{RED}Connection failed: {e}{RESET}")


def cmd_account():
    trader, cfg = load_trader()
    acct = trader.get_account()
    mode = "PRACTICE" if cfg.get("oanda_practice", True) else "LIVE"
    market = "OPEN" if trader.is_market_open() else "CLOSED"
    market_color = GREEN if market == "OPEN" else RED

    print(f"\n{BOLD}Forex Account ({mode}){RESET}  Market: {market_color}{market}{RESET}")
    print(f"  Balance:     ${float(acct['balance']):,.2f}")
    print(f"  NAV:         ${float(acct['portfolio_value']):,.2f}")
    print(f"  Unrealized:  ${float(acct['unrealized_pl']):,.2f}")
    print(f"  Margin Used: ${float(acct['margin_used']):,.2f}")
    print(f"  Margin Free: ${float(acct['margin_available']):,.2f}")
    print(f"  Positions:   {acct['open_position_count']}")
    print(f"  Trades:      {acct['open_trade_count']}")
    print()


def cmd_buy(instrument, units, order_type="market", price=None,
            stop_loss=None, take_profit=None):
    trader, _ = load_trader()
    instrument = instrument.upper().replace("/", "_")
    print(f"{DIM}Buying {units} {instrument} ({order_type})...{RESET}")
    result = trader.buy(
        instrument, int(units), order_type=order_type,
        price=float(price) if price else None,
        stop_loss=float(stop_loss) if stop_loss else None,
        take_profit=float(take_profit) if take_profit else None,
    )
    if "error" in result:
        print(f"{RED}{result['error']}{RESET}")
    else:
        print(f"{GREEN}Filled:{RESET} {result.get('units', '?')} {instrument} @ {result.get('price', '?')}")


def cmd_sell(instrument, units, order_type="market", price=None,
             stop_loss=None, take_profit=None):
    trader, _ = load_trader()
    instrument = instrument.upper().replace("/", "_")
    print(f"{DIM}Selling {units} {instrument} ({order_type})...{RESET}")
    result = trader.sell(
        instrument, int(units), order_type=order_type,
        price=float(price) if price else None,
        stop_loss=float(stop_loss) if stop_loss else None,
        take_profit=float(take_profit) if take_profit else None,
    )
    if "error" in result:
        print(f"{RED}{result['error']}{RESET}")
    else:
        print(f"{GREEN}Filled:{RESET} {result.get('units', '?')} {instrument} @ {result.get('price', '?')}")


def cmd_quote(instruments):
    trader, _ = load_trader()
    print()
    for inst in instruments:
        inst = inst.upper().replace("/", "_")
        q = trader.get_quote(inst)
        if "error" in q:
            print(f"  {inst}: {RED}{q['error']}{RESET}")
        else:
            bid = float(q["bid"])
            ask = float(q["ask"])
            spread = q["spread_pips"]
            tradeable = "yes" if q.get("tradeable") else "no"
            print(f"  {BOLD}{inst}{RESET}  bid: {bid:.5f}  ask: {ask:.5f}  "
                  f"spread: {spread}p  tradeable: {tradeable}")
    print()


def cmd_positions():
    trader, _ = load_trader()
    positions = trader.get_positions()
    if not positions:
        print(f"{DIM}No open positions.{RESET}")
        return
    print(f"\n{BOLD}Open Positions{RESET}")
    print(f"  {'Pair':<10} {'Long':>8} {'Short':>8} {'Entry':>10} {'P&L':>10}")
    print(f"  {'-'*48}")
    for p in positions:
        pl = float(p["unrealized_pl"])
        color = GREEN if pl >= 0 else RED
        long_u = float(p.get("long_units", 0))
        short_u = float(p.get("short_units", 0))
        print(f"  {p['instrument']:<10} {long_u:>8.0f} {short_u:>8.0f} "
              f"{p['avg_entry']:>10} {color}${pl:>9,.2f}{RESET}")
    print()


def cmd_trades():
    trader, _ = load_trader()
    trades = trader.get_trades()
    if not trades:
        print(f"{DIM}No open trades.{RESET}")
        return
    print(f"\n{BOLD}Open Trades{RESET}")
    print(f"  {'ID':<6} {'Pair':<10} {'Side':<5} {'Units':>8} {'Price':>10} {'P&L':>10}")
    print(f"  {'-'*52}")
    for t in trades:
        pl = float(t.get("unrealized_pl", 0))
        color = GREEN if pl >= 0 else RED
        print(f"  {t['id']:<6} {t['instrument']:<10} {t['side']:<5} "
              f"{t['units']:>8} {t['price']:>10} {color}${pl:>9,.2f}{RESET}")
    print()


def cmd_close(instrument=None):
    trader, _ = load_trader()
    if instrument:
        instrument = instrument.upper().replace("/", "_")
        result = trader.close_position(instrument)
        if "error" in result:
            print(f"{RED}{result['error']}{RESET}")
        else:
            print(f"{GREEN}Closed {instrument}{RESET}")
    else:
        confirm = input(f"{YELLOW}Close ALL forex positions? (y/n): {RESET}").strip().lower()
        if confirm != "y":
            print("Cancelled.")
            return
        result = trader.close_all()
        print(f"{GREEN}{result['status']} ({result['count']} positions){RESET}")


def cmd_orders(status="pending"):
    trader, _ = load_trader()
    orders = trader.get_orders(status=status)
    if not orders:
        print(f"{DIM}No {status} orders.{RESET}")
        return
    print(f"\n{BOLD}Orders ({status}){RESET}")
    for o in orders:
        print(f"  {o['id']}  {o['instrument']}  {o['units']} units  "
              f"type={o['type']}  status={o['status']}")
    print()


def cmd_cancel(order_id=None):
    trader, _ = load_trader()
    if order_id:
        result = trader.cancel_order(order_id)
    else:
        confirm = input(f"{YELLOW}Cancel ALL pending orders? (y/n): {RESET}").strip().lower()
        if confirm != "y":
            return
        result = trader.cancel_all()
    print(f"{GREEN}{result.get('status', 'done')}{RESET}")


def cmd_pairs():
    trader, _ = load_trader()
    print(f"\n{BOLD}Popular Currency Pairs{RESET}")
    for pair, name in POPULAR_PAIRS:
        q = trader.get_quote(pair)
        if "error" not in q:
            bid = float(q["bid"])
            ask = float(q["ask"])
            spread = q["spread_pips"]
            print(f"  {BOLD}{pair:<10}{RESET} {name:<35} "
                  f"bid: {bid:.5f}  ask: {ask:.5f}  spread: {spread}p")
        else:
            print(f"  {BOLD}{pair:<10}{RESET} {name:<35} {DIM}unavailable{RESET}")
    print()


def cmd_watch(instruments, interval=5):
    trader, _ = load_trader()
    instruments = [i.upper().replace("/", "_") for i in instruments]
    print(f"{BOLD}Watching: {', '.join(instruments)}{RESET}")
    print(f"{DIM}Refreshing every {interval}s. Ctrl+C to stop.{RESET}\n")
    try:
        while True:
            line = f"  {time.strftime('%H:%M:%S')}  "
            for inst in instruments:
                q = trader.get_quote(inst)
                if "error" not in q:
                    mid = float(q["mid"])
                    spread = q["spread_pips"]
                    line += f"{BOLD}{inst}{RESET}: {mid:.5f} ({spread}p)  "
            print(line)
            time.sleep(interval)
    except KeyboardInterrupt:
        print(f"\n{DIM}Stopped.{RESET}")


def cmd_candles(instrument, granularity="H1", count=20):
    trader, _ = load_trader()
    instrument = instrument.upper().replace("/", "_")
    candles = trader.get_candles(instrument, granularity, int(count))
    if not candles:
        print(f"{DIM}No candle data.{RESET}")
        return
    print(f"\n{BOLD}{instrument} {granularity} (last {count}){RESET}")
    print(f"  {'Time':<18} {'Open':>10} {'High':>10} {'Low':>10} {'Close':>10} {'Vol':>6}")
    print(f"  {'-'*68}")
    for c in candles:
        t = c["time"][:16].replace("T", " ")
        color = GREEN if c["close"] >= c["open"] else RED
        print(f"  {t:<18} {c['open']:>10.5f} {c['high']:>10.5f} "
              f"{c['low']:>10.5f} {color}{c['close']:>10.5f}{RESET} {c['volume']:>6}")
    print()


# ── Strategy Commands ────────────────────────────────────────────────

def cmd_trailing_stop(instrument, units, stop_pips=50, trail_pips=30,
                      tp_pips=100, max_spread=5.0, ladders=""):
    from forex.strategies import create_trailing_stop
    trader, _ = load_trader()
    instrument = instrument.upper().replace("/", "_")

    ladder_drops = []
    if ladders:
        for pair in ladders.split(","):
            parts = pair.strip().split(":")
            if len(parts) == 2:
                ladder_drops.append([float(parts[0]), int(parts[1])])

    print(f"{DIM}Creating forex trailing stop on {instrument}...{RESET}")
    result = create_trailing_stop(
        trader, instrument, int(units),
        stop_pips=float(stop_pips), trail_pips=float(trail_pips),
        take_profit_pips=float(tp_pips), max_spread=float(max_spread),
        ladder_drops=ladder_drops,
    )
    if "error" in result:
        print(f"{RED}{result['error']}{RESET}")
    else:
        print(f"{GREEN}Strategy {result['id']} created:{RESET}")
        print(f"  {result['log'][0]['msg']}")


def cmd_short(instrument, units, stop_pips=50, trail_pips=30, tp_pips=100):
    from forex.strategies import create_short
    trader, _ = load_trader()
    instrument = instrument.upper().replace("/", "_")

    print(f"{DIM}Creating short on {instrument}...{RESET}")
    result = create_short(
        trader, instrument, int(units),
        stop_pips=float(stop_pips), trail_pips=float(trail_pips),
        take_profit_pips=float(tp_pips),
    )
    if "error" in result:
        print(f"{RED}{result['error']}{RESET}")
    else:
        print(f"{GREEN}Strategy {result['id']} created:{RESET}")
        print(f"  {result['log'][0]['msg']}")


def cmd_strategies():
    from forex.strategies import get_strategies
    strategies = get_strategies()
    if not strategies:
        print(f"{DIM}No forex strategies.{RESET}")
        return
    print(f"\n{BOLD}Forex Strategies{RESET}")
    for s in strategies:
        color = GREEN if s["status"] == "active" else DIM
        state = s.get("state", {})
        if s["type"] == "forex_trailing_stop":
            floor = state.get("current_floor", 0)
            high = state.get("highest_price", 0)
            units = state.get("total_units", 0)
            extra = f"floor={floor:.5f} high={high:.5f} units={units}"
        elif s["type"] == "forex_short":
            ceiling = state.get("current_ceiling", 0)
            low = state.get("lowest_price", 0)
            units = state.get("total_units", 0)
            extra = f"ceiling={ceiling:.5f} low={low:.5f} units={units}"
        else:
            extra = ""
        print(f"  {color}{s['id']:<28} {s['type']:<20} {s['status']:<10} {extra}{RESET}")
    print()


def cmd_strategy_log(strategy_id):
    from forex.strategies import get_strategy
    s = get_strategy(strategy_id)
    if not s:
        print(f"{RED}Strategy {strategy_id} not found.{RESET}")
        return
    print(f"\n{BOLD}Log for {s['id']} ({s['type']}, {s['status']}){RESET}")
    for entry in s.get("log", []):
        print(f"  {entry['time'][:19]} | {entry['msg']}")
    print()


def cmd_cancel_strategy(strategy_id):
    from forex.strategies import cancel_strategy
    result = cancel_strategy(strategy_id)
    if result:
        print(f"{GREEN}Cancelled {strategy_id}{RESET}")
    else:
        print(f"{RED}Strategy {strategy_id} not found.{RESET}")


def cmd_tick():
    from forex.strategies import tick
    trader, _ = load_trader()
    print(f"{DIM}Running forex strategy check...{RESET}")
    results = tick(trader)
    if not results:
        print(f"{DIM}No actions taken.{RESET}")
    else:
        for r in results:
            for a in r["actions"]:
                color = GREEN if "buy" in a.get("action", "") else (
                    RED if "sell" in a.get("action", "") or "close" in a.get("action", "") else YELLOW)
                print(f"  {color}[{r['strategy']}] {a['msg']}{RESET}")


def cmd_run(interval=60):
    from forex.strategies import tick, is_forex_open
    trader, _ = load_trader()
    print(f"{BOLD}Forex engine running{RESET} (checking every {interval}s)")
    print(f"{DIM}Ctrl+C to stop{RESET}\n")
    try:
        while True:
            ts = time.strftime("%H:%M:%S")
            if not is_forex_open():
                print(f"  {ts} {DIM}forex closed (weekend){RESET}")
                time.sleep(300)
                continue

            results = tick(trader)
            if results:
                for r in results:
                    for a in r["actions"]:
                        color = GREEN if "buy" in a.get("action", "") else (
                            RED if "close" in a.get("action", "") else YELLOW)
                        print(f"  {ts} {color}[{r['strategy']}] {a['msg']}{RESET}")
            else:
                print(f"  {ts} {DIM}no actions{RESET}")
            time.sleep(interval)
    except KeyboardInterrupt:
        print(f"\n{DIM}Engine stopped.{RESET}")


def cmd_pnl():
    from forex.strategies import get_pnl_summary
    s = get_pnl_summary()
    print(f"\n{BOLD}Forex P&L Summary{RESET}")
    print(f"  Total trades: {s['total_trades']}")
    print(f"  Buys:  {s['buys']}")
    print(f"  Sells: {s['sells']}")
    pips = s["realized_pnl_pips"]
    color = GREEN if pips >= 0 else RED
    print(f"  Realized P&L: {color}{pips:+.1f} pips{RESET}")
    if s.get("last_trade"):
        lt = s["last_trade"]
        print(f"  Last: {lt['action']} {lt.get('instrument', '')} @ {lt['time'][:19]}")
    print()


# ── Signal & Analysis Commands ──────────────────────────────────────

def cmd_analyze(instrument, timeframe="H1"):
    """Run full signal analysis on a pair."""
    from forex.signals import analyze_pair, format_signal_report
    trader, _ = load_trader()
    instrument = instrument.upper().replace("/", "_")
    print(f"{DIM}Analyzing {instrument} ({timeframe})...{RESET}\n")
    analysis = analyze_pair(trader, instrument, timeframe=timeframe)
    print(format_signal_report(analysis))
    print()


def cmd_scan(timeframe="H1"):
    """Scan all major pairs and rank by signal strength."""
    from forex.signals import scan_pairs, format_signal_report
    trader, _ = load_trader()
    print(f"{DIM}Scanning major pairs ({timeframe})...{RESET}\n")
    results = scan_pairs(trader, timeframe=timeframe)
    for r in results:
        if "error" in r:
            print(f"  {r['instrument']}: {RED}{r['error']}{RESET}")
            continue
        comp = r.get("composite", {})
        conf = comp.get("confidence", 0)
        rec = comp.get("recommendation", "no_trade")
        bull = comp.get("bullish", 0)
        bear = comp.get("bearish", 0)
        price = r.get("current_price", 0)
        spread = r.get("spread_pips", 0)

        if conf > 0.5:
            color = GREEN if "buy" in rec else RED
        elif conf > 0.2:
            color = YELLOW
        else:
            color = DIM

        arrow = "^" if "buy" in rec else "v" if "sell" in rec else "-"
        print(f"  {color}{arrow} {r['instrument']:<10} {rec:<12} conf={conf:.0%}  "
              f"({bull}B {bear}S)  price={price:.5f}  spread={spread}p{RESET}")
    print()


def cmd_regime(instrument, timeframe="H4"):
    """Detect market regime for a pair."""
    from forex.brain import detect_regime
    trader, _ = load_trader()
    instrument = instrument.upper().replace("/", "_")
    candles = trader.get_candles(instrument, timeframe, 200)
    print(f"{DIM}Detecting regime for {instrument} ({timeframe})...{RESET}\n")
    regime = detect_regime(candles)
    print(f"  Regime:     {BOLD}{regime['regime'].upper()}{RESET}")
    print(f"  Direction:  {regime.get('trend_direction', 'N/A')}")
    print(f"  Volatility: {regime.get('volatility', 'N/A')}")
    print(f"  ADX:        {regime.get('adx', 'N/A')}")
    print(f"  ATR:        {regime.get('atr', 'N/A')}")
    print(f"  Confidence: {regime.get('confidence', 0):.0%}")
    if "ai_assessment" in regime:
        print(f"\n  {CYAN}AI: {regime['ai_assessment']}{RESET}")
    print()


def cmd_sentiment(text, source="news"):
    """Score text for market sentiment."""
    from forex.brain import score_sentiment
    print(f"{DIM}Scoring sentiment...{RESET}\n")
    result = score_sentiment(text, source)
    score = result.get("score", 0)
    color = GREEN if score > 0 else RED if score < 0 else DIM
    print(f"  Score:      {color}{score:+.2f}{RESET}")
    print(f"  Bias:       {result.get('bias', 'N/A')}")
    print(f"  Confidence: {result.get('confidence', 0):.0%}")
    if result.get("key_phrases"):
        print(f"  Key:        {', '.join(result['key_phrases'][:5])}")
    if result.get("summary"):
        print(f"  Summary:    {result['summary']}")
    print()


def cmd_brain(mode=None):
    """Show or set brain mode."""
    from forex.brain import get_brain_mode, set_brain_mode
    if mode:
        result = set_brain_mode(mode)
        if "error" in result:
            print(f"{RED}{result['error']}{RESET}")
        else:
            print(f"{GREEN}Brain mode set to: {mode}{RESET}")
    else:
        current = get_brain_mode()
        print(f"  Brain mode: {BOLD}{current}{RESET}")
        print(f"  Options: auto (rules only), qwen (local AI), opus (Claude API)")


def cmd_daily_analysis():
    """Generate comprehensive daily analysis."""
    from forex.brain import daily_analysis
    trader, _ = load_trader()
    print(f"{DIM}Generating daily analysis...{RESET}\n")
    result = daily_analysis(trader)
    print(f"{BOLD}=== DAILY FOREX ANALYSIS ==={RESET}")
    print(result.get("analysis", "No analysis available"))
    print(f"{BOLD}=== END ==={RESET}\n")


def cmd_session():
    """Show current trading session info."""
    from forex.strategies import get_active_session
    s = get_active_session()
    print(f"\n{BOLD}Trading Session{RESET}")
    print(f"  UTC Hour:    {s['hour_utc']}:00")
    print(f"  Sessions:    {', '.join(s['sessions']) or 'none (gap)'}")
    print(f"  Overlap:     {'YES (best liquidity)' if s['overlap'] else 'no'}")
    print(f"  Liquidity:   {s['liquidity']:.0%}")
    print(f"  Best pairs:  {', '.join(s['best_pairs'][:6])}")
    print()


def cmd_auto(max_positions=6):
    """Run auto-scanner once: scan for signals and deploy."""
    from forex.strategies import auto_scan_and_deploy
    trader, _ = load_trader()
    print(f"{DIM}Running auto-scanner (max {max_positions} positions)...{RESET}\n")
    results = auto_scan_and_deploy(trader, max_positions=max_positions)
    for a in results:
        if "deploy" in a.get("action", ""):
            print(f"  {GREEN}{a['msg']}{RESET}")
        elif "error" in a.get("action", ""):
            print(f"  {RED}{a['msg']}{RESET}")
        else:
            print(f"  {DIM}{a['msg']}{RESET}")
    print()


# ── REPL ─────────────────────────────────────────────────────────────

def repl():
    print(f"\n{BOLD}Rickshaw Forex{RESET}")
    try:
        trader, cfg = load_trader()
        mode = "PRACTICE" if cfg.get("oanda_practice", True) else "LIVE"
        acct = trader.get_account()
        market = "OPEN" if trader.is_market_open() else "CLOSED"
        market_color = GREEN if market == "OPEN" else RED
        print(f"  {mode} | Balance: ${float(acct['balance']):,.2f} | "
              f"NAV: ${float(acct['portfolio_value']):,.2f} | "
              f"Market: {market_color}{market}{RESET}")
    except SystemExit:
        print(f"{YELLOW}Run 'python -m forex setup' first{RESET}")
        return
    except Exception as e:
        print(f"{RED}Connection error: {e}{RESET}")
        return

    print(f"{DIM}Commands: buy, sell, quote, positions, trades, close, watch, pairs,{RESET}")
    print(f"{DIM}  candles, trailing, short, strategies, tick, run, pnl,{RESET}")
    print(f"{DIM}  analyze, scan, regime, sentiment, brain, daily, help, quit{RESET}\n")

    while True:
        try:
            line = input(f"{CYAN}forex> {RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not line:
            continue

        parts = line.split()
        cmd = parts[0].lower()

        try:
            if cmd in ("quit", "exit", "q"):
                break
            elif cmd == "help":
                print(f"""
  {BOLD}Trading:{RESET}
  buy <PAIR> <UNITS> [limit <P>] [sl <P>] [tp <P>]
  sell <PAIR> <UNITS> [limit <P>] [sl <P>] [tp <P>]
  quote <PAIR> [PAIR2 ...]      positions       trades
  close [PAIR]                   orders          cancel [ORDER_ID]
  watch <PAIR> [PAIR2 ...] [interval <SEC>]
  pairs                          candles <PAIR> [GRAN] [COUNT]
  account

  {BOLD}Strategies:{RESET}
  trailing <PAIR> <UNITS> [stop <PIPS>] [trail <PIPS>] [tp <PIPS>] [spread <MAX>]
  short <PAIR> <UNITS> [stop <PIPS>] [trail <PIPS>] [tp <PIPS>]
  strategies                    list all strategies
  log <STRATEGY_ID>             show strategy log
  stop <STRATEGY_ID>            cancel a strategy
  tick                          run one check cycle
  run [INTERVAL_SEC]            run engine loop (default 60s)
  pnl                           P&L summary

  {BOLD}Analysis (AI-powered):{RESET}
  analyze <PAIR> [TIMEFRAME]    full signal analysis (all indicators + AI)
  scan [TIMEFRAME]              scan all majors, rank by signal strength
  regime <PAIR> [TIMEFRAME]     detect market regime (trending/ranging/volatile)
  sentiment <TEXT>              score text for market sentiment
  brain [auto|qwen|opus]        show/set AI brain mode
  daily                         comprehensive daily analysis

  {BOLD}Pairs:{RESET} EUR_USD, GBP_USD, USD_JPY, AUD_USD, USD_CAD, etc.
  {BOLD}Units:{RESET} 1000=micro lot, 10000=mini lot, 100000=standard lot
  {BOLD}Granularity:{RESET} S5, M1, M5, M15, H1, H4, D, W, M
""")
            elif cmd == "account":
                cmd_account()
            elif cmd == "buy" and len(parts) >= 3:
                kwargs = _parse_fx_args(parts[3:])
                cmd_buy(parts[1], parts[2], **kwargs)
            elif cmd == "sell" and len(parts) >= 3:
                kwargs = _parse_fx_args(parts[3:])
                cmd_sell(parts[1], parts[2], **kwargs)
            elif cmd == "quote" and len(parts) >= 2:
                cmd_quote(parts[1:])
            elif cmd in ("positions", "pos"):
                cmd_positions()
            elif cmd == "trades":
                cmd_trades()
            elif cmd == "close":
                inst = parts[1] if len(parts) > 1 else None
                cmd_close(inst)
            elif cmd == "orders":
                status = parts[1] if len(parts) > 1 else "pending"
                cmd_orders(status)
            elif cmd == "cancel":
                oid = parts[1] if len(parts) > 1 else None
                cmd_cancel(oid)
            elif cmd == "pairs":
                cmd_pairs()
            elif cmd == "watch" and len(parts) >= 2:
                interval = 5
                insts = []
                i = 1
                while i < len(parts):
                    if parts[i] == "interval" and i + 1 < len(parts):
                        interval = int(parts[i + 1])
                        i += 2
                    else:
                        insts.append(parts[i])
                        i += 1
                cmd_watch(insts, interval)
            elif cmd == "candles" and len(parts) >= 2:
                gran = parts[2] if len(parts) > 2 else "H1"
                count = parts[3] if len(parts) > 3 else 20
                cmd_candles(parts[1], gran, count)
            elif cmd == "trailing" and len(parts) >= 3:
                stop = 50; trail = 30; tp = 100; spread = 5.0; ladders = ""
                i = 3
                while i < len(parts):
                    if parts[i] == "stop" and i+1 < len(parts):
                        stop = parts[i+1]; i += 2
                    elif parts[i] == "trail" and i+1 < len(parts):
                        trail = parts[i+1]; i += 2
                    elif parts[i] == "tp" and i+1 < len(parts):
                        tp = parts[i+1]; i += 2
                    elif parts[i] == "spread" and i+1 < len(parts):
                        spread = parts[i+1]; i += 2
                    elif parts[i] == "ladders" and i+1 < len(parts):
                        ladders = parts[i+1]; i += 2
                    else:
                        i += 1
                cmd_trailing_stop(parts[1], parts[2], stop, trail, tp, spread, ladders)
            elif cmd == "short" and len(parts) >= 3:
                stop = 50; trail = 30; tp = 100
                i = 3
                while i < len(parts):
                    if parts[i] == "stop" and i+1 < len(parts):
                        stop = parts[i+1]; i += 2
                    elif parts[i] == "trail" and i+1 < len(parts):
                        trail = parts[i+1]; i += 2
                    elif parts[i] == "tp" and i+1 < len(parts):
                        tp = parts[i+1]; i += 2
                    else:
                        i += 1
                cmd_short(parts[1], parts[2], stop, trail, tp)
            elif cmd in ("strategies", "strats"):
                cmd_strategies()
            elif cmd == "log" and len(parts) >= 2:
                cmd_strategy_log(parts[1])
            elif cmd == "stop" and len(parts) >= 2:
                cmd_cancel_strategy(parts[1])
            elif cmd == "tick":
                cmd_tick()
            elif cmd == "run":
                interval = int(parts[1]) if len(parts) > 1 else 60
                cmd_run(interval)
            elif cmd == "pnl":
                cmd_pnl()
            elif cmd == "analyze" and len(parts) >= 2:
                tf = parts[2] if len(parts) > 2 else "H1"
                cmd_analyze(parts[1], tf)
            elif cmd == "scan":
                tf = parts[1] if len(parts) > 1 else "H1"
                cmd_scan(tf)
            elif cmd == "regime" and len(parts) >= 2:
                tf = parts[2] if len(parts) > 2 else "H4"
                cmd_regime(parts[1], tf)
            elif cmd == "sentiment" and len(parts) >= 2:
                text = " ".join(parts[1:])
                cmd_sentiment(text)
            elif cmd == "brain":
                mode = parts[1] if len(parts) > 1 else None
                cmd_brain(mode)
            elif cmd == "daily":
                cmd_daily_analysis()
            elif cmd == "session":
                cmd_session()
            elif cmd == "auto":
                max_pos = int(parts[1]) if len(parts) > 1 else 6
                cmd_auto(max_pos)
            else:
                print(f"{DIM}Unknown command. Type 'help'{RESET}")
        except Exception as e:
            print(f"{RED}Error: {e}{RESET}")

    print(f"{DIM}Goodbye.{RESET}")


def _parse_fx_args(args):
    """Parse optional order args: limit <price>, sl <price>, tp <price>."""
    kwargs = {}
    i = 0
    while i < len(args):
        if args[i] == "limit" and i + 1 < len(args):
            kwargs["order_type"] = "limit"
            kwargs["price"] = args[i + 1]
            i += 2
        elif args[i] == "sl" and i + 1 < len(args):
            kwargs["stop_loss"] = args[i + 1]
            i += 2
        elif args[i] == "tp" and i + 1 < len(args):
            kwargs["take_profit"] = args[i + 1]
            i += 2
        else:
            i += 1
    return kwargs


# ── Main ─────────────────────────────────────────────────────────────

def main():
    parent = os.path.dirname(SCRIPT_DIR)
    if parent not in sys.path:
        sys.path.insert(0, parent)

    parser = argparse.ArgumentParser(description="Rickshaw Forex")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("setup", help="Configure OANDA API key")
    sub.add_parser("account", help="Show account info")

    buy_p = sub.add_parser("buy", help="Buy currency pair")
    buy_p.add_argument("instrument")
    buy_p.add_argument("units", type=int)

    sell_p = sub.add_parser("sell", help="Sell currency pair")
    sell_p.add_argument("instrument")
    sell_p.add_argument("units", type=int)

    quote_p = sub.add_parser("quote", help="Get currency quote")
    quote_p.add_argument("instruments", nargs="+")

    sub.add_parser("positions", help="Show open positions")
    sub.add_parser("trades", help="Show open trades")
    sub.add_parser("pairs", help="List popular pairs with quotes")

    close_p = sub.add_parser("close", help="Close position")
    close_p.add_argument("instrument", nargs="?", default=None)

    watch_p = sub.add_parser("watch", help="Watch quotes live")
    watch_p.add_argument("instruments", nargs="+")
    watch_p.add_argument("--interval", type=int, default=5)

    candle_p = sub.add_parser("candles", help="Historical candles")
    candle_p.add_argument("instrument")
    candle_p.add_argument("granularity", nargs="?", default="H1")
    candle_p.add_argument("count", nargs="?", type=int, default=20)

    args = parser.parse_args()

    if args.command == "setup":
        cmd_setup()
    elif args.command == "account":
        cmd_account()
    elif args.command == "buy":
        cmd_buy(args.instrument, args.units)
    elif args.command == "sell":
        cmd_sell(args.instrument, args.units)
    elif args.command == "quote":
        cmd_quote(args.instruments)
    elif args.command == "positions":
        cmd_positions()
    elif args.command == "trades":
        cmd_trades()
    elif args.command == "pairs":
        cmd_pairs()
    elif args.command == "close":
        cmd_close(args.instrument)
    elif args.command == "watch":
        cmd_watch(args.instruments, args.interval)
    elif args.command == "candles":
        cmd_candles(args.instrument, args.granularity, args.count)
    elif args.command is None:
        repl()


if __name__ == "__main__":
    main()
