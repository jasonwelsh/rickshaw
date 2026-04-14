"""Rickshaw Trader CLI — Stock trading from the command line.

Usage:
    python -m trader                    # Interactive REPL
    python -m trader account            # Show account info
    python -m trader buy AAPL 10        # Buy 10 shares of Apple
    python -m trader sell TSLA 5        # Sell 5 shares of Tesla
    python -m trader quote AAPL         # Get current quote
    python -m trader positions          # Show open positions
    python -m trader orders             # Show open orders
    python -m trader watch AAPL TSLA    # Live quote watch
    python -m trader politicians        # Top trading politicians
    python -m trader trades             # Recent politician trades
    python -m trader setup              # Configure API keys
"""
import argparse
import json
import os
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "trader_config.json")

# Colors
CYAN = "\033[36m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def load_trader():
    from trader.alpaca_client import AlpacaTrader
    if not os.path.exists(CONFIG_FILE):
        print(f"{RED}Not configured. Run: python -m trader setup{RESET}")
        sys.exit(1)
    with open(CONFIG_FILE) as f:
        cfg = json.load(f)
    key = cfg.get("alpaca_api_key", "")
    secret = cfg.get("alpaca_secret_key", "")
    paper = cfg.get("paper", True)
    if not key or not secret:
        print(f"{RED}Missing API keys. Run: python -m trader setup{RESET}")
        sys.exit(1)
    return AlpacaTrader(key, secret, paper=paper), cfg


# ── Commands ─────────────────────────────────────────────────────────

def cmd_setup():
    print(f"\n{BOLD}Rickshaw Trader Setup{RESET}")
    print(f"{DIM}Get keys from alpaca.markets > Paper Trading > API Keys{RESET}\n")

    key = input("  API Key: ").strip()
    secret = input("  Secret Key: ").strip()
    paper_input = input("  Paper trading? (y/n, default y): ").strip().lower()
    paper = paper_input != "n"

    cfg = {"alpaca_api_key": key, "alpaca_secret_key": secret, "paper": paper}

    # Test connection
    print(f"\n{DIM}Testing connection...{RESET}")
    try:
        from trader.alpaca_client import AlpacaTrader
        trader = AlpacaTrader(key, secret, paper=paper)
        acct = trader.get_account()
        print(f"{GREEN}Connected!{RESET}")
        print(f"  Status: {acct['status']}")
        print(f"  Cash: ${acct['cash']}")
        print(f"  Portfolio: ${acct['portfolio_value']}")
        print(f"  Mode: {'PAPER' if paper else 'LIVE'}")

        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
        print(f"\n{GREEN}Saved to {CONFIG_FILE}{RESET}\n")
    except Exception as e:
        print(f"{RED}Connection failed: {e}{RESET}")


def cmd_account():
    trader, _ = load_trader()
    acct = trader.get_account()
    mode = "PAPER" if _.get("paper", True) else "LIVE"
    print(f"\n{BOLD}Account ({mode}){RESET}")
    print(f"  Status:     {acct['status']}")
    print(f"  Cash:       ${float(acct['cash']):,.2f}")
    print(f"  Buying Power: ${float(acct['buying_power']):,.2f}")
    print(f"  Portfolio:  ${float(acct['portfolio_value']):,.2f}")
    print(f"  Equity:     ${float(acct['equity']):,.2f}")
    print()


def cmd_buy(symbol, qty, order_type="market", limit_price=None,
            stop_price=None, trail_percent=None):
    trader, _ = load_trader()
    print(f"{DIM}Buying {qty} x {symbol} ({order_type})...{RESET}")
    result = trader.buy(
        symbol=symbol.upper(), qty=int(qty), order_type=order_type,
        limit_price=float(limit_price) if limit_price else None,
        stop_price=float(stop_price) if stop_price else None,
        trail_percent=float(trail_percent) if trail_percent else None,
    )
    if "error" in result:
        print(f"{RED}{result['error']}{RESET}")
    else:
        print(f"{GREEN}Order placed:{RESET}")
        _print_order(result)


def cmd_sell(symbol, qty, order_type="market", limit_price=None,
             stop_price=None, trail_percent=None):
    trader, _ = load_trader()
    print(f"{DIM}Selling {qty} x {symbol} ({order_type})...{RESET}")
    result = trader.sell(
        symbol=symbol.upper(), qty=int(qty), order_type=order_type,
        limit_price=float(limit_price) if limit_price else None,
        stop_price=float(stop_price) if stop_price else None,
        trail_percent=float(trail_percent) if trail_percent else None,
    )
    if "error" in result:
        print(f"{RED}{result['error']}{RESET}")
    else:
        print(f"{GREEN}Order placed:{RESET}")
        _print_order(result)


def cmd_quote(symbols):
    trader, _ = load_trader()
    for sym in symbols:
        q = trader.get_quote(sym.upper())
        if "error" in q:
            print(f"  {sym}: {RED}{q['error']}{RESET}")
        else:
            bid = float(q['bid'])
            ask = float(q['ask'])
            spread = ask - bid
            print(f"  {BOLD}{q['symbol']}{RESET}  bid: ${bid:,.2f}  ask: ${ask:,.2f}  spread: ${spread:,.2f}")


def cmd_positions():
    trader, _ = load_trader()
    positions = trader.get_positions()
    if not positions:
        print(f"{DIM}No open positions.{RESET}")
        return
    print(f"\n{BOLD}Open Positions{RESET}")
    print(f"  {'Symbol':<8} {'Qty':>6} {'Avg Entry':>10} {'Current':>10} {'P&L':>12} {'P&L%':>8}")
    print(f"  {'-'*56}")
    for p in positions:
        pl = float(p['unrealized_pl'])
        plpc = float(p['unrealized_plpc']) * 100
        color = GREEN if pl >= 0 else RED
        print(f"  {p['symbol']:<8} {p['qty']:>6} ${float(p['avg_entry']):>9,.2f} ${float(p['current_price']):>9,.2f} {color}${pl:>11,.2f} {plpc:>7,.2f}%{RESET}")
    print()


def cmd_orders(status="open"):
    trader, _ = load_trader()
    orders = trader.get_orders(status=status)
    if not orders:
        print(f"{DIM}No {status} orders.{RESET}")
        return
    print(f"\n{BOLD}Orders ({status}){RESET}")
    for o in orders:
        _print_order(o)
    print()


def cmd_cancel(order_id=None):
    trader, _ = load_trader()
    if order_id:
        result = trader.cancel_order(order_id)
    else:
        confirm = input(f"{YELLOW}Cancel ALL open orders? (y/n): {RESET}").strip().lower()
        if confirm != "y":
            print("Cancelled.")
            return
        result = trader.cancel_all()
    print(f"{GREEN}{result['status']}{RESET}")


def cmd_close(symbol=None):
    trader, _ = load_trader()
    if symbol:
        result = trader.close_position(symbol.upper())
        print(f"{GREEN}Closed {symbol}: {result['status']}{RESET}")
    else:
        confirm = input(f"{YELLOW}Close ALL positions? (y/n): {RESET}").strip().lower()
        if confirm != "y":
            print("Cancelled.")
            return
        result = trader.close_all()
        print(f"{GREEN}{result['status']}{RESET}")


def cmd_watch(symbols, interval=5):
    trader, _ = load_trader()
    print(f"{BOLD}Watching: {', '.join(s.upper() for s in symbols)}{RESET}")
    print(f"{DIM}Refreshing every {interval}s. Ctrl+C to stop.{RESET}\n")
    try:
        while True:
            line = f"  {time.strftime('%H:%M:%S')}  "
            for sym in symbols:
                q = trader.get_quote(sym.upper())
                if "error" not in q:
                    bid = float(q['bid'])
                    ask = float(q['ask'])
                    mid = (bid + ask) / 2
                    line += f"{BOLD}{sym.upper()}{RESET}: ${mid:,.2f}  "
            print(line)
            time.sleep(interval)
    except KeyboardInterrupt:
        print(f"\n{DIM}Stopped.{RESET}")


def cmd_politicians():
    from trader import capitol_trades
    print(f"{DIM}Fetching top trading politicians...{RESET}")
    result = capitol_trades.get_top_traders()
    if isinstance(result, dict) and "error" in result:
        print(f"{RED}{result['error']}{RESET}")
        return
    if isinstance(result, dict) and "raw_text" in result:
        print(f"{YELLOW}Raw data (site uses JS rendering):{RESET}")
        print(result["raw_text"][:1000])
        return
    if isinstance(result, list):
        for p in result:
            print(f"  {p.get('name', '?')}: {p.get('url', '')}")
    else:
        print(json.dumps(result, indent=2)[:1000])


def cmd_trades():
    from trader import capitol_trades
    print(f"{DIM}Fetching recent politician trades...{RESET}")
    result = capitol_trades.get_recent_trades()
    if isinstance(result, dict) and "raw_text" in result:
        print(f"{YELLOW}Raw data:{RESET}")
        print(result["raw_text"][:1500])
        return
    if isinstance(result, list):
        for t in result:
            action_color = GREEN if t.get('action') == 'buy' else RED
            print(f"  {action_color}{t.get('action','?'):>4}{RESET} {t.get('symbol','?'):<6} ${t.get('amount','?')}")
    else:
        print(json.dumps(result, indent=2)[:1000])


def cmd_trailing_stop(symbol, qty, stop_pct=10, trail_pct=5, ladders=""):
    from trader.strategies import create_trailing_stop
    trader, _ = load_trader()

    ladder_drops = []
    if ladders:
        for pair in ladders.split(","):
            parts = pair.strip().split(":")
            if len(parts) == 2:
                ladder_drops.append((float(parts[0]), int(parts[1])))

    print(f"{DIM}Creating trailing stop on {symbol}...{RESET}")
    result = create_trailing_stop(
        trader, symbol.upper(), int(qty),
        stop_pct=float(stop_pct), trail_pct=float(trail_pct),
        ladder_drops=ladder_drops,
    )
    if "error" in result:
        print(f"{RED}{result['error']}{RESET}")
    else:
        print(f"{GREEN}Strategy {result['id']} created:{RESET}")
        print(f"  {result['log'][0]['msg']}")
        if ladder_drops:
            print(f"  Ladders: {ladder_drops}")


def cmd_copy_trade(politician, max_per_trade=5000):
    from trader.strategies import create_copy_strategy
    trader, _ = load_trader()
    print(f"{DIM}Creating copy strategy for {politician}...{RESET}")
    result = create_copy_strategy(trader, politician, max_per_trade=float(max_per_trade))
    print(f"{GREEN}Strategy {result['id']} created:{RESET}")
    print(f"  {result['log'][0]['msg']}")


def cmd_strategies():
    from trader.strategies import get_strategies
    strategies = get_strategies()
    if not strategies:
        print(f"{DIM}No strategies.{RESET}")
        return
    print(f"\n{BOLD}Strategies{RESET}")
    for s in strategies:
        color = GREEN if s["status"] == "active" else DIM
        state = s.get("state", {})
        extra = ""
        if s["type"] == "trailing_stop":
            floor = state.get("current_floor", 0)
            high = state.get("highest_price", 0)
            qty = state.get("total_qty", 0)
            extra = f"floor=${floor:,.2f} high=${high:,.2f} qty={qty}"
        elif s["type"] == "copy_trade":
            extra = f"politician={s['config'].get('politician','?')}"
        print(f"  {color}{s['id']:<20} {s['type']:<15} {s['status']:<10} {extra}{RESET}")
    print()


def cmd_strategy_log(strategy_id):
    from trader.strategies import get_strategy
    s = get_strategy(strategy_id)
    if not s:
        print(f"{RED}Strategy {strategy_id} not found.{RESET}")
        return
    print(f"\n{BOLD}Log for {s['id']} ({s['type']}, {s['status']}){RESET}")
    for entry in s.get("log", []):
        print(f"  {entry['time'][:19]} | {entry['msg']}")
    print()


def cmd_engine_tick():
    from trader.strategies import tick
    trader, _ = load_trader()
    print(f"{DIM}Running strategy check...{RESET}")
    results = tick(trader)
    if not results:
        print(f"{DIM}No actions taken.{RESET}")
    else:
        for r in results:
            for a in r["actions"]:
                color = GREEN if "buy" in a.get("action", "") else (RED if "sell" in a.get("action", "") else YELLOW)
                print(f"  {color}[{r['strategy']}] {a['msg']}{RESET}")


def cmd_pnl():
    from trader.strategies import get_pnl_summary
    s = get_pnl_summary()
    print(f"\n{BOLD}P&L Summary{RESET}")
    print(f"  Total trades: {s['total_trades']}")
    print(f"  Buys: {s['buys']}")
    print(f"  Sells: {s['sells']}")
    pnl = s['realized_pnl']
    color = GREEN if pnl >= 0 else RED
    print(f"  Realized P&L: {color}${pnl:+,.2f}{RESET}")
    if s.get("last_trade"):
        lt = s["last_trade"]
        print(f"  Last: {lt['action']} {lt.get('symbol','')} @ {lt['time'][:19]}")
    print()


def cmd_engine_run(interval=300):
    from trader.strategies import tick
    trader, _ = load_trader()
    print(f"{BOLD}Strategy engine running{RESET} (checking every {interval}s)")
    print(f"{DIM}Ctrl+C to stop{RESET}\n")
    try:
        while True:
            results = tick(trader)
            ts = time.strftime("%H:%M:%S")
            if results:
                for r in results:
                    for a in r["actions"]:
                        color = GREEN if "buy" in a.get("action", "") else (RED if "sell" in a.get("action", "") else YELLOW)
                        print(f"  {ts} {color}[{r['strategy']}] {a['msg']}{RESET}")
            else:
                print(f"  {ts} {DIM}no actions{RESET}")
            time.sleep(interval)
    except KeyboardInterrupt:
        print(f"\n{DIM}Engine stopped.{RESET}")


def cmd_research(session_type="midday", brain="qwen"):
    from trader.research import run_research
    trader, _ = load_trader()
    print(f"{DIM}Running {session_type} research ({brain} brain)...{RESET}\n")
    result = run_research(trader, session_type=session_type, brain_mode=brain)

    if result["mode"] == "opus":
        # Print the prompt for Claude to analyze
        print(f"{BOLD}=== RESEARCH PROMPT (for Opus) ==={RESET}")
        print(result["report"])
        print(f"{BOLD}=== END PROMPT ==={RESET}\n")
    else:
        print(f"{BOLD}=== {session_type.upper()} RESEARCH REPORT ==={RESET}")
        print(result["report"])
        print(f"{BOLD}=== END REPORT ==={RESET}\n")


def cmd_watchlist_show():
    from trader.research import load_watchlist
    wl = load_watchlist()
    if not wl:
        print(f"{DIM}Watchlist empty. Use: watchlist add AAPL \"reason\"{RESET}")
        return
    trader, _ = load_trader()
    for w in wl:
        sym = w.get("symbol", "?")
        reason = w.get("reason", "")
        try:
            q = trader.get_quote(sym)
            price = (float(q["bid"]) + float(q["ask"])) / 2 if "bid" in q else 0
            print(f"  {BOLD}{sym:5s}{RESET} ${price:>8,.2f}  {DIM}{reason}{RESET}")
        except Exception:
            print(f"  {BOLD}{sym:5s}{RESET}  {DIM}{reason}{RESET}")


def cmd_watchlist_add(symbol, reason=""):
    from trader.research import load_watchlist, save_watchlist
    wl = load_watchlist()
    # Don't duplicate
    if any(w["symbol"] == symbol.upper() for w in wl):
        print(f"{DIM}{symbol} already on watchlist{RESET}")
        return
    wl.append({"symbol": symbol.upper(), "reason": reason, "added": time.strftime("%Y-%m-%d")})
    save_watchlist(wl)
    print(f"{GREEN}Added {symbol.upper()} to watchlist{RESET}")


def cmd_watchlist_remove(symbol):
    from trader.research import load_watchlist, save_watchlist
    wl = load_watchlist()
    wl = [w for w in wl if w["symbol"] != symbol.upper()]
    save_watchlist(wl)
    print(f"{DIM}Removed {symbol.upper()}{RESET}")


def cmd_cancel_strategy(strategy_id):
    from trader.strategies import cancel_strategy
    result = cancel_strategy(strategy_id)
    if result:
        print(f"{GREEN}Cancelled {strategy_id}{RESET}")
    else:
        print(f"{RED}Strategy {strategy_id} not found.{RESET}")


def _print_order(o):
    side_color = GREEN if o.get('side') == 'buy' else RED
    print(f"  {side_color}{o.get('side','?'):>4}{RESET} {o.get('qty','?')}x {BOLD}{o.get('symbol','?')}{RESET} "
          f"({o.get('type','?')}) status={o.get('status','?')} "
          f"filled={o.get('filled_avg_price', '-')}")


# ── REPL ─────────────────────────────────────────────────────────────

def repl():
    print(f"\n{BOLD}Rickshaw Trader{RESET}")
    try:
        trader, cfg = load_trader()
        mode = "PAPER" if cfg.get("paper", True) else "LIVE"
        acct = trader.get_account()
        print(f"  {mode} | Cash: ${float(acct['cash']):,.2f} | Portfolio: ${float(acct['portfolio_value']):,.2f}")
    except SystemExit:
        print(f"{YELLOW}Run 'python -m trader setup' first{RESET}")
        return
    except Exception as e:
        print(f"{RED}Connection error: {e}{RESET}")
        return

    print(f"{DIM}Commands: buy, sell, quote, positions, orders, cancel, close, watch,{RESET}")
    print(f"{DIM}  trailing, copy, strategies, tick, run, pnl, politicians, trades, help, quit{RESET}\n")

    while True:
        try:
            line = input(f"{GREEN}trader> {RESET}").strip()
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
  buy <SYM> <QTY> [limit <P>] [stop <P>] [trail <PCT>]
  sell <SYM> <QTY> [limit <P>] [stop <P>] [trail <PCT>]
  quote <SYM> [SYM2 ...]     positions       orders [all]
  cancel [ORDER_ID]           close [SYM]     account
  watch <SYM> [SYM2 ...] [interval <SEC>]

  {BOLD}Strategies:{RESET}
  trailing <SYM> <QTY> [stop <PCT>] [trail <PCT>] [ladders <drop:qty,...>]
  copy <POLITICIAN_SLUG> [MAX_PER_TRADE]
  strategies                  list all strategies
  log <STRATEGY_ID>           show strategy log
  stop <STRATEGY_ID>          cancel a strategy
  tick                        run one check cycle
  run [INTERVAL_SEC]          run engine loop (default 300s)
  pnl                         P&L summary

  {BOLD}Research:{RESET}
  research [pre_market|midday|after_hours] [qwen|opus]
  watchlist                   show watchlist with live quotes
  wl add <SYM> [reason]       add to watchlist
  wl rm <SYM>                 remove from watchlist

  {BOLD}Data:{RESET}
  politicians                 top trading politicians
  trades                      recent politician trades
""")
            elif cmd == "account":
                cmd_account()
            elif cmd == "buy" and len(parts) >= 3:
                kwargs = _parse_order_args(parts[3:])
                cmd_buy(parts[1], parts[2], **kwargs)
            elif cmd == "sell" and len(parts) >= 3:
                kwargs = _parse_order_args(parts[3:])
                cmd_sell(parts[1], parts[2], **kwargs)
            elif cmd == "quote" and len(parts) >= 2:
                cmd_quote(parts[1:])
            elif cmd == "positions" or cmd == "pos":
                cmd_positions()
            elif cmd == "orders":
                status = parts[1] if len(parts) > 1 else "open"
                cmd_orders(status)
            elif cmd == "cancel":
                oid = parts[1] if len(parts) > 1 else None
                cmd_cancel(oid)
            elif cmd == "close":
                sym = parts[1] if len(parts) > 1 else None
                cmd_close(sym)
            elif cmd == "watch" and len(parts) >= 2:
                interval = 5
                syms = []
                i = 1
                while i < len(parts):
                    if parts[i] == "interval" and i + 1 < len(parts):
                        interval = int(parts[i + 1])
                        i += 2
                    else:
                        syms.append(parts[i])
                        i += 1
                cmd_watch(syms, interval)
            elif cmd == "trailing" and len(parts) >= 3:
                stop = 10
                trail = 5
                ladders = ""
                i = 3
                while i < len(parts):
                    if parts[i] == "stop" and i+1 < len(parts):
                        stop = parts[i+1]; i += 2
                    elif parts[i] == "trail" and i+1 < len(parts):
                        trail = parts[i+1]; i += 2
                    elif parts[i] == "ladders" and i+1 < len(parts):
                        ladders = parts[i+1]; i += 2
                    else:
                        i += 1
                cmd_trailing_stop(parts[1], parts[2], stop, trail, ladders)
            elif cmd == "copy" and len(parts) >= 2:
                max_t = parts[2] if len(parts) > 2 else 5000
                cmd_copy_trade(parts[1], max_t)
            elif cmd == "strategies" or cmd == "strats":
                cmd_strategies()
            elif cmd == "log" and len(parts) >= 2:
                cmd_strategy_log(parts[1])
            elif cmd == "tick":
                cmd_engine_tick()
            elif cmd == "run":
                interval = int(parts[1]) if len(parts) > 1 else 300
                cmd_engine_run(interval)
            elif cmd == "pnl":
                cmd_pnl()
            elif cmd == "stop" and len(parts) >= 2:
                cmd_cancel_strategy(parts[1])
            elif cmd == "research":
                session = parts[1] if len(parts) > 1 else "midday"
                brain = parts[2] if len(parts) > 2 else "qwen"
                cmd_research(session, brain)
            elif cmd == "watchlist" or cmd == "wl":
                if len(parts) >= 3 and parts[1] == "add":
                    reason = " ".join(parts[3:]) if len(parts) > 3 else ""
                    cmd_watchlist_add(parts[2], reason)
                elif len(parts) >= 3 and parts[1] in ("rm", "remove"):
                    cmd_watchlist_remove(parts[2])
                else:
                    cmd_watchlist_show()
            elif cmd == "politicians":
                cmd_politicians()
            elif cmd == "trades":
                cmd_trades()
            else:
                print(f"{DIM}Unknown command. Type 'help'{RESET}")
        except Exception as e:
            print(f"{RED}Error: {e}{RESET}")

    print(f"{DIM}Goodbye.{RESET}")


def _parse_order_args(args):
    """Parse optional order args: limit <price>, stop <price>, trail <pct>."""
    kwargs = {}
    i = 0
    while i < len(args):
        if args[i] == "limit" and i + 1 < len(args):
            kwargs["order_type"] = "limit"
            kwargs["limit_price"] = args[i + 1]
            i += 2
        elif args[i] == "stop" and i + 1 < len(args):
            kwargs["order_type"] = "stop"
            kwargs["stop_price"] = args[i + 1]
            i += 2
        elif args[i] == "trail" and i + 1 < len(args):
            kwargs["order_type"] = "trailing_stop"
            kwargs["trail_percent"] = args[i + 1]
            i += 2
        else:
            i += 1
    return kwargs


# ── Main ─────────────────────────────────────────────────────────────

def main():
    # Add parent dir to path so 'from trader import ...' works
    parent = os.path.dirname(SCRIPT_DIR)
    if parent not in sys.path:
        sys.path.insert(0, parent)

    parser = argparse.ArgumentParser(description="Rickshaw Trader")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("setup", help="Configure API keys")
    sub.add_parser("account", help="Show account info")

    buy_p = sub.add_parser("buy", help="Buy stock")
    buy_p.add_argument("symbol")
    buy_p.add_argument("qty", type=int)
    buy_p.add_argument("--type", default="market", dest="order_type")
    buy_p.add_argument("--limit", type=float, default=None)
    buy_p.add_argument("--stop", type=float, default=None)
    buy_p.add_argument("--trail", type=float, default=None)

    sell_p = sub.add_parser("sell", help="Sell stock")
    sell_p.add_argument("symbol")
    sell_p.add_argument("qty", type=int)
    sell_p.add_argument("--type", default="market", dest="order_type")
    sell_p.add_argument("--limit", type=float, default=None)
    sell_p.add_argument("--stop", type=float, default=None)
    sell_p.add_argument("--trail", type=float, default=None)

    quote_p = sub.add_parser("quote", help="Get stock quote")
    quote_p.add_argument("symbols", nargs="+")

    sub.add_parser("positions", help="Show open positions")
    sub.add_parser("orders", help="Show orders")

    cancel_p = sub.add_parser("cancel", help="Cancel order")
    cancel_p.add_argument("order_id", nargs="?", default=None)

    close_p = sub.add_parser("close", help="Close position")
    close_p.add_argument("symbol", nargs="?", default=None)

    watch_p = sub.add_parser("watch", help="Watch quotes live")
    watch_p.add_argument("symbols", nargs="+")
    watch_p.add_argument("--interval", type=int, default=5)

    sub.add_parser("politicians", help="Top trading politicians")
    sub.add_parser("trades", help="Recent politician trades")

    args = parser.parse_args()

    if args.command == "setup":
        cmd_setup()
    elif args.command == "account":
        cmd_account()
    elif args.command == "buy":
        cmd_buy(args.symbol, args.qty, args.order_type, args.limit, args.stop, args.trail)
    elif args.command == "sell":
        cmd_sell(args.symbol, args.qty, args.order_type, args.limit, args.stop, args.trail)
    elif args.command == "quote":
        cmd_quote(args.symbols)
    elif args.command == "positions":
        cmd_positions()
    elif args.command == "orders":
        cmd_orders()
    elif args.command == "cancel":
        cmd_cancel(args.order_id)
    elif args.command == "close":
        cmd_close(args.symbol)
    elif args.command == "watch":
        cmd_watch(args.symbols, args.interval)
    elif args.command == "politicians":
        cmd_politicians()
    elif args.command == "trades":
        cmd_trades()
    elif args.command is None:
        repl()


if __name__ == "__main__":
    main()
