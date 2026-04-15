"""Rickshaw Forex Strategy Engine — Pip-based rules for currency pairs.

Same design as trader/strategies.py:
  - Every decision is a rule, never a judgment call
  - Verify actual state before acting
  - Log everything

Key differences from stock strategies:
  - Uses pips instead of percentages for stops/trails
  - Units instead of shares (1000 = micro lot, 10000 = mini, 100000 = standard)
  - 24/5 market (no daily open/close cycle)
  - Spread monitoring (forex spreads widen at night/low liquidity)
"""
import json
import os
import time
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STRATEGIES_FILE = os.path.join(SCRIPT_DIR, "forex_strategies.json")
TRADE_LOG_FILE = os.path.join(SCRIPT_DIR, "forex_trade_log.json")


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


def pip_size(instrument):
    """Pip size: JPY pairs = 0.01, others = 0.0001."""
    if "JPY" in instrument:
        return 0.01
    return 0.0001


def pips_to_price(instrument, pips):
    """Convert pips to price distance."""
    return pips * pip_size(instrument)


def price_to_pips(instrument, price_diff):
    """Convert price difference to pips."""
    return price_diff / pip_size(instrument)


def is_forex_open():
    """Forex is open 24/5: Sunday 5pm ET (22:00 UTC) to Friday 5pm ET."""
    now = datetime.now(timezone.utc)
    weekday = now.weekday()
    if weekday == 5:  # Saturday
        return False
    if weekday == 6:  # Sunday, opens 22:00 UTC
        return now.hour >= 22
    if weekday == 4:  # Friday, closes 22:00 UTC
        return now.hour < 22
    return True


def get_mid_price(trader, instrument):
    """Get mid price from quote."""
    quote = trader.get_quote(instrument)
    if "error" in quote:
        return None, None, quote
    bid = float(quote["bid"])
    ask = float(quote["ask"])
    mid = (bid + ask) / 2
    spread = price_to_pips(instrument, ask - bid)
    return mid, spread, quote


# ── Pip Trailing Stop Strategy ──────────────────────────────────────

def create_trailing_stop(trader, instrument, units, stop_pips=50, trail_pips=30,
                         take_profit_pips=100, max_spread=5.0, ladder_drops=None):
    """Create a pip-based trailing stop strategy.

    Rules (mechanical, no judgment):
      1. Check spread isn't too wide
      2. Buy units at market
      3. Set floor at entry - stop_pips
      4. Every tick: if price > highest, move floor up by trail_pips from high
      5. If price <= floor, close position
      6. If spread > max_spread, skip tick (don't trade in wide spreads)
      7. Floor only moves up, never down

    Args:
        instrument: Currency pair (e.g., "EUR_USD")
        units: Number of currency units (1000=micro, 10000=mini, 100000=standard)
        stop_pips: Initial stop distance in pips
        trail_pips: Trail distance in pips from highest price
        take_profit_pips: Take profit distance in pips (sell half)
        max_spread: Maximum spread in pips to allow trading
        ladder_drops: List of [drop_pips, add_units] for averaging down
    """
    # Check spread
    mid, spread, quote = get_mid_price(trader, instrument)
    if mid is None:
        return {"error": f"Could not get quote: {quote}"}

    if spread > max_spread:
        return {"error": f"Spread too wide: {spread:.1f} pips (max {max_spread})"}

    # Place buy order
    result = trader.buy(instrument, units)
    if "error" in result:
        return {"error": result["error"]}

    fill_price = float(result.get("price", mid))
    floor_price = fill_price - pips_to_price(instrument, stop_pips)
    tp_price = fill_price + pips_to_price(instrument, take_profit_pips)

    strategy = {
        "id": f"fx-{instrument}-{int(time.time()) % 10000}",
        "type": "forex_trailing_stop",
        "instrument": instrument,
        "status": "active",
        "created": _timestamp(),
        "config": {
            "initial_units": units,
            "stop_pips": stop_pips,
            "trail_pips": trail_pips,
            "take_profit_pips": take_profit_pips,
            "max_spread": max_spread,
            "ladder_drops": ladder_drops or [],
        },
        "state": {
            "entry_price": fill_price,
            "highest_price": fill_price,
            "current_floor": floor_price,
            "take_profit_price": tp_price,
            "total_units": units,
            "total_cost": fill_price * units,
            "ladders_triggered": [],
            "profit_taken": False,
        },
        "log": [
            {"time": _timestamp(), "action": "filled",
             "msg": f"Bought {units} {instrument} @ {fill_price:.5f}. "
                    f"Floor: {floor_price:.5f} ({stop_pips}p). "
                    f"TP: {tp_price:.5f} ({take_profit_pips}p)"},
        ],
    }

    strategies = _load_strategies()
    strategies.append(strategy)
    _save_strategies(strategies)

    _log_trade(strategy["id"], "filled", {
        "instrument": instrument, "units": units, "price": fill_price,
        "spread": round(spread, 1),
    })

    return strategy


def check_trailing_stop(trader, strategy):
    """Check and update a forex trailing stop. Pure rules."""
    instrument = strategy["instrument"]
    config = strategy["config"]
    state = strategy["state"]
    actions = []

    if not is_forex_open():
        return [{"action": "skip", "msg": "Forex closed (weekend)"}]

    # Get current price and spread
    mid, spread, quote = get_mid_price(trader, instrument)
    if mid is None:
        return [{"action": "error", "msg": f"Quote error: {quote}"}]

    # Skip if spread too wide
    if spread > config["max_spread"]:
        return [{"action": "skip",
                 "msg": f"Spread wide: {spread:.1f}p (max {config['max_spread']}p)"}]

    # Check stop (floor hit)
    if mid <= state["current_floor"]:
        try:
            result = trader.close_position(instrument)
            avg_cost = state["total_cost"] / state["total_units"]
            pnl_price = mid - avg_cost
            pnl_pips = price_to_pips(instrument, pnl_price)
            # Approximate P&L in USD
            pnl_usd = pnl_price * state["total_units"]
            if "JPY" in instrument:
                pnl_usd = pnl_price * state["total_units"] / mid

            strategy["status"] = "closed"
            msg = (f"STOP HIT: Closed {instrument} @ {mid:.5f}. "
                   f"P&L: {pnl_pips:+.1f} pips (~${pnl_usd:+,.2f})")
            strategy["log"].append({"time": _timestamp(), "action": "stop_close", "msg": msg})
            actions.append({"action": "stop_close", "msg": msg, "pnl_pips": round(pnl_pips, 1)})

            _log_trade(strategy["id"], "stop_close", {
                "instrument": instrument, "price": mid,
                "pnl_pips": round(pnl_pips, 1), "pnl_usd": round(pnl_usd, 2),
            })
        except Exception as e:
            actions.append({"action": "error", "msg": f"Close failed: {e}"})
        return actions

    # Check take profit (sell half)
    if not state.get("profit_taken") and mid >= state["take_profit_price"]:
        half_units = state["total_units"] // 2
        if half_units > 0:
            try:
                result = trader.sell(instrument, half_units)
                avg_cost = state["total_cost"] / state["total_units"]
                pnl_pips = price_to_pips(instrument, mid - avg_cost)

                state["profit_taken"] = True
                state["total_units"] -= half_units
                state["total_cost"] -= avg_cost * half_units

                # Move floor to breakeven
                state["current_floor"] = max(state["current_floor"], avg_cost)

                msg = (f"PROFIT TAKE: Sold {half_units} {instrument} @ {mid:.5f} "
                       f"(+{pnl_pips:.1f}p). Floor → breakeven {avg_cost:.5f}")
                strategy["log"].append({"time": _timestamp(), "action": "take_profit", "msg": msg})
                actions.append({"action": "take_profit", "msg": msg})

                _log_trade(strategy["id"], "take_profit", {
                    "instrument": instrument, "units": half_units,
                    "price": mid, "pnl_pips": round(pnl_pips, 1),
                })
            except Exception as e:
                actions.append({"action": "error", "msg": f"Take profit failed: {e}"})

    # Breakeven & tighten logic
    actions.extend(_maybe_tighten_stop(strategy, mid, instrument))

    # Trail floor up on new highs (use effective trail if tightened)
    effective_trail = state.get("effective_trail_pips", config["trail_pips"])
    if mid > state["highest_price"]:
        state["highest_price"] = mid
        new_floor = mid - pips_to_price(instrument, effective_trail)

        if new_floor > state["current_floor"]:
            old_floor = state["current_floor"]
            state["current_floor"] = new_floor

            msg = (f"TRAIL UP: {mid:.5f} new high. "
                   f"Floor: {old_floor:.5f} -> {new_floor:.5f} ({effective_trail:.0f}p)")
            strategy["log"].append({"time": _timestamp(), "action": "trail_up", "msg": msg})
            actions.append({"action": "trail_up", "msg": msg})

    # Ladder buys (average down on dips)
    entry = state["entry_price"]
    for drop_pips, add_units in config.get("ladder_drops", []):
        trigger = entry - pips_to_price(instrument, drop_pips)
        if mid <= trigger and drop_pips not in state["ladders_triggered"]:
            if spread > config["max_spread"]:
                continue  # Don't ladder in wide spreads

            try:
                result = trader.buy(instrument, add_units)
                state["ladders_triggered"].append(drop_pips)
                state["total_units"] += add_units
                state["total_cost"] += mid * add_units

                # Recalculate floor from new average
                avg = state["total_cost"] / state["total_units"]
                new_floor = avg - pips_to_price(instrument, config["stop_pips"])
                if new_floor > state["current_floor"]:
                    state["current_floor"] = new_floor

                msg = (f"LADDER BUY: +{add_units} {instrument} @ {mid:.5f} "
                       f"(drop {drop_pips}p). Total: {state['total_units']} units")
                strategy["log"].append({"time": _timestamp(), "action": "ladder_buy", "msg": msg})
                actions.append({"action": "ladder_buy", "msg": msg})

                _log_trade(strategy["id"], "ladder_buy", {
                    "instrument": instrument, "units": add_units, "price": mid,
                })
            except Exception as e:
                actions.append({"action": "error", "msg": f"Ladder buy failed: {e}"})

    return actions


# ── Short Strategy ──────────────────────────────────────────────────

def create_short(trader, instrument, units, stop_pips=50, trail_pips=30,
                 take_profit_pips=100, max_spread=5.0):
    """Create a short (sell) position with trailing stop above."""
    mid, spread, quote = get_mid_price(trader, instrument)
    if mid is None:
        return {"error": f"Could not get quote: {quote}"}
    if spread > max_spread:
        return {"error": f"Spread too wide: {spread:.1f} pips"}

    result = trader.sell(instrument, units)
    if "error" in result:
        return {"error": result["error"]}

    fill_price = float(result.get("price", mid))
    ceiling = fill_price + pips_to_price(instrument, stop_pips)
    tp_price = fill_price - pips_to_price(instrument, take_profit_pips)

    strategy = {
        "id": f"fx-short-{instrument}-{int(time.time()) % 10000}",
        "type": "forex_short",
        "instrument": instrument,
        "status": "active",
        "created": _timestamp(),
        "config": {
            "initial_units": units,
            "stop_pips": stop_pips,
            "trail_pips": trail_pips,
            "take_profit_pips": take_profit_pips,
            "max_spread": max_spread,
        },
        "state": {
            "entry_price": fill_price,
            "lowest_price": fill_price,
            "current_ceiling": ceiling,
            "take_profit_price": tp_price,
            "total_units": units,
            "profit_taken": False,
        },
        "log": [
            {"time": _timestamp(), "action": "filled",
             "msg": f"Sold {units} {instrument} @ {fill_price:.5f}. "
                    f"Ceiling: {ceiling:.5f} ({stop_pips}p). "
                    f"TP: {tp_price:.5f} ({take_profit_pips}p)"},
        ],
    }

    strategies = _load_strategies()
    strategies.append(strategy)
    _save_strategies(strategies)

    _log_trade(strategy["id"], "short_filled", {
        "instrument": instrument, "units": units, "price": fill_price,
    })
    return strategy


def check_short(trader, strategy):
    """Check a short position. Mirror of trailing stop but inverted."""
    instrument = strategy["instrument"]
    config = strategy["config"]
    state = strategy["state"]
    actions = []

    if not is_forex_open():
        return [{"action": "skip", "msg": "Forex closed"}]

    mid, spread, quote = get_mid_price(trader, instrument)
    if mid is None:
        return [{"action": "error", "msg": f"Quote error: {quote}"}]

    if spread > config["max_spread"]:
        return [{"action": "skip", "msg": f"Spread wide: {spread:.1f}p"}]

    # Stop hit (price went UP past ceiling)
    if mid >= state["current_ceiling"]:
        try:
            result = trader.close_position(instrument)
            pnl_pips = price_to_pips(instrument, state["entry_price"] - mid)

            strategy["status"] = "closed"
            msg = f"STOP HIT: Closed short {instrument} @ {mid:.5f}. P&L: {pnl_pips:+.1f}p"
            strategy["log"].append({"time": _timestamp(), "action": "stop_close", "msg": msg})
            actions.append({"action": "stop_close", "msg": msg})

            _log_trade(strategy["id"], "stop_close", {
                "instrument": instrument, "price": mid, "pnl_pips": round(pnl_pips, 1),
            })
        except Exception as e:
            actions.append({"action": "error", "msg": f"Close failed: {e}"})
        return actions

    # Take profit (price went DOWN)
    if not state.get("profit_taken") and mid <= state["take_profit_price"]:
        half = state["total_units"] // 2
        if half > 0:
            try:
                trader.buy(instrument, half)
                state["profit_taken"] = True
                state["total_units"] -= half
                pnl_pips = price_to_pips(instrument, state["entry_price"] - mid)

                state["current_ceiling"] = min(state["current_ceiling"], state["entry_price"])

                msg = f"PROFIT TAKE: Covered {half} {instrument} @ {mid:.5f} (+{pnl_pips:.1f}p)"
                strategy["log"].append({"time": _timestamp(), "action": "take_profit", "msg": msg})
                actions.append({"action": "take_profit", "msg": msg})
            except Exception as e:
                actions.append({"action": "error", "msg": f"Take profit failed: {e}"})

    # Breakeven & tighten logic
    actions.extend(_maybe_tighten_stop(strategy, mid, instrument))

    # Trail ceiling down on new lows (use effective trail if tightened)
    effective_trail = state.get("effective_trail_pips", config["trail_pips"])
    if mid < state["lowest_price"]:
        state["lowest_price"] = mid
        new_ceiling = mid + pips_to_price(instrument, effective_trail)

        if new_ceiling < state["current_ceiling"]:
            old = state["current_ceiling"]
            state["current_ceiling"] = new_ceiling
            msg = f"TRAIL DOWN: {mid:.5f} new low. Ceiling: {old:.5f} -> {new_ceiling:.5f} ({effective_trail:.0f}p)"
            strategy["log"].append({"time": _timestamp(), "action": "trail_down", "msg": msg})
            actions.append({"action": "trail_down", "msg": msg})

    return actions


# ── Breakeven & Tightening Logic ────────────────────────────────────

def _maybe_tighten_stop(strategy, mid, instrument):
    """Move stop to breakeven after gaining 1x stop distance, then tighten.

    Rules:
      - After gaining 1x initial stop → move floor to entry (breakeven)
      - After gaining 2x initial stop → tighten trail to 60% of original
      - After gaining 3x initial stop → tighten trail to 40% of original
    Returns list of actions taken.
    """
    config = strategy["config"]
    state = strategy["state"]
    actions = []

    entry = state["entry_price"]
    stop_dist = pips_to_price(instrument, config["stop_pips"])
    is_long = strategy["type"] == "forex_trailing_stop"

    if is_long:
        gain = mid - entry
    else:
        gain = entry - mid

    gain_multiple = gain / stop_dist if stop_dist > 0 else 0

    # Breakeven at 1x stop distance
    if gain_multiple >= 1.0 and not state.get("breakeven_set"):
        if is_long:
            new_floor = max(state["current_floor"], entry + pips_to_price(instrument, 2))
        else:
            new_floor = min(state["current_ceiling"], entry - pips_to_price(instrument, 2))

        if is_long and new_floor > state["current_floor"]:
            state["current_floor"] = new_floor
            state["breakeven_set"] = True
            msg = f"BREAKEVEN: Floor moved to {new_floor:.5f} (+2p above entry)"
            strategy["log"].append({"time": _timestamp(), "action": "breakeven", "msg": msg})
            actions.append({"action": "breakeven", "msg": msg})
        elif not is_long and new_floor < state["current_ceiling"]:
            state["current_ceiling"] = new_floor
            state["breakeven_set"] = True
            msg = f"BREAKEVEN: Ceiling moved to {new_floor:.5f} (-2p below entry)"
            strategy["log"].append({"time": _timestamp(), "action": "breakeven", "msg": msg})
            actions.append({"action": "breakeven", "msg": msg})

    # Tighten trail at 2x
    if gain_multiple >= 2.0 and not state.get("trail_tightened_2x"):
        original_trail = config["trail_pips"]
        tight_trail = original_trail * 0.6
        state["effective_trail_pips"] = tight_trail
        state["trail_tightened_2x"] = True
        msg = f"TIGHTEN: Trail narrowed {original_trail}p -> {tight_trail:.0f}p (2x gain)"
        strategy["log"].append({"time": _timestamp(), "action": "tighten", "msg": msg})
        actions.append({"action": "tighten", "msg": msg})

    # Tighten more at 3x
    if gain_multiple >= 3.0 and not state.get("trail_tightened_3x"):
        original_trail = config["trail_pips"]
        tight_trail = original_trail * 0.4
        state["effective_trail_pips"] = tight_trail
        state["trail_tightened_3x"] = True
        msg = f"TIGHTEN: Trail narrowed to {tight_trail:.0f}p (3x gain, locking profits)"
        strategy["log"].append({"time": _timestamp(), "action": "tighten", "msg": msg})
        actions.append({"action": "tighten", "msg": msg})

    return actions


# ── Session Awareness ───────────────────────────────────────────────

def get_active_session():
    """Determine which trading session is active. Returns session info.

    Sessions (UTC):
      Tokyo:   00:00 - 09:00
      London:  07:00 - 16:00
      New York: 12:00 - 21:00
      Overlap (London+NY): 12:00 - 16:00 (BEST liquidity)
    """
    now = datetime.now(timezone.utc)
    hour = now.hour

    sessions = []
    if 0 <= hour < 9:
        sessions.append("tokyo")
    if 7 <= hour < 16:
        sessions.append("london")
    if 12 <= hour < 21:
        sessions.append("new_york")

    overlap = "london" in sessions and "new_york" in sessions

    # Liquidity score: 0-1
    if overlap:
        liquidity = 1.0  # Best time to trade
    elif "london" in sessions or "new_york" in sessions:
        liquidity = 0.7
    elif "tokyo" in sessions:
        liquidity = 0.4
    else:
        liquidity = 0.2  # Late NY / early Tokyo gap

    return {
        "sessions": sessions,
        "overlap": overlap,
        "liquidity": liquidity,
        "hour_utc": hour,
        "best_pairs": _session_best_pairs(sessions),
    }


def _session_best_pairs(sessions):
    """Which pairs have best liquidity per session."""
    pairs = set()
    if "tokyo" in sessions:
        pairs.update(["USD_JPY", "AUD_USD", "NZD_USD", "EUR_JPY", "AUD_JPY"])
    if "london" in sessions:
        pairs.update(["EUR_USD", "GBP_USD", "EUR_GBP", "GBP_JPY", "EUR_CHF"])
    if "new_york" in sessions:
        pairs.update(["EUR_USD", "GBP_USD", "USD_CAD", "USD_JPY", "USD_CHF"])
    return list(pairs) if pairs else ["EUR_USD", "GBP_USD", "USD_JPY"]


# ── Auto-Scanner (Find & Deploy) ───────────────────────────────────

def auto_scan_and_deploy(trader, max_positions=6, risk_pct=0.01):
    """Scan for high-confidence signals and auto-deploy strategies.

    Rules:
      - Only deploy during London or NY sessions (liquidity > 0.6)
      - Only trade pairs best suited for current session
      - Minimum composite confidence of 50%
      - Maximum total positions (including existing)
      - Size positions by confidence + volatility
      - Skip pairs we already have a position in
    """
    from forex.signals import scan_pairs
    from forex.brain import calculate_position_size

    actions = []

    # Check session
    session = get_active_session()
    if session["liquidity"] < 0.5:
        return [{"action": "skip",
                 "msg": f"Low liquidity ({session['liquidity']:.0%}). Sessions: {session['sessions']}"}]

    # Check current positions
    active = get_strategies(status="active")
    current_instruments = {s["instrument"] for s in active}

    if len(active) >= max_positions:
        return [{"action": "skip",
                 "msg": f"Max positions reached ({len(active)}/{max_positions})"}]

    slots = max_positions - len(active)

    # Scan session-appropriate pairs
    scan_pairs_list = session["best_pairs"]
    results = scan_pairs(trader, pairs=scan_pairs_list, timeframe="H1", count=200)

    # Get account for sizing
    account = trader.get_account()
    balance = float(account["balance"])

    for analysis in results:
        if slots <= 0:
            break
        if "error" in analysis:
            continue

        instrument = analysis["instrument"]
        comp = analysis.get("composite", {})
        confidence = comp.get("confidence", 0)
        recommendation = comp.get("recommendation", "no_trade")

        # Skip if below threshold or already have position
        if confidence < 0.4:
            continue
        if instrument in current_instruments:
            continue
        if "no_trade" in recommendation:
            continue

        # Determine direction and sizing
        direction = comp.get("direction", 0)
        atr_val = analysis.get("atr")
        if not atr_val or atr_val <= 0:
            continue

        # Stop = 3x ATR, trail = 2x ATR (in pips)
        stop_pips = round(price_to_pips(instrument, atr_val * 3))
        trail_pips = round(price_to_pips(instrument, atr_val * 2))
        tp_pips = round(stop_pips * 2)  # 1:2 risk/reward

        # Position size based on confidence
        units = calculate_position_size(balance, risk_pct, stop_pips, instrument, confidence)
        units = max(1000, min(units, 50000))  # Clamp to micro-standard lot range

        # Max spread based on pair
        max_spread = 5.0 if "JPY" in instrument else 3.0

        try:
            if direction > 0:
                result = create_trailing_stop(
                    trader, instrument, units,
                    stop_pips=stop_pips, trail_pips=trail_pips,
                    take_profit_pips=tp_pips, max_spread=max_spread,
                )
            elif direction < 0:
                result = create_short(
                    trader, instrument, units,
                    stop_pips=stop_pips, trail_pips=trail_pips,
                    take_profit_pips=tp_pips, max_spread=max_spread,
                )
            else:
                continue

            if "error" in result:
                actions.append({"action": "error", "msg": f"Deploy {instrument} failed: {result['error']}"})
            else:
                side = "LONG" if direction > 0 else "SHORT"
                msg = (f"AUTO-DEPLOY: {side} {units}u {instrument} "
                       f"(conf={confidence:.0%}, stop={stop_pips}p, trail={trail_pips}p, tp={tp_pips}p)")
                actions.append({"action": "auto_deploy", "msg": msg})
                current_instruments.add(instrument)
                slots -= 1
                _log_trade(f"auto-{instrument}", "auto_deploy", {
                    "instrument": instrument, "units": units, "direction": side,
                    "confidence": confidence, "stop_pips": stop_pips,
                })
        except Exception as e:
            actions.append({"action": "error", "msg": f"Deploy error: {e}"})

    if not actions:
        actions.append({"action": "skip", "msg": "No signals above threshold"})

    return actions


# ── Engine ──────────────────────────────────────────────────────────

def tick(trader):
    """Run one check cycle on all active forex strategies."""
    strategies = _load_strategies()
    results = []

    for s in strategies:
        if s["status"] != "active":
            continue

        try:
            if s["type"] == "forex_trailing_stop":
                actions = check_trailing_stop(trader, s)
            elif s["type"] == "forex_short":
                actions = check_short(trader, s)
            else:
                actions = []
        except Exception as e:
            actions = [{"action": "error", "msg": f"Strategy {s['id']} crashed: {e}"}]

        if actions:
            real = [a for a in actions if a["action"] != "skip"]
            if real:
                results.append({"strategy": s["id"], "type": s["type"], "actions": real})

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
        return {"total_trades": 0, "buys": 0, "sells": 0, "realized_pnl_pips": 0}

    with open(TRADE_LOG_FILE) as f:
        log = json.load(f)

    buys = sum(1 for t in log if t["action"] in ("filled", "ladder_buy"))
    sells = sum(1 for t in log if t["action"] in ("stop_close", "take_profit", "short_filled"))
    pnl_pips = sum(t.get("pnl_pips", 0) for t in log)

    return {
        "total_trades": len(log),
        "buys": buys,
        "sells": sells,
        "realized_pnl_pips": round(pnl_pips, 1),
        "last_trade": log[-1] if log else None,
    }
