"""Rickshaw Trader Strategy Engine — Trailing Stop, Copy Trading, Wheel.

Each strategy is a dict stored in strategies.json:
{
    "id": "ts-TSLA-001",
    "type": "trailing_stop",
    "symbol": "TSLA",
    "status": "active",
    "config": { ... },
    "state": { ... },
    "log": [ ... ]
}

The engine checks all active strategies on each tick and executes
the appropriate actions.
"""
import json
import os
import time
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STRATEGIES_FILE = os.path.join(SCRIPT_DIR, "strategies.json")
TRADE_LOG_FILE = os.path.join(SCRIPT_DIR, "trade_log.json")


def _load_strategies():
    if os.path.exists(STRATEGIES_FILE):
        with open(STRATEGIES_FILE, "r") as f:
            return json.load(f)
    return []


def _save_strategies(strategies):
    with open(STRATEGIES_FILE, "w") as f:
        json.dump(strategies, f, indent=2)


def _log_trade(strategy_id, action, details):
    """Append to the trade log."""
    entry = {
        "time": datetime.now(timezone.utc).isoformat(),
        "strategy": strategy_id,
        "action": action,
        **details,
    }
    log = []
    if os.path.exists(TRADE_LOG_FILE):
        with open(TRADE_LOG_FILE, "r") as f:
            log = json.load(f)
    log.append(entry)
    # Keep last 500 entries
    if len(log) > 500:
        log = log[-500:]
    with open(TRADE_LOG_FILE, "w") as f:
        json.dump(log, f, indent=2)
    return entry


def _timestamp():
    return datetime.now(timezone.utc).isoformat()


# ── Trailing Stop Strategy ───────────────────────────────────────────

def create_trailing_stop(trader, symbol, qty, stop_pct=10, trail_pct=5,
                         ladder_drops=None):
    """Create a trailing stop strategy.

    Args:
        symbol: Stock ticker
        qty: Shares to buy
        stop_pct: Initial stop loss % below entry (default 10%)
        trail_pct: Trail % below highest price (default 5%)
        ladder_drops: List of (drop_pct, buy_qty) for ladder buys
                      e.g. [(20, 10), (30, 20)] = buy 10 more at -20%, 20 more at -30%
    """
    # Buy initial position
    result = trader.buy(symbol, qty)
    if "error" in result:
        return {"error": result["error"]}

    # Get entry price
    quote = trader.get_quote(symbol)
    entry_price = (float(quote["bid"]) + float(quote["ask"])) / 2 if "bid" in quote else 0

    strategy = {
        "id": f"ts-{symbol}-{int(time.time()) % 10000}",
        "type": "trailing_stop",
        "symbol": symbol,
        "status": "active",
        "created": _timestamp(),
        "config": {
            "initial_qty": qty,
            "stop_pct": stop_pct,
            "trail_pct": trail_pct,
            "ladder_drops": ladder_drops or [],
        },
        "state": {
            "entry_price": entry_price,
            "highest_price": entry_price,
            "current_floor": entry_price * (1 - stop_pct / 100),
            "total_qty": qty,
            "total_cost": entry_price * qty,
            "ladders_triggered": [],
        },
        "log": [
            {"time": _timestamp(), "action": "open",
             "msg": f"Bought {qty}x {symbol} @ ~${entry_price:.2f}, floor=${entry_price * (1 - stop_pct / 100):.2f}"},
        ],
    }

    strategies = _load_strategies()
    strategies.append(strategy)
    _save_strategies(strategies)

    _log_trade(strategy["id"], "open", {
        "symbol": symbol, "qty": qty, "entry": entry_price,
        "floor": strategy["state"]["current_floor"],
    })

    return strategy


def check_trailing_stop(trader, strategy):
    """Check and update a trailing stop strategy. Returns list of actions taken."""
    if strategy["status"] != "active":
        return []

    symbol = strategy["symbol"]
    config = strategy["config"]
    state = strategy["state"]
    actions = []

    # Get current price
    quote = trader.get_quote(symbol)
    if "error" in quote:
        return [{"action": "error", "msg": quote["error"]}]

    current = (float(quote["bid"]) + float(quote["ask"])) / 2

    # Check if price hit the floor -> SELL
    if current <= state["current_floor"]:
        # Sell everything
        try:
            result = trader.sell(symbol, state["total_qty"])
            pnl = (current - state["total_cost"] / state["total_qty"]) * state["total_qty"]
            pnl_pct = (current / (state["total_cost"] / state["total_qty"]) - 1) * 100

            strategy["status"] = "closed"
            msg = f"STOP HIT: Sold {state['total_qty']}x {symbol} @ ~${current:.2f}. P&L: ${pnl:+,.2f} ({pnl_pct:+.1f}%)"
            strategy["log"].append({"time": _timestamp(), "action": "stop_sell", "msg": msg})
            actions.append({"action": "stop_sell", "msg": msg, "pnl": pnl})

            _log_trade(strategy["id"], "stop_sell", {
                "symbol": symbol, "qty": state["total_qty"],
                "price": current, "pnl": pnl, "pnl_pct": pnl_pct,
            })
        except Exception as e:
            actions.append({"action": "error", "msg": f"Sell failed: {e}"})
        return actions

    # Check if new high -> move floor up
    if current > state["highest_price"]:
        state["highest_price"] = current
        new_floor = current * (1 - config["trail_pct"] / 100)

        # Floor only moves up, never down
        if new_floor > state["current_floor"]:
            old_floor = state["current_floor"]
            state["current_floor"] = new_floor
            msg = f"New high ${current:.2f}: floor moved ${old_floor:.2f} -> ${new_floor:.2f}"
            strategy["log"].append({"time": _timestamp(), "action": "trail_up", "msg": msg})
            actions.append({"action": "trail_up", "msg": msg})

    # Check ladder buys
    entry = state["entry_price"]
    for drop_pct, buy_qty in config.get("ladder_drops", []):
        trigger_price = entry * (1 - drop_pct / 100)
        if current <= trigger_price and drop_pct not in state["ladders_triggered"]:
            try:
                result = trader.buy(symbol, buy_qty)
                state["total_qty"] += buy_qty
                state["total_cost"] += current * buy_qty
                state["ladders_triggered"].append(drop_pct)

                # Recalculate floor based on new average
                avg = state["total_cost"] / state["total_qty"]
                state["current_floor"] = max(
                    state["current_floor"],
                    avg * (1 - config["stop_pct"] / 100),
                )

                msg = f"LADDER BUY: {buy_qty}x {symbol} @ ~${current:.2f} (drop {drop_pct}%). Total: {state['total_qty']} shares"
                strategy["log"].append({"time": _timestamp(), "action": "ladder_buy", "msg": msg})
                actions.append({"action": "ladder_buy", "msg": msg})

                _log_trade(strategy["id"], "ladder_buy", {
                    "symbol": symbol, "qty": buy_qty, "price": current,
                    "total_qty": state["total_qty"],
                })
            except Exception as e:
                actions.append({"action": "error", "msg": f"Ladder buy failed: {e}"})

    return actions


# ── Copy Trading Strategy ────────────────────────────────────────────

def create_copy_strategy(trader, politician_slug, max_per_trade=5000,
                         follow_sells=True):
    """Create a copy trading strategy that follows a politician's trades."""
    strategy = {
        "id": f"cp-{politician_slug}-{int(time.time()) % 10000}",
        "type": "copy_trade",
        "symbol": "MULTI",
        "status": "active",
        "created": _timestamp(),
        "config": {
            "politician": politician_slug,
            "max_per_trade": max_per_trade,
            "follow_sells": follow_sells,
        },
        "state": {
            "last_check": None,
            "known_trades": [],
            "positions_opened": [],
            "total_invested": 0,
            "total_returned": 0,
        },
        "log": [
            {"time": _timestamp(), "action": "open",
             "msg": f"Copy trading {politician_slug}, max ${max_per_trade}/trade"},
        ],
    }

    strategies = _load_strategies()
    strategies.append(strategy)
    _save_strategies(strategies)
    return strategy


def check_copy_strategy(trader, strategy):
    """Check for new politician trades and copy them."""
    if strategy["status"] != "active":
        return []

    from trader import capitol_trades
    config = strategy["config"]
    state = strategy["state"]
    actions = []

    # Get politician's recent trades
    trades = capitol_trades.get_politician_trades(config["politician"])

    if isinstance(trades, dict) and ("error" in trades or "raw_text" in trades):
        # Can't parse structured trades — skip this check
        state["last_check"] = _timestamp()
        return [{"action": "skip", "msg": "Could not parse politician trades this cycle"}]

    if not isinstance(trades, list):
        return []

    # Find new trades we haven't seen
    for trade in trades:
        trade_key = f"{trade.get('symbol','')}-{trade.get('action','')}-{trade.get('amount','')}"
        if trade_key in state["known_trades"]:
            continue

        state["known_trades"].append(trade_key)
        symbol = trade.get("symbol", "")
        action = trade.get("action", "")
        if not symbol or not action:
            continue

        # Calculate qty based on max_per_trade
        try:
            quote = trader.get_quote(symbol)
            if "error" in quote:
                continue
            price = (float(quote["bid"]) + float(quote["ask"])) / 2
            if price <= 0:
                continue
            qty = max(1, int(config["max_per_trade"] / price))
        except Exception:
            qty = 1

        try:
            if action == "buy":
                result = trader.buy(symbol, qty)
                cost = price * qty
                state["positions_opened"].append(symbol)
                state["total_invested"] += cost
                msg = f"COPY BUY: {qty}x {symbol} @ ~${price:.2f} (following {config['politician']})"
            elif action == "sell" and config["follow_sells"]:
                result = trader.sell(symbol, qty)
                state["total_returned"] += price * qty
                msg = f"COPY SELL: {qty}x {symbol} @ ~${price:.2f} (following {config['politician']})"
            else:
                continue

            strategy["log"].append({"time": _timestamp(), "action": f"copy_{action}", "msg": msg})
            actions.append({"action": f"copy_{action}", "msg": msg})
            _log_trade(strategy["id"], f"copy_{action}", {
                "symbol": symbol, "qty": qty, "price": price,
                "politician": config["politician"],
            })
        except Exception as e:
            actions.append({"action": "error", "msg": f"Copy trade failed: {e}"})

    state["last_check"] = _timestamp()
    # Keep known_trades bounded
    if len(state["known_trades"]) > 200:
        state["known_trades"] = state["known_trades"][-100:]

    return actions


# ── Engine ───────────────────────────────────────────────────────────

def tick(trader):
    """Run one check cycle on all active strategies. Returns summary."""
    strategies = _load_strategies()
    results = []

    for s in strategies:
        if s["status"] != "active":
            continue

        if s["type"] == "trailing_stop":
            actions = check_trailing_stop(trader, s)
        elif s["type"] == "copy_trade":
            actions = check_copy_strategy(trader, s)
        else:
            actions = []

        if actions:
            results.append({"strategy": s["id"], "type": s["type"], "actions": actions})

    _save_strategies(strategies)
    return results


def get_strategies(status=None):
    """Get all strategies, optionally filtered by status."""
    strategies = _load_strategies()
    if status:
        return [s for s in strategies if s["status"] == status]
    return strategies


def get_strategy(strategy_id):
    """Get a single strategy by ID."""
    for s in _load_strategies():
        if s["id"] == strategy_id:
            return s
    return None


def cancel_strategy(strategy_id):
    """Cancel an active strategy (does NOT close positions)."""
    strategies = _load_strategies()
    for s in strategies:
        if s["id"] == strategy_id:
            s["status"] = "cancelled"
            s["log"].append({"time": _timestamp(), "action": "cancel", "msg": "Strategy cancelled by user"})
            _save_strategies(strategies)
            return s
    return None


def get_pnl_summary():
    """Summarize P&L from trade log."""
    if not os.path.exists(TRADE_LOG_FILE):
        return {"total_trades": 0, "total_pnl": 0}

    with open(TRADE_LOG_FILE) as f:
        log = json.load(f)

    buys = sum(1 for t in log if t["action"] in ("open", "ladder_buy", "copy_buy"))
    sells = sum(1 for t in log if t["action"] in ("stop_sell", "copy_sell"))
    pnl = sum(t.get("pnl", 0) for t in log)

    return {
        "total_trades": len(log),
        "buys": buys,
        "sells": sells,
        "realized_pnl": round(pnl, 2),
        "last_trade": log[-1] if log else None,
    }
