"""Rickshaw Trader Strategy Engine — Rule-based, dumb-AI-proof.

Design principles:
  - Every decision is a rule, never a judgment call
  - Verify actual state (positions, fills) before acting
  - Handle every edge case: partial fills, API errors, market closed, gap downs
  - Log everything so we can audit what happened and why
  - A 4B model should be able to run this without thinking

Strategies stored in strategies.json, trade history in trade_log.json.
"""
import json
import os
import time
import requests
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STRATEGIES_FILE = os.path.join(SCRIPT_DIR, "strategies.json")
TRADE_LOG_FILE = os.path.join(SCRIPT_DIR, "trade_log.json")
CONFIG_FILE = os.path.join(SCRIPT_DIR, "trader_config.json")


def _load_strategies():
    if os.path.exists(STRATEGIES_FILE):
        with open(STRATEGIES_FILE, "r") as f:
            return json.load(f)
    return []


def _save_strategies(strategies):
    with open(STRATEGIES_FILE, "w") as f:
        json.dump(strategies, f, indent=2)


def _log_trade(strategy_id, action, details):
    entry = {
        "time": _timestamp(),
        "strategy": strategy_id,
        "action": action,
        **details,
    }
    log = []
    if os.path.exists(TRADE_LOG_FILE):
        with open(TRADE_LOG_FILE, "r") as f:
            log = json.load(f)
    log.append(entry)
    if len(log) > 1000:
        log = log[-1000:]
    with open(TRADE_LOG_FILE, "w") as f:
        json.dump(log, f, indent=2)
    return entry


def _timestamp():
    return datetime.now(timezone.utc).isoformat()


def is_market_open():
    """Check if US stock market is currently open."""
    try:
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
        r = requests.get(
            "https://paper-api.alpaca.markets/v2/clock",
            headers={
                "APCA-API-KEY-ID": cfg["alpaca_api_key"],
                "APCA-API-SECRET-KEY": cfg["alpaca_secret_key"],
            },
            timeout=5,
        )
        return r.json().get("is_open", False)
    except Exception:
        return False


def get_actual_position(trader, symbol):
    """Get actual position qty from Alpaca (not our state)."""
    try:
        p = trader.get_position(symbol)
        if "error" in p:
            return 0, 0
        return int(float(p["qty"])), float(p["avg_entry"])
    except Exception:
        return 0, 0


def get_fill_price(trader, symbol):
    """Get the most recent filled order price for a symbol."""
    try:
        orders = trader.get_orders(status="all", limit=10)
        for o in orders:
            if o["symbol"] == symbol and o["status"] == "filled" and o.get("filled_avg_price"):
                return float(o["filled_avg_price"])
    except Exception:
        pass
    return None


# ── Trailing Stop Strategy ───────────────────────────────────────────

def create_trailing_stop(trader, symbol, qty, stop_pct=10, trail_pct=5,
                         ladder_drops=None):
    """Create a trailing stop strategy.

    Rules (mechanical, no judgment):
      1. Buy qty shares at market
      2. Set floor at entry - stop_pct%
      3. Every tick: if price > highest, move floor up to price - trail_pct%
      4. If price <= floor, sell everything
      5. If price drops to ladder levels below entry, buy more
      6. Floor only moves up, never down
    """
    # Check market
    if not is_market_open():
        # Place order anyway (will fill when market opens)
        pass

    result = trader.buy(symbol, qty)
    if "error" in result:
        return {"error": result["error"]}

    # Use quote for initial estimate (fill price updated on first tick)
    quote = trader.get_quote(symbol)
    est_price = (float(quote["bid"]) + float(quote["ask"])) / 2 if "bid" in quote else 0

    strategy = {
        "id": f"ts-{symbol}-{int(time.time()) % 10000}",
        "type": "trailing_stop",
        "symbol": symbol,
        "status": "pending_fill",  # Not active until we confirm the fill
        "created": _timestamp(),
        "config": {
            "initial_qty": qty,
            "stop_pct": stop_pct,
            "trail_pct": trail_pct,
            "ladder_drops": ladder_drops or [],
        },
        "state": {
            "entry_price": est_price,
            "highest_price": est_price,
            "current_floor": est_price * (1 - stop_pct / 100) if est_price else 0,
            "total_qty": qty,
            "total_cost": est_price * qty,
            "actual_qty": 0,  # Verified from Alpaca
            "ladders_triggered": [],
            "cooldown_until": None,
        },
        "log": [
            {"time": _timestamp(), "action": "order_placed",
             "msg": f"Buy order placed: {qty}x {symbol} @ ~${est_price:.2f} (pending fill)"},
        ],
        "order_id": result.get("id"),
    }

    strategies = _load_strategies()
    strategies.append(strategy)
    _save_strategies(strategies)

    _log_trade(strategy["id"], "order_placed", {
        "symbol": symbol, "qty": qty, "est_price": est_price,
    })

    return strategy


def check_trailing_stop(trader, strategy):
    """Check and update a trailing stop. Pure rules, no judgment."""
    symbol = strategy["symbol"]
    config = strategy["config"]
    state = strategy["state"]
    actions = []

    # ── Step 0: Check market hours ────────────────────────────
    if not is_market_open():
        return [{"action": "skip", "msg": "Market closed"}]

    # ── Step 1: Verify position exists ────────────────────────
    actual_qty, actual_avg = get_actual_position(trader, symbol)
    state["actual_qty"] = actual_qty

    # If pending_fill, check if our order filled
    if strategy["status"] == "pending_fill":
        if actual_qty > 0:
            # Order filled! Update entry price with real fill
            state["entry_price"] = actual_avg
            state["total_cost"] = actual_avg * actual_qty
            state["total_qty"] = actual_qty
            state["highest_price"] = actual_avg
            state["current_floor"] = actual_avg * (1 - config["stop_pct"] / 100)
            strategy["status"] = "active"
            msg = f"FILLED: {actual_qty}x {symbol} @ ${actual_avg:.2f}. Floor: ${state['current_floor']:.2f}"
            strategy["log"].append({"time": _timestamp(), "action": "filled", "msg": msg})
            actions.append({"action": "filled", "msg": msg})
            _log_trade(strategy["id"], "filled", {
                "symbol": symbol, "qty": actual_qty, "price": actual_avg,
            })
        else:
            return [{"action": "waiting", "msg": f"Waiting for {symbol} fill..."}]

    if strategy["status"] != "active":
        return actions

    # If we have no shares, something went wrong
    if actual_qty <= 0:
        strategy["status"] = "error"
        msg = f"ERROR: Expected {state['total_qty']} shares of {symbol} but have 0"
        strategy["log"].append({"time": _timestamp(), "action": "error", "msg": msg})
        return [{"action": "error", "msg": msg}]

    # ── Step 2: Get current price ─────────────────────────────
    quote = trader.get_quote(symbol)
    if "error" in quote:
        return [{"action": "error", "msg": f"Quote error: {quote['error']}"}]

    current = (float(quote["bid"]) + float(quote["ask"])) / 2
    if current <= 0:
        return [{"action": "error", "msg": "Invalid price"}]

    # ── Step 3: Check stop (floor hit) ────────────────────────
    if current <= state["current_floor"]:
        try:
            # Sell actual qty, not state qty
            sell_qty = actual_qty
            result = trader.sell(symbol, sell_qty)

            avg_cost = state["total_cost"] / state["total_qty"] if state["total_qty"] > 0 else state["entry_price"]
            pnl = (current - avg_cost) * sell_qty
            pnl_pct = (current / avg_cost - 1) * 100 if avg_cost > 0 else 0

            strategy["status"] = "closed"
            msg = (f"STOP HIT: Sold {sell_qty}x {symbol} @ ~${current:.2f}. "
                   f"P&L: ${pnl:+,.2f} ({pnl_pct:+.1f}%)")
            strategy["log"].append({"time": _timestamp(), "action": "stop_sell", "msg": msg})
            actions.append({"action": "stop_sell", "msg": msg, "pnl": round(pnl, 2)})

            _log_trade(strategy["id"], "stop_sell", {
                "symbol": symbol, "qty": sell_qty,
                "price": current, "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2),
            })
        except Exception as e:
            actions.append({"action": "error", "msg": f"Sell failed: {e}"})
        return actions

    # ── Step 4: Check for new high -> trail floor up ──────────
    if current > state["highest_price"]:
        state["highest_price"] = current
        new_floor = current * (1 - config["trail_pct"] / 100)

        if new_floor > state["current_floor"]:
            old_floor = state["current_floor"]
            state["current_floor"] = new_floor
            msg = f"TRAIL UP: ${current:.2f} new high. Floor: ${old_floor:.2f} -> ${new_floor:.2f}"
            strategy["log"].append({"time": _timestamp(), "action": "trail_up", "msg": msg})
            actions.append({"action": "trail_up", "msg": msg})

    # ── Step 5: Check ladder buys ─────────────────────────────
    entry = state["entry_price"]
    for drop_pct, buy_qty in config.get("ladder_drops", []):
        trigger_price = entry * (1 - drop_pct / 100)
        if current <= trigger_price and drop_pct not in state["ladders_triggered"]:
            try:
                result = trader.buy(symbol, buy_qty)
                state["ladders_triggered"].append(drop_pct)

                # Update totals (will be corrected on next tick from actual position)
                state["total_qty"] += buy_qty
                state["total_cost"] += current * buy_qty

                # Recalculate floor
                avg = state["total_cost"] / state["total_qty"]
                new_floor = avg * (1 - config["stop_pct"] / 100)
                if new_floor > state["current_floor"]:
                    state["current_floor"] = new_floor

                msg = (f"LADDER BUY: {buy_qty}x {symbol} @ ~${current:.2f} "
                       f"(drop {drop_pct}%). Total: {state['total_qty']} shares")
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
    if strategy["status"] != "active":
        return []

    if not is_market_open():
        return [{"action": "skip", "msg": "Market closed"}]

    from trader import capitol_trades
    config = strategy["config"]
    state = strategy["state"]
    actions = []

    trades = capitol_trades.get_politician_trades(config["politician"])

    if isinstance(trades, dict) and ("error" in trades or "raw_text" in trades):
        state["last_check"] = _timestamp()
        return [{"action": "skip", "msg": "Could not parse trades this cycle"}]

    if not isinstance(trades, list):
        return []

    for trade in trades:
        trade_key = f"{trade.get('symbol','')}-{trade.get('action','')}-{trade.get('amount','')}"
        if trade_key in state["known_trades"]:
            continue

        state["known_trades"].append(trade_key)
        symbol = trade.get("symbol", "")
        action = trade.get("action", "")
        if not symbol or not action:
            continue

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
                state["positions_opened"].append(symbol)
                state["total_invested"] += price * qty
                msg = f"COPY BUY: {qty}x {symbol} @ ~${price:.2f}"
            elif action == "sell" and config["follow_sells"]:
                result = trader.sell(symbol, qty)
                state["total_returned"] += price * qty
                msg = f"COPY SELL: {qty}x {symbol} @ ~${price:.2f}"
            else:
                continue

            strategy["log"].append({"time": _timestamp(), "action": f"copy_{action}", "msg": msg})
            actions.append({"action": f"copy_{action}", "msg": msg})
            _log_trade(strategy["id"], f"copy_{action}", {
                "symbol": symbol, "qty": qty, "price": price,
            })
        except Exception as e:
            actions.append({"action": "error", "msg": f"Copy failed: {e}"})

    state["last_check"] = _timestamp()
    if len(state["known_trades"]) > 200:
        state["known_trades"] = state["known_trades"][-100:]

    return actions


# ── Engine ───────────────────────────────────────────────────────────

def tick(trader):
    """Run one check cycle. Pure mechanical — no judgment."""
    strategies = _load_strategies()
    results = []

    for s in strategies:
        if s["status"] not in ("active", "pending_fill"):
            continue

        try:
            if s["type"] == "trailing_stop":
                actions = check_trailing_stop(trader, s)
            elif s["type"] == "copy_trade":
                actions = check_copy_strategy(trader, s)
            else:
                actions = []
        except Exception as e:
            actions = [{"action": "error", "msg": f"Strategy {s['id']} crashed: {e}"}]

        if actions:
            # Filter out "skip" actions for cleaner output
            real_actions = [a for a in actions if a["action"] != "skip"]
            if real_actions:
                results.append({"strategy": s["id"], "type": s["type"], "actions": real_actions})

    _save_strategies(strategies)
    return results


def get_strategies(status=None):
    strategies = _load_strategies()
    if status:
        return [s for s in strategies if s["status"] == status]
    return strategies


def get_strategy(strategy_id):
    for s in _load_strategies():
        if s["id"] == strategy_id:
            return s
    return None


def cancel_strategy(strategy_id):
    strategies = _load_strategies()
    for s in strategies:
        if s["id"] == strategy_id:
            s["status"] = "cancelled"
            s["log"].append({"time": _timestamp(), "action": "cancel", "msg": "Cancelled by user"})
            _save_strategies(strategies)
            return s
    return None


def get_pnl_summary():
    if not os.path.exists(TRADE_LOG_FILE):
        return {"total_trades": 0, "buys": 0, "sells": 0, "realized_pnl": 0}

    with open(TRADE_LOG_FILE) as f:
        log = json.load(f)

    buys = sum(1 for t in log if t["action"] in ("filled", "ladder_buy", "copy_buy"))
    sells = sum(1 for t in log if t["action"] in ("stop_sell", "copy_sell"))
    pnl = sum(t.get("pnl", 0) for t in log)

    return {
        "total_trades": len(log),
        "buys": buys,
        "sells": sells,
        "realized_pnl": round(pnl, 2),
        "last_trade": log[-1] if log else None,
    }
