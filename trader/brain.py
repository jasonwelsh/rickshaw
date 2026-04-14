"""Rickshaw Trader Brain — Switch between Opus (Claude) and Qwen for decisions.

The brain handles the "thinking" layer above the mechanical strategy engine.
The engine runs rules. The brain picks WHICH rules to run and tunes parameters.

Two modes:
  opus:  Claude makes decisions via MCP tools (smarter, costs API credits)
  qwen:  Qwen 3.5 makes decisions locally (free, dumber, needs strict rules)
  auto:  Engine runs mechanically with no brain involvement (safest)

In "auto" mode, the brain does nothing — the engine just follows its rules.
In "opus" or "qwen" mode, the brain can:
  - Suggest new strategies based on market conditions
  - Adjust parameters (stop %, trail %) based on volatility
  - Decide when to enter/exit copy trades
  - Provide daily analysis summaries
"""
import json
import os
import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BRAIN_CONFIG = os.path.join(SCRIPT_DIR, "brain_config.json")


def get_brain_mode():
    """Get current brain mode: auto, opus, or qwen."""
    if os.path.exists(BRAIN_CONFIG):
        with open(BRAIN_CONFIG) as f:
            cfg = json.load(f)
        return cfg.get("mode", "auto")
    return "auto"


def set_brain_mode(mode):
    """Set brain mode."""
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


def ask_brain(question, context=""):
    """Ask the current brain a question. Returns the answer."""
    mode = get_brain_mode()

    if mode == "auto":
        return {"answer": "Auto mode — no brain consulted. Engine follows mechanical rules only.",
                "mode": "auto"}

    if mode == "qwen":
        return _ask_qwen(question, context)

    if mode == "opus":
        return {"answer": "Opus mode — decision delegated to Claude in the terminal.",
                "mode": "opus", "question": question}

    return {"error": f"Unknown mode: {mode}"}


def _ask_qwen(question, context=""):
    """Ask Qwen 3.5 via Ollama for a trading decision."""
    try:
        system = (
            "You are a trading strategy assistant. You make rule-based decisions only. "
            "Never guess or speculate. If you don't have enough data, say so. "
            "Keep responses under 100 words. Be specific with numbers."
        )

        messages = [
            {"role": "system", "content": system},
        ]
        if context:
            messages.append({"role": "user", "content": f"Context: {context}"})
        messages.append({"role": "user", "content": question})

        resp = requests.post(
            "http://localhost:11434/v1/chat/completions",
            json={
                "model": "qwen3.5:4b",
                "messages": messages,
                "temperature": 0.2,
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"].get("content", "")

        # Strip <think> blocks
        import re
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

        return {"answer": content, "mode": "qwen"}
    except Exception as e:
        return {"error": str(e), "mode": "qwen"}


def daily_analysis(trader):
    """Generate a daily analysis based on current positions and strategies."""
    from trader.strategies import get_strategies, get_pnl_summary

    positions = trader.get_positions()
    strategies = get_strategies(status="active")
    pnl = get_pnl_summary()
    account = trader.get_account()

    context = f"""
Account: ${account['portfolio_value']} portfolio, ${account['cash']} cash
Active strategies: {len(strategies)}
Realized P&L: ${pnl['realized_pnl']}
Open positions: {len(positions)}
"""
    for p in positions:
        context += f"  {p['symbol']}: {p['qty']} shares, P&L ${p['unrealized_pl']}\n"

    question = (
        "Based on this portfolio state, provide a brief daily assessment: "
        "1) Are any positions at risk? "
        "2) Should any strategies be adjusted? "
        "3) Any recommendations? "
        "Keep it factual and rule-based."
    )

    return ask_brain(question, context)
