# Rickshaw Forex

Self-contained forex trading system. CLI + GUI + background engine + AI analysis.

## Quick Start

```bash
cd rickshaw
pip install requests
python -m forex setup          # Configure OANDA API key (or edit forex_config.json)
python -m forex                # Interactive REPL
pythonw forex/forex_gui.pyw    # GUI dashboard
```

## Architecture

```
forex/
├── __init__.py              Package marker
├── __main__.py              CLI + REPL entry point (python -m forex)
├── oanda_client.py          OANDA v3 REST API client (no SDK needed)
├── indicators.py            13 pure-Python technical indicators
├── signals.py               Signal generator — 11 signal types + composite scoring
├── strategies.py            Execution engine — trailing stop, short, auto-scanner
├── brain.py                 AI layer — Qwen (local) or Claude (API) analysis
├── engine_runner.py         Background daemon with Telegram heartbeats
├── forex_gui.pyw            tkinter GUI dashboard
├── forex_config.json        OANDA credentials (edit this)
├── forex_brain_config.json  Brain mode setting (auto/qwen/opus)
├── start_forex.bat          Windows launcher (engine + GUI)
├── requirements.txt         Python dependencies
├── FOREX.md                 This file
│
├── forex_strategies.json    Active strategies (auto-managed)
├── forex_trade_log.json     Trade history (auto-managed)
├── signal_log.json          Signal analysis history (auto-managed)
├── forex_analysis_log.json  AI analysis history (auto-managed)
├── forex_engine.log         Engine log (auto-managed)
└── forex_engine.pid         Engine PID file (auto-managed)
```

## Config Files

### forex_config.json (required)
```json
{
  "oanda_api_key": "your-oanda-api-key",
  "oanda_account_id": "101-001-XXXXXXXX-001",
  "oanda_practice": true
}
```

### forex_brain_config.json (optional)
```json
{"mode": "qwen"}
```
Modes: `auto` (rules only), `qwen` (local Ollama), `opus` (Claude API — needs ANTHROPIC_API_KEY env var)

## CLI Commands (REPL)

```
Trading:
  buy <PAIR> <UNITS>            sell <PAIR> <UNITS>
  quote <PAIR>                  positions / trades
  close [PAIR]                  orders / cancel [ID]
  watch <PAIR> [interval N]     pairs (all major pairs)
  candles <PAIR> [GRAN] [N]     account

Strategies:
  trailing <PAIR> <UNITS> [stop N] [trail N] [tp N]
  short <PAIR> <UNITS> [stop N] [trail N] [tp N]
  strategies                    log <ID>
  stop <ID>                     tick (run one cycle)
  run [INTERVAL]                pnl

Analysis (AI):
  analyze <PAIR> [TF]           scan [TF]
  regime <PAIR> [TF]            sentiment <TEXT>
  brain [auto|qwen|opus]        session
  auto [MAX_POS]                daily
```

## Running the Engine

```bash
# Foreground (debug)
python forex/engine_runner.py --interval 60 --always-heartbeat

# Background daemon
pythonw forex/engine_runner.py --interval 60 --heartbeat-every 5

# Or use the batch file
start_forex.bat
```

The engine:
- Ticks every 60 seconds (configurable)
- Checks all active strategies (trailing stops, shorts)
- Moves stops to breakeven after 1x gain
- Tightens trails at 2x and 3x gains
- Auto-scans for new opportunities every 15 cycles
- Only deploys during high-liquidity sessions (London/NY)
- Sends Telegram heartbeats (if configured)
- AI-powered Telegram updates via Qwen every 5 cycles

## Technical Indicators (13)

| Indicator | Type | Parameters |
|-----------|------|------------|
| EMA crossover (9/21) | Trend | 9, 21 period |
| EMA trend (50/200) | Trend | 50, 200 period |
| ADX + DI | Trend strength | 14 period |
| Ichimoku Cloud | Trend | 9/26/52 standard |
| Bollinger Bands %B | Mean reversion | 20 period, 2.0 std |
| RSI | Mean reversion | 14 period |
| Stochastic %K/%D | Mean reversion | 14, 3, 3 |
| MACD (12/26/9) | Momentum | Standard |
| MACD divergence | Momentum | 20-bar lookback |
| RSI divergence | Momentum | 20-bar lookback |
| Donchian channel | Breakout | 20 period |
| Pivot Points | S/R | Daily H/L/C |
| ATR | Volatility | 14 period |

## Strategy Features

- **Trailing stop (long)**: Pip-based floor, trails up on new highs
- **Short position**: Pip-based ceiling, trails down on new lows
- **Breakeven stop**: Auto-moves to entry + 2 pips after 1x gain
- **Trail tightening**: Narrows to 60% at 2x gain, 40% at 3x gain
- **Take profit**: Sells half at TP target, moves floor to breakeven
- **Ladder buys**: Average down on dips at configurable levels
- **Spread guard**: Skips ticks when spread exceeds max threshold
- **Session awareness**: Knows Tokyo/London/NY/overlap sessions
- **Auto-scanner**: Scans session-appropriate pairs, auto-deploys above 40% confidence
- **ATR-based sizing**: Dynamic position sizing from volatility

## Dependencies

- Python 3.10+
- `requests` (only external dependency)
- Ollama + Qwen 3.5 (optional, for AI brain — `http://localhost:11434`)
- Telegram bot (optional, for heartbeat updates)

## Telegram Setup (optional)

The engine reads Telegram config from:
1. `~/telegram-to-powershell/config.json` (if exists)
2. `../rickshaw.db` SQLite config table (if exists)

To add Telegram manually, create `~/telegram-to-powershell/config.json`:
```json
{"bot_token": "your-bot-token", "chat_id": 123456789}
```

## No External Dependencies on Parent

This folder is fully self-contained. It does NOT import from `trader/` or any sibling package. The only optional external connections are:
- Ollama at `http://localhost:11434` (for AI brain)
- Telegram API (for heartbeat updates)
- OANDA API (for trading — required)
