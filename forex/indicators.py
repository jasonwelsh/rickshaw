"""Rickshaw Forex Indicators — Pure-Python technical indicators.

No external dependencies (no TA-Lib, no pandas needed for core calcs).
All functions take lists of floats and return lists of floats.
Designed to work with OANDA candle data directly.
"""
import math
from typing import List, Optional, Tuple


# ── Moving Averages ─────────────────────────────────────────────────

def sma(data: List[float], period: int) -> List[Optional[float]]:
    """Simple Moving Average."""
    result = [None] * len(data)
    for i in range(period - 1, len(data)):
        result[i] = sum(data[i - period + 1:i + 1]) / period
    return result


def ema(data: List[float], period: int) -> List[Optional[float]]:
    """Exponential Moving Average."""
    result = [None] * len(data)
    if len(data) < period:
        return result
    multiplier = 2 / (period + 1)
    # Seed with SMA
    result[period - 1] = sum(data[:period]) / period
    for i in range(period, len(data)):
        result[i] = (data[i] - result[i - 1]) * multiplier + result[i - 1]
    return result


# ── RSI ─────────────────────────────────────────────────────────────

def rsi(closes: List[float], period: int = 14) -> List[Optional[float]]:
    """Relative Strength Index."""
    result = [None] * len(closes)
    if len(closes) < period + 1:
        return result

    gains = []
    losses = []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    if avg_loss == 0:
        result[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        result[period] = 100 - (100 / (1 + rs))

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            result[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i + 1] = 100 - (100 / (1 + rs))

    return result


# ── MACD ────────────────────────────────────────────────────────────

def macd(closes: List[float], fast: int = 12, slow: int = 26, signal: int = 9
         ) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
    """MACD Line, Signal Line, Histogram."""
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)

    macd_line = [None] * len(closes)
    for i in range(len(closes)):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            macd_line[i] = ema_fast[i] - ema_slow[i]

    # Signal line = EMA of MACD
    valid_macd = [v for v in macd_line if v is not None]
    if len(valid_macd) < signal:
        return macd_line, [None] * len(closes), [None] * len(closes)

    sig = ema(valid_macd, signal)
    # Map signal back to full length
    signal_line = [None] * len(closes)
    offset = len(closes) - len(valid_macd)
    for i, v in enumerate(sig):
        if v is not None:
            signal_line[offset + i] = v

    # Histogram
    histogram = [None] * len(closes)
    for i in range(len(closes)):
        if macd_line[i] is not None and signal_line[i] is not None:
            histogram[i] = macd_line[i] - signal_line[i]

    return macd_line, signal_line, histogram


# ── Bollinger Bands ─────────────────────────────────────────────────

def bollinger_bands(closes: List[float], period: int = 20, std_dev: float = 2.0
                    ) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
    """Upper, Middle (SMA), Lower bands."""
    middle = sma(closes, period)
    upper = [None] * len(closes)
    lower = [None] * len(closes)

    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1:i + 1]
        mean = middle[i]
        variance = sum((x - mean) ** 2 for x in window) / period
        sd = math.sqrt(variance)
        upper[i] = mean + std_dev * sd
        lower[i] = mean - std_dev * sd

    return upper, middle, lower


def bollinger_pct_b(closes: List[float], period: int = 20, std_dev: float = 2.0
                    ) -> List[Optional[float]]:
    """%B — where price is relative to bands. 0=lower, 1=upper."""
    upper, _, lower = bollinger_bands(closes, period, std_dev)
    result = [None] * len(closes)
    for i in range(len(closes)):
        if upper[i] is not None and lower[i] is not None:
            band_width = upper[i] - lower[i]
            if band_width > 0:
                result[i] = (closes[i] - lower[i]) / band_width
    return result


# ── ATR ─────────────────────────────────────────────────────────────

def atr(highs: List[float], lows: List[float], closes: List[float],
        period: int = 14) -> List[Optional[float]]:
    """Average True Range."""
    result = [None] * len(closes)
    if len(closes) < 2:
        return result

    true_ranges = [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return result

    # Initial ATR = simple average
    result[period - 1] = sum(true_ranges[:period]) / period
    for i in range(period, len(true_ranges)):
        result[i] = (result[i - 1] * (period - 1) + true_ranges[i]) / period

    return result


# ── ADX ─────────────────────────────────────────────────────────────

def adx(highs: List[float], lows: List[float], closes: List[float],
        period: int = 14) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
    """ADX, +DI, -DI."""
    n = len(closes)
    adx_out = [None] * n
    pdi_out = [None] * n
    ndi_out = [None] * n

    if n < period * 2:
        return adx_out, pdi_out, ndi_out

    # Directional movement
    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    tr_list = [0.0] * n

    for i in range(1, n):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        plus_dm[i] = up_move if (up_move > down_move and up_move > 0) else 0
        minus_dm[i] = down_move if (down_move > up_move and down_move > 0) else 0
        tr_list[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )

    # Smoothed averages
    smooth_plus = sum(plus_dm[1:period + 1])
    smooth_minus = sum(minus_dm[1:period + 1])
    smooth_tr = sum(tr_list[1:period + 1])

    dx_values = []

    for i in range(period, n):
        if i == period:
            smooth_plus = sum(plus_dm[1:period + 1])
            smooth_minus = sum(minus_dm[1:period + 1])
            smooth_tr = sum(tr_list[1:period + 1])
        else:
            smooth_plus = smooth_plus - smooth_plus / period + plus_dm[i]
            smooth_minus = smooth_minus - smooth_minus / period + minus_dm[i]
            smooth_tr = smooth_tr - smooth_tr / period + tr_list[i]

        if smooth_tr > 0:
            pdi = 100 * smooth_plus / smooth_tr
            ndi = 100 * smooth_minus / smooth_tr
        else:
            pdi = 0
            ndi = 0

        pdi_out[i] = pdi
        ndi_out[i] = ndi

        if pdi + ndi > 0:
            dx = 100 * abs(pdi - ndi) / (pdi + ndi)
        else:
            dx = 0
        dx_values.append(dx)

        # ADX = smoothed DX
        if len(dx_values) >= period:
            if len(dx_values) == period:
                adx_out[i] = sum(dx_values) / period
            else:
                adx_out[i] = (adx_out[i - 1] * (period - 1) + dx) / period

    return adx_out, pdi_out, ndi_out


# ── Stochastic Oscillator ──────────────────────────────────────────

def stochastic(highs: List[float], lows: List[float], closes: List[float],
               k_period: int = 14, k_slow: int = 3, d_period: int = 3
               ) -> Tuple[List[Optional[float]], List[Optional[float]]]:
    """%K and %D lines."""
    n = len(closes)
    raw_k = [None] * n

    for i in range(k_period - 1, n):
        h = max(highs[i - k_period + 1:i + 1])
        l = min(lows[i - k_period + 1:i + 1])
        if h - l > 0:
            raw_k[i] = 100 * (closes[i] - l) / (h - l)
        else:
            raw_k[i] = 50.0

    # Slow %K = SMA of raw %K
    valid_k = [v for v in raw_k if v is not None]
    slow_k_vals = sma(valid_k, k_slow) if len(valid_k) >= k_slow else [None] * len(valid_k)

    k_out = [None] * n
    offset = n - len(valid_k)
    for i, v in enumerate(slow_k_vals):
        if v is not None:
            k_out[offset + i] = v

    # %D = SMA of slow %K
    valid_sk = [v for v in k_out if v is not None]
    d_vals = sma(valid_sk, d_period) if len(valid_sk) >= d_period else [None] * len(valid_sk)

    d_out = [None] * n
    offset2 = n - len(valid_sk)
    for i, v in enumerate(d_vals):
        if v is not None:
            d_out[offset2 + i] = v

    return k_out, d_out


# ── Donchian Channel ───────────────────────────────────────────────

def donchian(highs: List[float], lows: List[float], period: int = 20
             ) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
    """Upper (highest high), Lower (lowest low), Middle."""
    n = len(highs)
    upper = [None] * n
    lower = [None] * n
    middle = [None] * n

    for i in range(period - 1, n):
        upper[i] = max(highs[i - period + 1:i + 1])
        lower[i] = min(lows[i - period + 1:i + 1])
        middle[i] = (upper[i] + lower[i]) / 2

    return upper, lower, middle


# ── Ichimoku Cloud ──────────────────────────────────────────────────

def ichimoku(highs: List[float], lows: List[float], closes: List[float],
             tenkan: int = 9, kijun: int = 26, senkou_b: int = 52, displacement: int = 26):
    """Returns dict with: tenkan_sen, kijun_sen, senkou_a, senkou_b, chikou_span."""
    n = len(closes)

    def midpoint(h, l, period, idx):
        if idx < period - 1:
            return None
        hh = max(h[idx - period + 1:idx + 1])
        ll = min(l[idx - period + 1:idx + 1])
        return (hh + ll) / 2

    tenkan_sen = [midpoint(highs, lows, tenkan, i) for i in range(n)]
    kijun_sen = [midpoint(highs, lows, kijun, i) for i in range(n)]

    # Senkou A = (Tenkan + Kijun) / 2, displaced forward
    senkou_a = [None] * (n + displacement)
    for i in range(n):
        if tenkan_sen[i] is not None and kijun_sen[i] is not None:
            senkou_a[i + displacement] = (tenkan_sen[i] + kijun_sen[i]) / 2

    # Senkou B = midpoint of senkou_b period, displaced forward
    senkou_b_line = [None] * (n + displacement)
    for i in range(n):
        mp = midpoint(highs, lows, senkou_b, i)
        if mp is not None:
            senkou_b_line[i + displacement] = mp

    # Chikou = close displaced backward
    chikou = [None] * n
    for i in range(displacement, n):
        chikou[i - displacement] = closes[i]

    # Trim to original length for current cloud
    return {
        "tenkan_sen": tenkan_sen,
        "kijun_sen": kijun_sen,
        "senkou_a": senkou_a[:n],
        "senkou_b": senkou_b_line[:n],
        "chikou_span": chikou,
    }


# ── Fibonacci Retracement ──────────────────────────────────────────

def fibonacci_levels(swing_low: float, swing_high: float) -> dict:
    """Calculate Fibonacci retracement levels from a swing."""
    diff = swing_high - swing_low
    return {
        "0.0": swing_high,
        "23.6": swing_high - diff * 0.236,
        "38.2": swing_high - diff * 0.382,
        "50.0": swing_high - diff * 0.500,
        "61.8": swing_high - diff * 0.618,
        "78.6": swing_high - diff * 0.786,
        "100.0": swing_low,
        # Extensions
        "127.2": swing_high + diff * 0.272,
        "161.8": swing_high + diff * 0.618,
    }


def find_swings(highs: List[float], lows: List[float], lookback: int = 20
                ) -> Tuple[Optional[Tuple[int, float]], Optional[Tuple[int, float]]]:
    """Find most recent swing high and swing low."""
    n = len(highs)
    if n < lookback * 2:
        return None, None

    # Find swing high (highest high in recent lookback)
    recent_highs = highs[-lookback * 2:]
    swing_high_idx = max(range(len(recent_highs)), key=lambda i: recent_highs[i])
    swing_high_val = recent_highs[swing_high_idx]
    swing_high_idx = n - lookback * 2 + swing_high_idx

    # Find swing low (lowest low in recent lookback)
    recent_lows = lows[-lookback * 2:]
    swing_low_idx = min(range(len(recent_lows)), key=lambda i: recent_lows[i])
    swing_low_val = recent_lows[swing_low_idx]
    swing_low_idx = n - lookback * 2 + swing_low_idx

    return (swing_low_idx, swing_low_val), (swing_high_idx, swing_high_val)


# ── Pivot Points ────────────────────────────────────────────────────

def pivot_points(high: float, low: float, close: float) -> dict:
    """Standard pivot points from previous period's H, L, C."""
    p = (high + low + close) / 3
    return {
        "P": p,
        "R1": 2 * p - low,
        "R2": p + (high - low),
        "R3": high + 2 * (p - low),
        "S1": 2 * p - high,
        "S2": p - (high - low),
        "S3": low - 2 * (high - p),
    }


# ── Utility Functions ──────────────────────────────────────────────

def crossover(fast: List[Optional[float]], slow: List[Optional[float]]) -> List[int]:
    """Detect crossovers. Returns: +1 (fast crosses above slow), -1 (below), 0 (no cross)."""
    result = [0] * len(fast)
    for i in range(1, len(fast)):
        if fast[i] is None or slow[i] is None or fast[i-1] is None or slow[i-1] is None:
            continue
        if fast[i-1] <= slow[i-1] and fast[i] > slow[i]:
            result[i] = 1  # Bullish crossover
        elif fast[i-1] >= slow[i-1] and fast[i] < slow[i]:
            result[i] = -1  # Bearish crossover
    return result


def divergence(prices: List[float], indicator: List[Optional[float]],
               lookback: int = 20) -> Optional[str]:
    """Detect divergence between price and an indicator (RSI, MACD).
    Returns: 'bullish', 'bearish', or None."""
    n = len(prices)
    if n < lookback * 2:
        return None

    recent = slice(-lookback, None)
    earlier = slice(-lookback * 2, -lookback)

    # Get lows and highs for both periods
    recent_price_low = min(prices[recent])
    earlier_price_low = min(prices[earlier])
    recent_price_high = max(prices[recent])
    earlier_price_high = max(prices[earlier])

    valid_recent = [v for v in indicator[recent] if v is not None]
    valid_earlier = [v for v in indicator[earlier] if v is not None]
    if not valid_recent or not valid_earlier:
        return None

    recent_ind_low = min(valid_recent)
    earlier_ind_low = min(valid_earlier)
    recent_ind_high = max(valid_recent)
    earlier_ind_high = max(valid_earlier)

    # Bullish: price lower low, indicator higher low
    if recent_price_low < earlier_price_low and recent_ind_low > earlier_ind_low:
        return "bullish"

    # Bearish: price higher high, indicator lower high
    if recent_price_high > earlier_price_high and recent_ind_high < earlier_ind_high:
        return "bearish"

    return None


def log_return(prices: List[float], period: int = 1) -> List[Optional[float]]:
    """Log returns over period."""
    result = [None] * len(prices)
    for i in range(period, len(prices)):
        if prices[i] > 0 and prices[i - period] > 0:
            result[i] = math.log(prices[i] / prices[i - period])
    return result


def z_score(data: List[Optional[float]], lookback: int = 252) -> List[Optional[float]]:
    """Rolling z-score normalization."""
    result = [None] * len(data)
    valid = []
    for i, v in enumerate(data):
        if v is not None:
            valid.append(v)
        if len(valid) >= lookback:
            window = valid[-lookback:]
            mean = sum(window) / len(window)
            std = math.sqrt(sum((x - mean) ** 2 for x in window) / len(window))
            if std > 0:
                result[i] = (v - mean) / std
    return result
