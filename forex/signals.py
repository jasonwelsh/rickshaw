"""Rickshaw Forex Signals — Generate composite trading signals from indicators + AI.

This is the signal generation layer that sits between raw data and strategy execution.
It analyzes candle data, runs all indicators, and produces a unified signal.

Signal flow:
  OANDA candles → indicators.py → signals.py → brain.py (fusion) → strategies.py (execution)
"""
import json
import os
from datetime import datetime, timezone

from forex.indicators import (
    ema, sma, rsi, macd, bollinger_bands, bollinger_pct_b,
    atr, adx, stochastic, donchian, ichimoku,
    pivot_points, crossover, divergence, log_return,
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SIGNAL_LOG = os.path.join(SCRIPT_DIR, "signal_log.json")


def analyze_pair(trader, instrument, candles=None, timeframe="H1", count=200):
    """Full analysis of a currency pair. Returns all signals + composite.

    Args:
        trader: OandaTrader instance
        instrument: e.g. "EUR_USD"
        candles: pre-fetched candles (or None to fetch)
        timeframe: granularity for candle fetch
        count: number of candles

    Returns: dict with individual signals + composite recommendation
    """
    if candles is None:
        candles = trader.get_candles(instrument, timeframe, count)

    if not candles or len(candles) < 60:
        return {"error": "Insufficient candle data", "instrument": instrument}

    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    volumes = [c.get("volume", 0) for c in candles]

    signals = []

    # ── 1. Trend Following Signals ──────────────────────────────

    # EMA Crossover (9/21)
    sig = _ema_crossover_signal(closes)
    if sig:
        signals.append(sig)

    # EMA Trend Filter (50/200)
    sig = _ema_trend_signal(closes)
    if sig:
        signals.append(sig)

    # ADX Trend Strength
    sig = _adx_signal(highs, lows, closes)
    if sig:
        signals.append(sig)

    # Ichimoku
    sig = _ichimoku_signal(highs, lows, closes)
    if sig:
        signals.append(sig)

    # ── 2. Mean Reversion Signals ───────────────────────────────

    # Bollinger Band Bounce
    sig = _bollinger_signal(closes)
    if sig:
        signals.append(sig)

    # RSI Overbought/Oversold
    sig = _rsi_signal(closes)
    if sig:
        signals.append(sig)

    # Stochastic
    sig = _stochastic_signal(highs, lows, closes)
    if sig:
        signals.append(sig)

    # ── 3. Momentum Signals ─────────────────────────────────────

    # MACD
    sig = _macd_signal(closes)
    if sig:
        signals.append(sig)

    # MACD Divergence
    sig = _macd_divergence_signal(closes)
    if sig:
        signals.append(sig)

    # RSI Divergence
    sig = _rsi_divergence_signal(closes)
    if sig:
        signals.append(sig)

    # ── 4. Breakout Signals ─────────────────────────────────────

    # Donchian Channel
    sig = _donchian_signal(highs, lows, closes)
    if sig:
        signals.append(sig)

    # ── 5. Support/Resistance ───────────────────────────────────

    # Pivot Points
    sig = _pivot_signal(highs, lows, closes)
    if sig:
        signals.append(sig)

    # ── 6. Volatility Context ───────────────────────────────────
    atr_vals = atr(highs, lows, closes, 14)
    latest_atr = next((v for v in reversed(atr_vals) if v is not None), None)

    # ── Composite ───────────────────────────────────────────────
    from forex.brain import fuse_signals
    composite = fuse_signals(signals)

    # Get current quote
    quote = trader.get_quote(instrument)
    current_price = float(quote.get("mid", 0)) if "error" not in quote else closes[-1]
    spread = quote.get("spread_pips", 0) if "error" not in quote else 0

    result = {
        "instrument": instrument,
        "timeframe": timeframe,
        "time": datetime.now(timezone.utc).isoformat(),
        "current_price": current_price,
        "spread_pips": spread,
        "atr": round(latest_atr, 5) if latest_atr else None,
        "candle_count": len(candles),
        "signals": signals,
        "composite": composite,
    }

    # Log signal
    _log_signal(result)

    return result


def scan_pairs(trader, pairs=None, timeframe="H1", count=200):
    """Scan multiple pairs and rank by signal strength.

    Returns list of pair analyses sorted by confidence.
    """
    if pairs is None:
        pairs = ["EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD",
                 "USD_CAD", "USD_CHF", "NZD_USD", "EUR_GBP",
                 "EUR_JPY", "GBP_JPY"]

    results = []
    for pair in pairs:
        try:
            analysis = analyze_pair(trader, pair, timeframe=timeframe, count=count)
            if "error" not in analysis:
                results.append(analysis)
        except Exception as e:
            results.append({"instrument": pair, "error": str(e)})

    # Sort by composite confidence (highest first)
    results.sort(
        key=lambda x: x.get("composite", {}).get("confidence", 0),
        reverse=True,
    )

    return results


# ── Individual Signal Generators ────────────────────────────────────

def _ema_crossover_signal(closes):
    """EMA 9/21 crossover with EMA 50 filter."""
    ema9 = ema(closes, 9)
    ema21 = ema(closes, 21)
    ema50 = ema(closes, 50)

    crosses = crossover(ema9, ema21)
    latest_cross = 0
    for i in range(len(crosses) - 1, max(0, len(crosses) - 5), -1):
        if crosses[i] != 0:
            latest_cross = crosses[i]
            break

    if latest_cross == 0:
        # Check current position (no recent cross, but still above/below)
        if ema9[-1] and ema21[-1]:
            if ema9[-1] > ema21[-1]:
                latest_cross = 0.5  # Weak bullish (above but no fresh cross)
            else:
                latest_cross = -0.5
        else:
            return None

    # Filter by EMA 50
    strength = abs(latest_cross)
    if ema50[-1] is not None:
        if latest_cross > 0 and closes[-1] > ema50[-1]:
            strength = min(1.0, strength * 1.3)  # Confirmed by trend
        elif latest_cross < 0 and closes[-1] < ema50[-1]:
            strength = min(1.0, strength * 1.3)
        else:
            strength *= 0.5  # Against the larger trend

    return {
        "name": "EMA_crossover_9_21",
        "direction": 1 if latest_cross > 0 else -1,
        "strength": round(strength, 2),
        "weight": 1.5,
        "source": "trend",
        "detail": f"EMA9 {'above' if latest_cross > 0 else 'below'} EMA21",
    }


def _ema_trend_signal(closes):
    """EMA 50/200 trend direction (golden/death cross)."""
    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200)

    if ema50[-1] is None or ema200[-1] is None:
        return None

    # Check for cross in last 10 bars
    crosses = crossover(ema50, ema200)
    recent_cross = any(c != 0 for c in crosses[-10:])

    direction = 1 if ema50[-1] > ema200[-1] else -1
    strength = 0.6 if recent_cross else 0.3  # Fresh cross = stronger

    # Distance between EMAs as strength modifier
    distance_pct = abs(ema50[-1] - ema200[-1]) / ema200[-1] * 100
    strength = min(1.0, strength + distance_pct * 0.1)

    return {
        "name": "EMA_trend_50_200",
        "direction": direction,
        "strength": round(strength, 2),
        "weight": 2.0,  # Higher weight — big picture trend
        "source": "trend",
        "detail": f"{'Golden' if direction > 0 else 'Death'} cross, gap={distance_pct:.2f}%",
    }


def _adx_signal(highs, lows, closes):
    """ADX trend strength + DI crossover."""
    adx_vals, pdi, ndi = adx(highs, lows, closes, 14)

    latest_adx = next((v for v in reversed(adx_vals) if v is not None), None)
    latest_pdi = next((v for v in reversed(pdi) if v is not None), None)
    latest_ndi = next((v for v in reversed(ndi) if v is not None), None)

    if latest_adx is None or latest_pdi is None or latest_ndi is None:
        return None

    # ADX < 20 = ranging, no signal
    if latest_adx < 20:
        return {
            "name": "ADX_trend",
            "direction": 0,
            "strength": 0.1,
            "weight": 1.0,
            "source": "trend",
            "detail": f"ADX={latest_adx:.1f} (ranging, no trend)",
        }

    direction = 1 if latest_pdi > latest_ndi else -1
    strength = min(1.0, latest_adx / 50)  # ADX 50+ = max strength

    return {
        "name": "ADX_trend",
        "direction": direction,
        "strength": round(strength, 2),
        "weight": 1.5,
        "source": "trend",
        "detail": f"ADX={latest_adx:.1f} +DI={latest_pdi:.1f} -DI={latest_ndi:.1f}",
    }


def _ichimoku_signal(highs, lows, closes):
    """Ichimoku cloud signal (simplified — check price vs cloud + TK cross)."""
    ichi = ichimoku(highs, lows, closes)

    ts = ichi["tenkan_sen"][-1]
    ks = ichi["kijun_sen"][-1]
    sa = ichi["senkou_a"][-1] if len(ichi["senkou_a"]) > 0 else None
    sb = ichi["senkou_b"][-1] if len(ichi["senkou_b"]) > 0 else None
    price = closes[-1]

    if any(v is None for v in [ts, ks, sa, sb]):
        return None

    cloud_top = max(sa, sb)
    cloud_bottom = min(sa, sb)

    # Price vs cloud
    if price > cloud_top:
        price_signal = 1  # Above cloud = bullish
    elif price < cloud_bottom:
        price_signal = -1  # Below cloud = bearish
    else:
        price_signal = 0  # Inside cloud = neutral

    # TK cross
    tk_signal = 1 if ts > ks else -1

    # Combined
    if price_signal == tk_signal:
        direction = price_signal
        strength = 0.8
    elif price_signal != 0:
        direction = price_signal
        strength = 0.4
    else:
        direction = tk_signal
        strength = 0.2

    return {
        "name": "Ichimoku",
        "direction": direction,
        "strength": round(strength, 2),
        "weight": 1.5,
        "source": "trend",
        "detail": f"Price {'above' if price_signal > 0 else 'below' if price_signal < 0 else 'in'} cloud, "
                  f"TK {'bull' if tk_signal > 0 else 'bear'} cross",
    }


def _bollinger_signal(closes):
    """Bollinger Band bounce (mean reversion)."""
    pct_b = bollinger_pct_b(closes, 20, 2.0)
    latest = next((v for v in reversed(pct_b) if v is not None), None)

    if latest is None:
        return None

    if latest < 0.05:  # Near/below lower band
        direction = 1  # Oversold, expect bounce up
        strength = min(1.0, (0.1 - latest) * 5)
    elif latest > 0.95:  # Near/above upper band
        direction = -1  # Overbought, expect bounce down
        strength = min(1.0, (latest - 0.9) * 5)
    elif 0.4 < latest < 0.6:
        direction = 0
        strength = 0
    else:
        direction = 1 if latest < 0.3 else (-1 if latest > 0.7 else 0)
        strength = 0.3

    return {
        "name": "Bollinger_Band",
        "direction": direction,
        "strength": round(max(0, strength), 2),
        "weight": 1.0,
        "source": "mean_reversion",
        "detail": f"%B={latest:.2f}",
    }


def _rsi_signal(closes, period=14):
    """RSI overbought/oversold."""
    rsi_vals = rsi(closes, period)
    latest = next((v for v in reversed(rsi_vals) if v is not None), None)

    if latest is None:
        return None

    if latest < 30:
        direction = 1  # Oversold
        strength = min(1.0, (30 - latest) / 20)
    elif latest > 70:
        direction = -1  # Overbought
        strength = min(1.0, (latest - 70) / 20)
    elif latest < 40:
        direction = 1
        strength = 0.2
    elif latest > 60:
        direction = -1
        strength = 0.2
    else:
        direction = 0
        strength = 0

    return {
        "name": "RSI",
        "direction": direction,
        "strength": round(strength, 2),
        "weight": 1.0,
        "source": "mean_reversion",
        "detail": f"RSI={latest:.1f}",
    }


def _stochastic_signal(highs, lows, closes):
    """Stochastic oscillator crossover at extremes."""
    k_vals, d_vals = stochastic(highs, lows, closes, 14, 3, 3)

    latest_k = next((v for v in reversed(k_vals) if v is not None), None)
    latest_d = next((v for v in reversed(d_vals) if v is not None), None)

    if latest_k is None or latest_d is None:
        return None

    # Check for cross in oversold/overbought zones
    if latest_k < 20 and latest_k > latest_d:
        direction = 1  # Bullish cross in oversold
        strength = 0.7
    elif latest_k > 80 and latest_k < latest_d:
        direction = -1  # Bearish cross in overbought
        strength = 0.7
    elif latest_k < 30:
        direction = 1
        strength = 0.3
    elif latest_k > 70:
        direction = -1
        strength = 0.3
    else:
        direction = 0
        strength = 0

    return {
        "name": "Stochastic",
        "direction": direction,
        "strength": round(strength, 2),
        "weight": 0.8,
        "source": "mean_reversion",
        "detail": f"%K={latest_k:.1f} %D={latest_d:.1f}",
    }


def _macd_signal(closes):
    """MACD line/signal crossover."""
    macd_line, sig_line, hist = macd(closes, 12, 26, 9)

    latest_hist = next((v for v in reversed(hist) if v is not None), None)
    if latest_hist is None:
        return None

    # Check for recent crossover
    crosses = crossover(macd_line, sig_line)
    recent_cross = 0
    for i in range(len(crosses) - 1, max(0, len(crosses) - 3), -1):
        if crosses[i] != 0:
            recent_cross = crosses[i]
            break

    direction = 1 if latest_hist > 0 else -1
    strength = 0.6 if recent_cross != 0 else 0.3  # Fresh cross = stronger

    return {
        "name": "MACD",
        "direction": direction,
        "strength": round(strength, 2),
        "weight": 1.2,
        "source": "momentum",
        "detail": f"Histogram={'positive' if latest_hist > 0 else 'negative'}, "
                  f"{'fresh cross' if recent_cross else 'continuation'}",
    }


def _macd_divergence_signal(closes):
    """MACD divergence (higher TF reversal signal)."""
    _, _, hist = macd(closes, 12, 26, 9)
    div = divergence(closes, hist, lookback=20)

    if div is None:
        return None

    direction = 1 if div == "bullish" else -1

    return {
        "name": "MACD_divergence",
        "direction": direction,
        "strength": 0.7,
        "weight": 1.5,  # Divergence is a strong signal
        "source": "momentum",
        "detail": f"{div} divergence detected",
    }


def _rsi_divergence_signal(closes):
    """RSI divergence."""
    rsi_vals = rsi(closes, 14)
    div = divergence(closes, rsi_vals, lookback=20)

    if div is None:
        return None

    return {
        "name": "RSI_divergence",
        "direction": 1 if div == "bullish" else -1,
        "strength": 0.6,
        "weight": 1.3,
        "source": "momentum",
        "detail": f"{div} RSI divergence",
    }


def _donchian_signal(highs, lows, closes):
    """Donchian channel breakout (Turtle Trading)."""
    upper, lower, middle = donchian(highs, lows, 20)

    if upper[-1] is None or lower[-1] is None:
        return None

    price = closes[-1]

    if price >= upper[-1]:
        direction = 1  # Breakout above
        strength = 0.7
    elif price <= lower[-1]:
        direction = -1  # Breakout below
        strength = 0.7
    elif upper[-1] != lower[-1]:
        # Position within channel
        pct = (price - lower[-1]) / (upper[-1] - lower[-1])
        if pct > 0.9:
            direction = 1
            strength = 0.4
        elif pct < 0.1:
            direction = -1
            strength = 0.4
        else:
            direction = 0
            strength = 0
    else:
        return None

    return {
        "name": "Donchian_breakout",
        "direction": direction,
        "strength": round(strength, 2),
        "weight": 1.3,
        "source": "breakout",
        "detail": f"Price at {'upper' if direction > 0 else 'lower' if direction < 0 else 'mid'} channel",
    }


def _pivot_signal(highs, lows, closes):
    """Daily pivot point proximity."""
    if len(closes) < 2:
        return None

    # Use previous day's H/L/C (approximate — last candle)
    prev_h = max(highs[-24:]) if len(highs) >= 24 else highs[-1]
    prev_l = min(lows[-24:]) if len(lows) >= 24 else lows[-1]
    prev_c = closes[-2] if len(closes) >= 2 else closes[-1]

    pivots = pivot_points(prev_h, prev_l, prev_c)
    price = closes[-1]

    # Find nearest pivot level
    levels = sorted(pivots.items(), key=lambda x: abs(x[1] - price))
    nearest_name, nearest_price = levels[0]
    distance_pips = abs(price - nearest_price) / 0.0001  # Approximate

    if distance_pips > 30:  # Too far from any pivot
        return None

    # At support (S levels) = bullish bounce expected
    # At resistance (R levels) = bearish bounce expected
    if nearest_name.startswith("S"):
        direction = 1  # Support bounce
        strength = min(0.8, max(0.3, 1 - distance_pips / 30))
    elif nearest_name.startswith("R"):
        direction = -1  # Resistance rejection
        strength = min(0.8, max(0.3, 1 - distance_pips / 30))
    else:  # Pivot point itself
        direction = 1 if price > nearest_price else -1
        strength = 0.3

    return {
        "name": "Pivot_Points",
        "direction": direction,
        "strength": round(strength, 2),
        "weight": 0.8,
        "source": "support_resistance",
        "detail": f"Near {nearest_name}={nearest_price:.5f} ({distance_pips:.0f}p away)",
    }


# ── Signal Summary ──────────────────────────────────────────────────

def format_signal_report(analysis):
    """Format an analysis result as a readable report."""
    if "error" in analysis:
        return f"Error: {analysis['error']}"

    lines = [
        f"=== {analysis['instrument']} {analysis['timeframe']} ===",
        f"Price: {analysis['current_price']:.5f}  Spread: {analysis['spread_pips']}p  "
        f"ATR: {analysis.get('atr', 'N/A')}",
        "",
    ]

    # Group signals by source
    by_source = {}
    for sig in analysis.get("signals", []):
        src = sig.get("source", "other")
        by_source.setdefault(src, []).append(sig)

    for source, sigs in by_source.items():
        lines.append(f"  [{source.upper()}]")
        for s in sigs:
            arrow = "^" if s["direction"] > 0 else "v" if s["direction"] < 0 else "-"
            lines.append(f"    {arrow} {s['name']}: strength={s['strength']:.2f}  {s['detail']}")
        lines.append("")

    # Composite
    comp = analysis.get("composite", {})
    rec = comp.get("recommendation", "no_trade")
    conf = comp.get("confidence", 0)
    bull = comp.get("bullish", 0)
    bear = comp.get("bearish", 0)

    lines.append(f"  COMPOSITE: {rec.upper()} (confidence={conf:.0%})")
    lines.append(f"  Signals: {bull} bullish, {bear} bearish, {comp.get('neutral', 0)} neutral")

    if "ai_opinion" in comp:
        lines.append(f"  AI: {comp['ai_opinion']}")

    return "\n".join(lines)


# ── Logging ─────────────────────────────────────────────────────────

def _log_signal(analysis):
    """Log signal analysis for historical review."""
    entry = {
        "time": analysis.get("time"),
        "instrument": analysis.get("instrument"),
        "timeframe": analysis.get("timeframe"),
        "price": analysis.get("current_price"),
        "composite": analysis.get("composite", {}),
        "signal_count": len(analysis.get("signals", [])),
    }
    log = []
    if os.path.exists(SIGNAL_LOG):
        try:
            with open(SIGNAL_LOG) as f:
                log = json.load(f)
        except Exception:
            pass
    log.append(entry)
    if len(log) > 2000:
        log = log[-2000:]
    with open(SIGNAL_LOG, "w") as f:
        json.dump(log, f, indent=2)
