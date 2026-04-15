"""Rickshaw Trader Research Mode — AI-driven market analysis and trade planning.

Runs 2-3 times daily:
  Pre-market (8:30 AM ET):  What happened overnight? What's moving pre-market?
  Midday (12:00 PM ET):     How are positions doing? Any sector rotation?
  After-hours (4:30 PM ET): Day review. Plan for tomorrow.

The brain (opus/qwen/auto) analyzes data and produces actionable plans.
Plans can be auto-executed or queued for review.
"""
import json
import os
import sys
import time
import requests
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(SCRIPT_DIR))

RESEARCH_LOG = os.path.join(SCRIPT_DIR, "research_log.json")
WATCHLIST_FILE = os.path.join(SCRIPT_DIR, "watchlist.json")


# ── Data Gathering ───────────────────────────────────────────────────

def get_market_movers(trader):
    """Get price data for a broad set of tickers to find what's moving."""
    sectors = {
        "Tech": ["AAPL", "MSFT", "NVDA", "GOOG", "META", "AMZN"],
        "Finance": ["JPM", "BAC", "GS", "V", "MA"],
        "Energy": ["XOM", "CVX", "COP", "SLB"],
        "Healthcare": ["UNH", "JNJ", "LLY", "PFE", "ABBV"],
        "Industrial": ["CAT", "DE", "BA", "HON", "GE"],
        "Consumer": ["WMT", "COST", "HD", "MCD", "NKE"],
    }

    movers = []
    for sector, symbols in sectors.items():
        for sym in symbols:
            try:
                q = trader.get_quote(sym)
                if "bid" in q:
                    bid = float(q["bid"])
                    ask = float(q["ask"])
                    mid = (bid + ask) / 2
                    spread_pct = ((ask - bid) / mid * 100) if mid > 0 else 0
                    movers.append({
                        "symbol": sym,
                        "sector": sector,
                        "price": round(mid, 2),
                        "spread_pct": round(spread_pct, 2),
                    })
            except Exception:
                pass
    return movers


def get_portfolio_summary(trader):
    """Get current portfolio state."""
    acct = trader.get_account()
    positions = trader.get_positions()

    pos_list = []
    for p in positions:
        pos_list.append({
            "symbol": p["symbol"],
            "qty": p["qty"],
            "avg_entry": float(p["avg_entry"]),
            "current": float(p["current_price"]),
            "pl": float(p["unrealized_pl"]),
            "pl_pct": float(p["unrealized_plpc"]) * 100,
        })

    return {
        "cash": float(acct["cash"]),
        "portfolio_value": float(acct["portfolio_value"]),
        "equity": float(acct["equity"]),
        "positions": pos_list,
        "total_pl": sum(p["pl"] for p in pos_list),
    }


def get_politician_signals():
    """Check Capitol Trades for recent politician activity."""
    from trader import capitol_trades
    try:
        return capitol_trades.get_recent_trades()
    except Exception:
        return {"error": "Could not fetch politician trades"}


def load_watchlist():
    """Load the watchlist of stocks we're monitoring."""
    if os.path.exists(WATCHLIST_FILE):
        with open(WATCHLIST_FILE) as f:
            return json.load(f)
    return []


def save_watchlist(watchlist):
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(watchlist, f, indent=2)


# ── Research Engine ──────────────────────────────────────────────────

def build_research_prompt(trader, session_type="midday"):
    """Build a research prompt with all available data."""
    portfolio = get_portfolio_summary(trader)
    movers = get_market_movers(trader)
    watchlist = load_watchlist()

    # Sort movers by spread (tighter spread = more liquid = better to trade)
    movers.sort(key=lambda x: x["spread_pct"])

    prompt_parts = []

    prompt_parts.append(f"SESSION: {session_type.upper()} RESEARCH")
    prompt_parts.append(f"TIME: {datetime.now().strftime('%Y-%m-%d %H:%M ET')}")

    # Portfolio state
    prompt_parts.append(f"\nPORTFOLIO: ${portfolio['portfolio_value']:,.0f} "
                       f"(Cash: ${portfolio['cash']:,.0f}, P&L: ${portfolio['total_pl']:+,.2f})")
    if portfolio["positions"]:
        prompt_parts.append("Current positions:")
        for p in portfolio["positions"]:
            prompt_parts.append(f"  {p['symbol']}: {p['qty']} shares @ ${p['avg_entry']:.2f} "
                              f"-> ${p['current']:.2f} ({p['pl_pct']:+.1f}%)")

    # Market data
    prompt_parts.append(f"\nMARKET QUOTES ({len(movers)} stocks):")
    by_sector = {}
    for m in movers:
        by_sector.setdefault(m["sector"], []).append(m)
    for sector, stocks in by_sector.items():
        syms = " | ".join(f"{s['symbol']}:${s['price']}" for s in stocks)
        prompt_parts.append(f"  {sector}: {syms}")

    # Watchlist
    if watchlist:
        prompt_parts.append(f"\nWATCHLIST: {', '.join(w.get('symbol','?') for w in watchlist)}")

    # Instructions
    prompt_parts.append(f"""
TASK: Based on this data, provide a research report with:

1. MARKET ASSESSMENT: What sectors look strong/weak right now based on prices?
2. PORTFOLIO REVIEW: Any positions we should adjust (tighten stops, take profit, exit)?
3. NEW OPPORTUNITIES: 1-3 specific trade ideas with:
   - Symbol, direction (buy/short), reasoning
   - Entry price target
   - Stop loss level
   - Profit target
4. WATCHLIST UPDATE: Any stocks to add/remove from the watchlist?
5. RISK CHECK: Are we too concentrated in one sector? Any upcoming risks?

Keep it factual. No speculation. Base everything on the price data provided.
Output as a structured report, not a conversation.""")

    return "\n".join(prompt_parts)


def run_research(trader, session_type="midday", brain_mode="qwen"):
    """Run a research cycle. Returns the analysis."""
    prompt = build_research_prompt(trader, session_type)

    if brain_mode == "auto":
        return {
            "session": session_type,
            "time": datetime.now().isoformat(),
            "mode": "auto",
            "report": "Auto mode — no AI research. Engine runs rules only.",
            "prompt": prompt,
        }

    if brain_mode == "qwen":
        answer = _ask_qwen(prompt)
    elif brain_mode == "opus":
        answer = {
            "answer": prompt,
            "note": "Opus mode — prompt returned for Claude to analyze in terminal.",
        }
    else:
        answer = {"answer": "Unknown brain mode."}

    result = {
        "session": session_type,
        "time": datetime.now().isoformat(),
        "mode": brain_mode,
        "report": answer.get("answer", ""),
    }

    # Save to log
    log = []
    if os.path.exists(RESEARCH_LOG):
        with open(RESEARCH_LOG) as f:
            log = json.load(f)
    log.append(result)
    if len(log) > 50:
        log = log[-50:]
    with open(RESEARCH_LOG, "w") as f:
        json.dump(log, f, indent=2)

    return result


def _ask_qwen(prompt, max_retries=3):
    """Ask Qwen 3.5 for research analysis. Retries on failure, falls back to 4B."""
    models = ["qwen3.5:9b", "qwen3.5:9b", "qwen3.5:4b"]  # 2 tries with 9B, fallback to 4B

    for attempt in range(max_retries):
        model = models[min(attempt, len(models) - 1)]
        try:
            resp = requests.post(
                "http://localhost:11434/v1/chat/completions",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": (
                            "You are a stock market research analyst. "
                            "Provide concise, data-driven analysis. "
                            "No speculation. Structure your output clearly. "
                            "Keep under 300 words."
                        )},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.3,
                },
                timeout=180,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"].get("content", "")
            import re
            content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
            if content and len(content) > 20:
                return {"answer": content, "model": model, "attempt": attempt + 1}
        except Exception as e:
            if attempt < max_retries - 1:
                import time
                time.sleep(5)  # Brief pause before retry
                continue
            return {"answer": f"Qwen failed after {max_retries} attempts: {e}"}

    return {"answer": "Qwen returned empty response after all retries"}


def pre_screen_research(trader):
    """Qwen analyzes market data and outputs a curated ticker list for the screener.

    This runs BEFORE the screener. Qwen thinks, screener filters.

    Returns: list of symbols Qwen recommends screening, with reasons.
    """
    movers = get_market_movers(trader)
    portfolio = get_portfolio_summary(trader)

    # Build focused prompt for ticker selection
    by_sector = {}
    for m in movers:
        by_sector.setdefault(m["sector"], []).append(m)

    prompt = f"""You are a pre-market stock screener for a small account (${portfolio['cash']:,.0f} cash).

CURRENT POSITIONS: {', '.join(p['symbol'] for p in portfolio['positions']) if portfolio['positions'] else 'none'}

MARKET DATA:
"""
    for sector, stocks in by_sector.items():
        syms = " | ".join(f"{s['symbol']}:${s['price']}" for s in stocks)
        prompt += f"  {sector}: {syms}\n"

    prompt += f"""
TASK: Pick exactly 10 stock tickers to screen for buying today.

RULES:
- Must be affordable (price under ${portfolio['cash'] * 0.9:.0f})
- Diversify across sectors (max 2 per sector)
- Don't pick stocks we already hold
- Prefer stocks showing momentum (price movement)
- Include at least 1 from each sector if affordable

OUTPUT FORMAT (exactly this, one per line):
SYMBOL|SECTOR|REASON

Example:
BAC|Finance|Strong banking sector momentum
PFE|Healthcare|Low price entry point at $27

Output ONLY the 10 lines, nothing else."""

    answer = _ask_qwen(prompt)
    report = answer.get("answer", "")

    # Parse the response into a ticker list
    picks = []
    for line in report.strip().split("\n"):
        line = line.strip()
        if "|" in line:
            parts = line.split("|")
            if len(parts) >= 2:
                symbol = parts[0].strip().upper()
                # Validate it's a real ticker (1-5 uppercase letters)
                import re
                if re.match(r'^[A-Z]{1,5}$', symbol):
                    picks.append({
                        "symbol": symbol,
                        "sector": parts[1].strip() if len(parts) > 1 else "Unknown",
                        "reason": parts[2].strip() if len(parts) > 2 else "",
                    })

    # Save to watchlist for the screener
    if picks:
        save_watchlist(picks)

    # Log
    result = {
        "session": "pre_screen",
        "time": datetime.now().isoformat(),
        "mode": "qwen",
        "picks": picks,
        "report": report,
    }
    log = []
    if os.path.exists(RESEARCH_LOG):
        with open(RESEARCH_LOG) as f:
            log = json.load(f)
    log.append(result)
    if len(log) > 50:
        log = log[-50:]
    with open(RESEARCH_LOG, "w") as f:
        json.dump(log, f, indent=2)

    return picks


def get_research_schedule():
    """Return the standard research schedule."""
    return [
        {"name": "pre_market", "hour": 8, "minute": 30, "label": "Pre-Market Analysis"},
        {"name": "midday", "hour": 12, "minute": 0, "label": "Midday Review"},
        {"name": "after_hours", "hour": 16, "minute": 30, "label": "After-Hours Review"},
    ]


def get_last_research():
    """Get the most recent research report."""
    if os.path.exists(RESEARCH_LOG):
        with open(RESEARCH_LOG) as f:
            log = json.load(f)
        if log:
            return log[-1]
    return None
