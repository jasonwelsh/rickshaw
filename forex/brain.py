"""Rickshaw Forex Brain — AI-powered analysis layer.

Three modes:
  auto:   Mechanical rules only, no AI involvement (safest)
  qwen:   Local Qwen 3.5 via Ollama (free, fast, good for structured extraction)
  opus:   Claude via API (smarter, costs credits, best for nuanced analysis)

AI adds value in forex through:
  1. Central bank sentiment scoring (hawkish/dovish)
  2. News event impact assessment
  3. Economic data interpretation
  4. Signal fusion (weighting multiple strategy signals)
  5. Regime detection (trending vs ranging market)
"""
import json
import os
import re
import requests
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BRAIN_CONFIG = os.path.join(SCRIPT_DIR, "forex_brain_config.json")
ANALYSIS_LOG = os.path.join(SCRIPT_DIR, "forex_analysis_log.json")


def get_brain_mode():
    if os.path.exists(BRAIN_CONFIG):
        with open(BRAIN_CONFIG) as f:
            return json.load(f).get("mode", "auto")
    return "auto"


def set_brain_mode(mode):
    if mode not in ("auto", "opus", "qwen"):
        return {"error": f"Invalid mode: {mode}. Use auto, opus, or qwen."}
    cfg = {}
    if os.path.exists(BRAIN_CONFIG):
        with open(BRAIN_CONFIG) as f:
            cfg = json.load(f)
    cfg["mode"] = mode
    with open(BRAIN_CONFIG, "w") as f:
        json.dump(cfg, f, indent=2)
    return {"mode": mode}


# ── Core AI Functions ───────────────────────────────────────────────

def ask_brain(question, context="", mode=None):
    """Ask the current brain a question."""
    mode = mode or get_brain_mode()

    if mode == "auto":
        return {"answer": "Auto mode — mechanical rules only.", "mode": "auto"}
    if mode == "qwen":
        return _ask_qwen(question, context)
    if mode == "opus":
        return _ask_claude(question, context)
    return {"error": f"Unknown mode: {mode}"}


def _ask_qwen(question, context=""):
    """Ask Qwen 3.5 via Ollama native API (thinking disabled for speed)."""
    try:
        system = (
            "You are a forex market analyst. You make data-driven assessments only. "
            "Never guess. If data is insufficient, say so. "
            "Keep responses under 150 words. Use numbers and specifics."
        )
        prompt = question
        if context:
            prompt = f"Context:\n{context}\n\nQuestion:\n{question}"

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]

        resp = requests.post(
            "http://localhost:11434/api/chat",
            json={
                "model": "qwen3.5:4b",
                "messages": messages,
                "stream": False,
                "think": False,
                "options": {"num_predict": 400, "temperature": 0.3},
            },
            timeout=120,
        )
        resp.raise_for_status()
        content = resp.json().get("message", {}).get("content", "")
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        return {"answer": content, "mode": "qwen"}
    except Exception as e:
        return {"error": str(e), "mode": "qwen"}


def _load_claude_token():
    """Load OAuth token from Claude Code credentials."""
    creds_file = os.path.join(os.path.expanduser("~"), ".claude", ".credentials.json")
    if not os.path.exists(creds_file):
        return None
    try:
        with open(creds_file) as f:
            creds = json.load(f)
        return creds.get("claudeAiOauth", {}).get("accessToken")
    except Exception:
        return None


def _ask_claude(question, context=""):
    """Ask Claude via Max subscription OAuth token."""
    # Try env var first, then Claude Code OAuth
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    auth_token = None

    if not api_key:
        auth_token = _load_claude_token()
        if not auth_token:
            # Fallback to Qwen
            return _ask_qwen(question, context)

    headers = {
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    else:
        headers["x-api-key"] = api_key

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1024,
                "system": (
                    "You are a forex market analyst. Provide data-driven assessments. "
                    "Score sentiment on a -1.0 to +1.0 scale. Be specific with numbers. "
                    "Always return valid JSON when asked for structured output."
                ),
                "messages": [
                    {"role": "user", "content": f"Context:\n{context}\n\nQuestion:\n{question}"}
                ],
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["content"][0]["text"]
        return {"answer": content, "mode": "opus"}
    except Exception as e:
        # Fallback to Qwen on any failure
        return _ask_qwen(question, context)


# ── Sentiment Analysis ──────────────────────────────────────────────

def score_sentiment(text, source="news", mode=None):
    """Score text on hawkish/dovish or bullish/bearish scale.

    Returns: {score: -1.0 to 1.0, confidence: 0-1, key_phrases: [...], bias: str}
    """
    mode = mode or get_brain_mode()
    if mode == "auto":
        return {"score": 0, "confidence": 0, "bias": "neutral", "mode": "auto"}

    prompt = f"""Analyze this {source} text for forex market sentiment.

Return JSON only (no markdown):
{{
  "score": <float -1.0 (very dovish/bearish) to 1.0 (very hawkish/bullish)>,
  "confidence": <float 0.0 to 1.0>,
  "bias": "<dovish|neutral|hawkish>" or "<bearish|neutral|bullish>",
  "key_phrases": ["phrase1", "phrase2"],
  "currencies_affected": ["USD", "EUR"],
  "direction_implied": {{"USD": "up/down/neutral", "EUR": "up/down/neutral"}},
  "summary": "<one sentence>"
}}

Text to analyze:
{text[:3000]}"""

    result = ask_brain(prompt, mode=mode)
    if "error" in result:
        return {"score": 0, "confidence": 0, "bias": "neutral", "error": result["error"]}

    try:
        # Extract JSON from response
        answer = result["answer"]
        json_match = re.search(r'\{.*\}', answer, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group())
            parsed["mode"] = mode
            return parsed
    except (json.JSONDecodeError, AttributeError):
        pass

    return {"score": 0, "confidence": 0, "bias": "neutral",
            "raw_answer": result.get("answer", ""), "mode": mode}


def analyze_central_bank(text, bank="fed", mode=None):
    """Specialized analysis for central bank communications."""
    mode = mode or get_brain_mode()
    if mode == "auto":
        return {"score": 0, "mode": "auto"}

    prompt = f"""Analyze this {bank.upper()} communication for monetary policy signals.

Return JSON only (no markdown):
{{
  "hawkish_dovish_score": <float -1.0 (very dovish) to 1.0 (very hawkish)>,
  "rate_direction": "<hike|hold|cut>",
  "confidence": <float 0.0 to 1.0>,
  "key_signals": ["signal1", "signal2"],
  "tone_shift": "<more_hawkish|unchanged|more_dovish> vs previous meeting",
  "currency_impact": {{"currency": "USD/EUR/JPY/GBP", "direction": "strengthen/weaken/neutral"}},
  "timeframe": "<immediate|weeks|months>",
  "summary": "<one sentence>"
}}

{bank.upper()} text:
{text[:4000]}"""

    result = ask_brain(prompt, mode=mode)
    if "error" in result:
        return {"score": 0, "error": result["error"]}

    try:
        answer = result["answer"]
        json_match = re.search(r'\{.*\}', answer, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group())
            parsed["mode"] = mode
            return parsed
    except (json.JSONDecodeError, AttributeError):
        pass

    return {"score": 0, "raw_answer": result.get("answer", ""), "mode": mode}


# ── Market Regime Detection ─────────────────────────────────────────

def detect_regime(candles, mode=None):
    """Detect current market regime: trending, ranging, or volatile.

    Uses AI to interpret technical data and provide regime classification.
    Falls back to rule-based detection in auto mode.
    """
    if not candles or len(candles) < 20:
        return {"regime": "unknown", "confidence": 0}

    # Calculate basic stats for rule-based fallback
    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]

    # Simple rule-based regime detection (always available)
    from forex.indicators import atr, ema, adx as calc_adx

    atr_vals = atr(highs, lows, closes, 14)
    ema_20 = ema(closes, 20)
    ema_50 = ema(closes, 50)
    adx_vals, pdi, ndi = calc_adx(highs, lows, closes, 14)

    # Get latest valid values
    latest_atr = next((v for v in reversed(atr_vals) if v is not None), None)
    latest_adx = next((v for v in reversed(adx_vals) if v is not None), None)
    latest_ema20 = next((v for v in reversed(ema_20) if v is not None), None)
    latest_ema50 = next((v for v in reversed(ema_50) if v is not None), None)

    # Rule-based classification
    regime = "ranging"
    confidence = 0.5

    if latest_adx is not None:
        if latest_adx > 30:
            regime = "trending"
            confidence = min(0.9, latest_adx / 50)
        elif latest_adx < 20:
            regime = "ranging"
            confidence = min(0.9, (20 - latest_adx) / 20)

    # Determine trend direction
    trend_direction = "neutral"
    if latest_ema20 is not None and latest_ema50 is not None:
        if latest_ema20 > latest_ema50:
            trend_direction = "bullish"
        elif latest_ema20 < latest_ema50:
            trend_direction = "bearish"

    # Volatility assessment
    volatility = "normal"
    if latest_atr is not None and len(closes) > 60:
        # Compare ATR to its 60-period average
        atr_window = [v for v in atr_vals[-60:] if v is not None]
        if atr_window:
            avg_atr = sum(atr_window) / len(atr_window)
            if latest_atr > avg_atr * 1.5:
                volatility = "high"
                regime = "volatile"
            elif latest_atr < avg_atr * 0.5:
                volatility = "low"

    result = {
        "regime": regime,
        "trend_direction": trend_direction,
        "volatility": volatility,
        "adx": round(latest_adx, 1) if latest_adx else None,
        "atr": round(latest_atr, 5) if latest_atr else None,
        "confidence": round(confidence, 2),
    }

    mode = mode or get_brain_mode()
    if mode != "auto":
        # Enhance with AI interpretation
        context = json.dumps(result)
        price_range = f"{min(lows[-20:]):.5f} - {max(highs[-20:]):.5f}"
        ai_result = ask_brain(
            f"Given these market stats, what regime is this? "
            f"Price range last 20 bars: {price_range}. "
            f"Current price: {closes[-1]:.5f}. "
            f"Should we use trend-following or mean-reversion strategies? "
            f"Answer in 2 sentences max.",
            context=context, mode=mode,
        )
        if "answer" in ai_result:
            result["ai_assessment"] = ai_result["answer"]

    return result


# ── Signal Fusion ───────────────────────────────────────────────────

def fuse_signals(signals, mode=None):
    """Combine multiple trading signals into a composite recommendation.

    Args:
        signals: list of dicts with {name, direction (+1/-1/0), strength (0-1), source}

    Returns: {direction: +1/-1/0, confidence: 0-1, recommendation: str, reasoning: str}
    """
    if not signals:
        return {"direction": 0, "confidence": 0, "recommendation": "no_trade"}

    # Rule-based fusion (always runs)
    directions = [s["direction"] for s in signals if s["direction"] != 0]
    if not directions:
        return {"direction": 0, "confidence": 0, "recommendation": "no_trade"}

    # Agreement score
    avg_direction = sum(directions) / len(directions)
    agreement = abs(avg_direction)

    # Weighted strength
    total_weight = sum(s.get("weight", 1) for s in signals)
    weighted_dir = sum(s["direction"] * s["strength"] * s.get("weight", 1) for s in signals)
    weighted_dir /= total_weight if total_weight > 0 else 1

    # Composite
    direction = 1 if weighted_dir > 0.1 else (-1 if weighted_dir < -0.1 else 0)
    confidence = min(1.0, abs(weighted_dir) * agreement)

    # Recommendation thresholds
    if confidence >= 0.7:
        rec = "strong_buy" if direction > 0 else "strong_sell"
    elif confidence >= 0.4:
        rec = "buy" if direction > 0 else "sell"
    elif confidence >= 0.2:
        rec = "lean_buy" if direction > 0 else "lean_sell"
    else:
        rec = "no_trade"

    result = {
        "direction": direction,
        "confidence": round(confidence, 3),
        "recommendation": rec,
        "agreement": round(agreement, 3),
        "signal_count": len(signals),
        "bullish": sum(1 for s in signals if s["direction"] > 0),
        "bearish": sum(1 for s in signals if s["direction"] < 0),
        "neutral": sum(1 for s in signals if s["direction"] == 0),
    }

    # AI enhancement
    mode = mode or get_brain_mode()
    if mode != "auto" and confidence > 0.3:
        signal_summary = "\n".join(
            f"  {s['name']}: {'BUY' if s['direction'] > 0 else 'SELL' if s['direction'] < 0 else 'NEUTRAL'} "
            f"(strength={s['strength']:.2f})"
            for s in signals
        )
        ai_result = ask_brain(
            f"These signals are generated for a forex trade. "
            f"Composite direction: {'BUY' if direction > 0 else 'SELL'}. "
            f"Confidence: {confidence:.0%}. "
            f"Do you agree? Any concerns? One sentence.",
            context=signal_summary, mode=mode,
        )
        if "answer" in ai_result:
            result["ai_opinion"] = ai_result["answer"]

    return result


# ── Position Sizing ─────────────────────────────────────────────────

def calculate_position_size(account_balance, risk_pct, stop_pips, instrument,
                           confidence=1.0):
    """Kelly-influenced position sizing based on confidence.

    Args:
        account_balance: Total account value in USD
        risk_pct: Base risk per trade (e.g., 0.01 for 1%)
        stop_pips: Stop loss distance in pips
        instrument: Currency pair (for pip value calculation)
        confidence: 0-1 from signal fusion (scales position)
    """
    # Adjust risk by confidence (0.25x Kelly)
    adjusted_risk = risk_pct * min(confidence, 1.0) * 0.25
    risk_amount = account_balance * adjusted_risk

    # Pip value (for standard lot of 100,000 units)
    if "JPY" in instrument:
        pip_value_per_unit = 0.01 / 1.0  # Approximate for JPY pairs
    else:
        pip_value_per_unit = 0.0001  # Approximate for most pairs

    # Units = risk_amount / (stop_pips * pip_value_per_unit)
    if stop_pips <= 0 or pip_value_per_unit <= 0:
        return 0

    units = risk_amount / (stop_pips * pip_value_per_unit)

    # Round to nearest 100 (micro lot increments)
    units = max(100, round(units / 100) * 100)

    return int(units)


# ── Analysis Logging ────────────────────────────────────────────────

def log_analysis(analysis_type, data):
    """Log an AI analysis for review."""
    entry = {
        "time": datetime.now(timezone.utc).isoformat(),
        "type": analysis_type,
        **data,
    }
    log = []
    if os.path.exists(ANALYSIS_LOG):
        try:
            with open(ANALYSIS_LOG) as f:
                log = json.load(f)
        except Exception:
            pass
    log.append(entry)
    if len(log) > 500:
        log = log[-500:]
    with open(ANALYSIS_LOG, "w") as f:
        json.dump(log, f, indent=2)


def daily_analysis(trader, mode=None):
    """Generate a comprehensive daily forex analysis."""
    mode = mode or get_brain_mode()

    account = trader.get_account()
    positions = trader.get_positions()
    trades = trader.get_trades()

    # Get quotes for major pairs
    pair_data = {}
    for pair in ["EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD"]:
        q = trader.get_quote(pair)
        if "error" not in q:
            pair_data[pair] = {
                "bid": q["bid"], "ask": q["ask"],
                "spread": q["spread_pips"],
            }

    context = f"""
Forex Account Status:
  Balance: ${float(account['balance']):,.2f}
  NAV: ${float(account['portfolio_value']):,.2f}
  Unrealized P&L: ${float(account['unrealized_pl']):,.2f}
  Open positions: {len(positions)}
  Open trades: {len(trades)}

Current Prices:
"""
    for pair, data in pair_data.items():
        context += f"  {pair}: bid={data['bid']} ask={data['ask']} spread={data['spread']}p\n"

    if positions:
        context += "\nOpen Positions:\n"
        for p in positions:
            context += f"  {p['instrument']}: {p['qty']} units, P&L ${float(p['unrealized_pl']):,.2f}\n"

    question = (
        "Based on this forex portfolio state, provide a brief assessment:\n"
        "1) Are any positions at risk?\n"
        "2) What's the current market environment? (trending/ranging/volatile)\n"
        "3) Any pair-specific observations?\n"
        "4) Recommended actions?\n"
        "Keep it factual and under 200 words."
    )

    result = ask_brain(question, context, mode=mode)

    analysis = {
        "time": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "account": account,
        "positions": positions,
        "pair_data": pair_data,
        "analysis": result.get("answer", result.get("error", "No analysis")),
    }

    log_analysis("daily", analysis)
    return analysis
