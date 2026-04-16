"""Technical indicators for stock analysis.

Feeds real data into Qwen's research prompt so it has actual
numbers to think with, not just vibes.
"""
import requests
from datetime import datetime, timedelta


def get_bars(api_key, secret_key, symbol, days=30):
    """Get daily bars from Alpaca free tier."""
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days + 5)).strftime("%Y-%m-%d")
    try:
        r = requests.get(
            f"https://data.alpaca.markets/v2/stocks/{symbol}/bars",
            headers={
                "APCA-API-KEY-ID": api_key,
                "APCA-API-SECRET-KEY": secret_key,
            },
            params={"timeframe": "1Day", "start": start, "end": end,
                    "limit": days, "feed": "iex"},
            timeout=10,
        )
        if r.ok:
            return r.json().get("bars", [])
    except Exception:
        pass
    return []


def calc_sma(closes, period):
    """Simple moving average."""
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def calc_rsi(closes, period=14):
    """Relative Strength Index."""
    if len(closes) < period + 1:
        return None
    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        if diff > 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(diff))

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def calc_volatility(closes, period=20):
    """Average daily percent change (volatility)."""
    if len(closes) < period + 1:
        return None
    changes = []
    for i in range(-period, 0):
        if closes[i - 1] != 0:
            changes.append(abs(closes[i] - closes[i - 1]) / closes[i - 1] * 100)
    return round(sum(changes) / len(changes), 2) if changes else None


def calc_avg_volume(bars, period=20):
    """Average daily volume."""
    if len(bars) < period:
        return None
    vols = [b["v"] for b in bars[-period:]]
    return int(sum(vols) / len(vols))


def analyze_stock(api_key, secret_key, symbol):
    """Full technical analysis for one stock. Returns dict."""
    bars = get_bars(api_key, secret_key, symbol, days=30)
    if not bars or len(bars) < 5:
        return {"symbol": symbol, "error": "insufficient data"}

    closes = [b["c"] for b in bars]
    current = closes[-1]

    sma5 = calc_sma(closes, 5)
    sma20 = calc_sma(closes, 20)
    rsi = calc_rsi(closes)
    vol = calc_volatility(closes)
    avg_vol = calc_avg_volume(bars)

    # Price change
    change_1d = round((closes[-1] / closes[-2] - 1) * 100, 2) if len(closes) >= 2 else 0
    change_5d = round((closes[-1] / closes[-5] - 1) * 100, 2) if len(closes) >= 5 else 0
    change_20d = round((closes[-1] / closes[0] - 1) * 100, 2) if len(closes) >= 20 else None

    # Trend signals
    above_sma5 = current > sma5 if sma5 else None
    above_sma20 = current > sma20 if sma20 else None

    # Volume trend
    recent_vol = bars[-1]["v"] if bars else 0
    vol_ratio = round(recent_vol / avg_vol, 2) if avg_vol and avg_vol > 0 else None

    return {
        "symbol": symbol,
        "price": current,
        "change_1d": change_1d,
        "change_5d": change_5d,
        "change_20d": change_20d,
        "sma5": round(sma5, 2) if sma5 else None,
        "sma20": round(sma20, 2) if sma20 else None,
        "above_sma5": above_sma5,
        "above_sma20": above_sma20,
        "rsi": rsi,
        "volatility": vol,
        "avg_volume": avg_vol,
        "vol_ratio": vol_ratio,
    }


def analyze_batch(api_key, secret_key, symbols):
    """Analyze multiple stocks. Returns list of dicts."""
    results = []
    for sym in symbols:
        try:
            r = analyze_stock(api_key, secret_key, sym)
            results.append(r)
        except Exception:
            results.append({"symbol": sym, "error": "failed"})
    return results


def format_for_prompt(analyses):
    """Format technical data into a readable block for Qwen."""
    lines = []
    lines.append(f"{'SYM':>5} {'PRICE':>7} {'1D%':>6} {'5D%':>6} {'20D%':>6} {'RSI':>5} {'VOL%':>5} {'>SMA5':>6} {'>SMA20':>7} {'VRAT':>5}")
    lines.append(f"  {'-'*70}")

    for a in analyses:
        if "error" in a:
            lines.append(f"  {a['symbol']:>5} -- insufficient data --")
            continue

        sma5 = "YES" if a.get("above_sma5") else ("NO" if a.get("above_sma5") is not None else "?")
        sma20 = "YES" if a.get("above_sma20") else ("NO" if a.get("above_sma20") is not None else "?")
        rsi = f"{a['rsi']}" if a.get("rsi") else "?"
        vol = f"{a['volatility']}" if a.get("volatility") else "?"
        vrat = f"{a['vol_ratio']}" if a.get("vol_ratio") else "?"
        d20 = f"{a['change_20d']:+.1f}" if a.get("change_20d") is not None else "?"

        lines.append(
            f"  {a['symbol']:>5} ${a['price']:>6.2f} {a['change_1d']:>+5.1f}% {a['change_5d']:>+5.1f}% "
            f"{d20:>5}% {rsi:>5} {vol:>5} {sma5:>6} {sma20:>7} {vrat:>5}"
        )

    # Legend
    lines.append("")
    lines.append("  RSI: <30 oversold (buy signal), >70 overbought (sell signal)")
    lines.append("  >SMA5/20: price above 5/20 day moving average = uptrend")
    lines.append("  VRAT: volume ratio vs 20d avg (>1.5 = unusual activity)")
    lines.append("  VOL%: avg daily % change (higher = more volatile)")

    return "\n".join(lines)
