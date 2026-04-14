"""Rickshaw Trader Screener — Mechanical stock selection. No judgment.

Scans a universe of stocks, scores them on pure data rules,
and outputs ranked picks ready for the engine.

Scoring rules (all mechanical):
  1. Momentum:  current price vs 5-day and 20-day moving average
  2. Spread:    tighter spread = more liquid = safer to trade
  3. Price:     $20-$1000 range (no penny stocks, no BRK.A)
  4. Sector:    penalize if we already hold that sector
  5. Congress:  bonus if politicians are buying it

Each rule outputs a 0-100 score. Weighted average = final score.
Top N picks get deployed as trailing stop strategies.
"""
import json
import os
import sys
import time
import requests
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(SCRIPT_DIR))

SCREENER_LOG = os.path.join(SCRIPT_DIR, "screener_log.json")

# ── Universe ─────────────────────────────────────────────────────────
# Broad set across sectors. Not hand-picked — just the most liquid
# stocks in each sector that Alpaca supports.

UNIVERSE = {
    "Tech":       ["AAPL", "MSFT", "NVDA", "GOOG", "META", "AMZN", "CRM", "ORCL", "ADBE", "INTC"],
    "Finance":    ["JPM", "BAC", "GS", "V", "MA", "WFC", "C", "AXP", "BLK", "SCHW"],
    "Energy":     ["XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PSX", "VLO", "OXY", "HAL"],
    "Healthcare": ["UNH", "JNJ", "LLY", "PFE", "ABBV", "MRK", "TMO", "ABT", "BMY", "AMGN"],
    "Industrial": ["CAT", "DE", "BA", "HON", "GE", "UPS", "RTX", "LMT", "MMM", "FDX"],
    "Consumer":   ["WMT", "COST", "HD", "MCD", "NKE", "SBUX", "TGT", "LOW", "TJX", "DG"],
}

ALL_SYMBOLS = []
SYMBOL_SECTOR = {}
for sector, symbols in UNIVERSE.items():
    for s in symbols:
        ALL_SYMBOLS.append(s)
        SYMBOL_SECTOR[s] = sector

# ── Scoring Weights ──────────────────────────────────────────────────

WEIGHTS = {
    "momentum_5d": 30,    # Short-term trend
    "momentum_20d": 25,   # Medium-term trend
    "spread": 15,         # Liquidity
    "price_range": 10,    # In tradeable range
    "sector_balance": 15, # Don't overload sectors
    "congress": 5,        # Politician signal (bonus)
}


# ── Data Collection ──────────────────────────────────────────────────

def get_quotes_batch(trader, symbols):
    """Get quotes for all symbols. Returns {symbol: {bid, ask, mid}}."""
    quotes = {}
    for sym in symbols:
        try:
            q = trader.get_quote(sym)
            if "bid" in q:
                bid = float(q["bid"])
                ask = float(q["ask"])
                mid = (bid + ask) / 2
                spread = (ask - bid) / mid * 100 if mid > 0 else 99
                quotes[sym] = {"bid": bid, "ask": ask, "mid": mid, "spread": spread}
        except Exception:
            pass
    return quotes


def get_historical_bars(api_key, secret_key, symbol, days=20):
    """Get recent daily bars from Alpaca for moving averages."""
    try:
        from datetime import timedelta
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=days + 5)).strftime("%Y-%m-%d")
        r = requests.get(
            f"https://data.alpaca.markets/v2/stocks/{symbol}/bars",
            headers={
                "APCA-API-KEY-ID": api_key,
                "APCA-API-SECRET-KEY": secret_key,
            },
            params={"timeframe": "1Day", "start": start, "end": end, "limit": days},
            timeout=10,
        )
        if r.ok:
            bars = r.json().get("bars", [])
            closes = [b["c"] for b in bars]
            return closes
    except Exception:
        pass
    return []


def get_current_holdings(trader):
    """Get currently held symbols and their sectors."""
    positions = trader.get_positions()
    held = {}
    for p in positions:
        sym = p["symbol"]
        held[sym] = SYMBOL_SECTOR.get(sym, "Unknown")
    return held


# ── Scoring Functions ────────────────────────────────────────────────

def score_momentum(closes, current_price):
    """Score based on price vs moving averages. Higher = stronger uptrend."""
    if not closes or current_price <= 0:
        return 50, 50  # neutral

    # 5-day MA
    ma5 = sum(closes[-5:]) / min(5, len(closes)) if len(closes) >= 5 else current_price
    pct_above_5 = (current_price / ma5 - 1) * 100

    # 20-day MA
    ma20 = sum(closes) / len(closes) if closes else current_price
    pct_above_20 = (current_price / ma20 - 1) * 100

    # Convert to 0-100 score
    # +5% above MA = score 100, -5% below = score 0, at MA = 50
    score_5d = max(0, min(100, 50 + pct_above_5 * 10))
    score_20d = max(0, min(100, 50 + pct_above_20 * 5))

    return round(score_5d), round(score_20d)


def score_spread(spread_pct):
    """Score based on bid-ask spread. Tighter = better."""
    # 0% spread = 100, 5% spread = 0
    return max(0, min(100, round(100 - spread_pct * 20)))


def score_price_range(price):
    """Score based on whether price is in tradeable range."""
    if price < 20 or price > 1000:
        return 0
    if 50 <= price <= 500:
        return 100
    if 20 <= price < 50:
        return 60
    if 500 < price <= 1000:
        return 70
    return 50


def score_sector_balance(symbol, held_sectors):
    """Penalize if we already have too many in this sector."""
    sector = SYMBOL_SECTOR.get(symbol, "Unknown")
    count = sum(1 for s in held_sectors.values() if s == sector)
    if count == 0:
        return 100  # Fresh sector — great
    if count == 1:
        return 60   # One already — okay
    if count == 2:
        return 20   # Two already — crowded
    return 0        # Three+ — avoid


def score_congress(symbol, congress_buys):
    """Bonus if politicians are buying this stock."""
    if symbol in congress_buys:
        return 100
    return 50  # Neutral


# ── Main Screener ────────────────────────────────────────────────────

def run_screen(trader, api_key, secret_key, top_n=5, exclude_held=True):
    """Screen the universe and return top N picks with scores.

    Returns: [{"symbol", "sector", "score", "scores", "price"}, ...]
    """
    held = get_current_holdings(trader)
    held_sectors = held

    # Get all quotes
    quotes = get_quotes_batch(trader, ALL_SYMBOLS)

    # Get congress signals (best effort)
    congress_buys = set()
    try:
        from trader import capitol_trades
        trades = capitol_trades.get_recent_trades()
        if isinstance(trades, list):
            congress_buys = {t.get("symbol", "") for t in trades if t.get("action") == "buy"}
    except Exception:
        pass

    results = []

    for sym in ALL_SYMBOLS:
        # Skip if already held
        if exclude_held and sym in held:
            continue

        q = quotes.get(sym)
        if not q:
            continue

        price = q["mid"]
        spread = q["spread"]

        # Get historical bars for momentum
        closes = get_historical_bars(api_key, secret_key, sym, days=20)

        # Score each dimension
        m5, m20 = score_momentum(closes, price)
        s_spread = score_spread(spread)
        s_price = score_price_range(price)
        s_sector = score_sector_balance(sym, held_sectors)
        s_congress = score_congress(sym, congress_buys)

        scores = {
            "momentum_5d": m5,
            "momentum_20d": m20,
            "spread": s_spread,
            "price_range": s_price,
            "sector_balance": s_sector,
            "congress": s_congress,
        }

        # Weighted average
        total = sum(scores[k] * WEIGHTS[k] for k in WEIGHTS) / sum(WEIGHTS.values())

        results.append({
            "symbol": sym,
            "sector": SYMBOL_SECTOR.get(sym, "?"),
            "price": round(price, 2),
            "score": round(total, 1),
            "scores": scores,
        })

    # Sort by score descending
    results.sort(key=lambda x: x["score"], reverse=True)

    # Log
    log_entry = {
        "time": datetime.now().isoformat(),
        "held": list(held.keys()),
        "top_picks": results[:top_n],
        "universe_size": len(ALL_SYMBOLS),
        "quoted": len(quotes),
    }
    log = []
    if os.path.exists(SCREENER_LOG):
        with open(SCREENER_LOG) as f:
            log = json.load(f)
    log.append(log_entry)
    if len(log) > 30:
        log = log[-30:]
    with open(SCREENER_LOG, "w") as f:
        json.dump(log, f, indent=2)

    return results[:top_n]


def auto_deploy(trader, api_key, secret_key, max_positions=8, shares_per=5,
                stop_pct=10, trail_pct=5):
    """Full auto: screen -> pick -> deploy trailing stops.

    Rules (mechanical):
      1. Screen the universe
      2. Take top picks that aren't already held
      3. Deploy trailing stop for each
      4. Don't exceed max_positions total
    """
    from trader.strategies import create_trailing_stop, get_strategies

    current = get_strategies(status="active") + get_strategies(status="pending_fill")
    slots = max_positions - len(current)

    if slots <= 0:
        return {"status": "full", "msg": f"Already at {len(current)}/{max_positions} positions"}

    picks = run_screen(trader, api_key, secret_key, top_n=slots)
    deployed = []

    for pick in picks:
        sym = pick["symbol"]
        price = pick["price"]

        # Adjust qty based on price to keep position sizes roughly equal
        target_size = 1500  # ~$1500 per position
        qty = max(1, int(target_size / price))

        # Ladder drops scale with score — higher score = more aggressive ladders
        ladders = [(20, max(1, qty // 2)), (30, qty)]

        result = create_trailing_stop(
            trader, sym, qty,
            stop_pct=stop_pct, trail_pct=trail_pct,
            ladder_drops=ladders,
        )

        if "error" not in result:
            deployed.append({
                "symbol": sym,
                "qty": qty,
                "score": pick["score"],
                "sector": pick["sector"],
                "strategy_id": result["id"],
            })

    return {
        "status": "deployed",
        "picks": deployed,
        "slots_used": len(deployed),
        "slots_remaining": slots - len(deployed),
    }
