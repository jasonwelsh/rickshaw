# Rickshaw — Local AI Agent Harness

## What It Is
Rickshaw is a local AI agent that runs on Qwen 3.5 via Ollama. It exists so that if cloud AI goes dark, you still have an intelligent agent on your hardware with tools, memory, and communication.

Think of it as a local Opus replacement. Dumber, but runs forever on your GPU with zero internet dependency (except for tools that need APIs).

## Why It Exists
- Cloud AI can go offline, get rate-limited, or get expensive
- A local agent with memory, tools, and Telegram access keeps working regardless
- The harness is the survival kit — the tools are what make it useful

## Architecture
```
Rickshaw (Qwen 3.5 local brain)
├── Core
│   ├── engine.py         — Agent loop with native tool calling
│   ├── brain.py          — SQLite storage (messages, memory, sessions, config)
│   ├── backend.py        — Ollama OpenAI-compatible client
│   ├── tools.py          — 8 built-in tools + executor
│   ├── mcp_bridge.py     — MCP server bridge (JSON-RPC stdio)
│   ├── context.py        — RICKSHAW.md loader (mirrors CLAUDE.md pattern)
│   ├── telegram.py       — Telegram bot (@rickshaw_ai_bot)
│   └── config.py         — Defaults (models, URLs, limits)
│
├── Trader Module (trader/)
│   ├── alpaca_client.py  — Alpaca SDK wrapper (buy/sell/positions/quotes)
│   ├── strategies.py     — Trailing stop, copy trading, P&L tracking
│   ├── screener.py       — Mechanical stock screener (60 stocks, 6 sectors)
│   ├── research.py       — Qwen pre-screen research + market analysis
│   ├── brain.py          — Brain switch (auto/qwen/opus)
│   ├── engine_runner.py  — Background daemon with Telegram heartbeat
│   ├── capitol_trades.py — Politician trade scraper
│   ├── mcp_trader.py     — MCP server (12 trading tools)
│   ├── trader_gui.pyw    — Trading dashboard GUI
│   └── __main__.py       — CLI REPL
│
├── Forex Module (forex/)
│   ├── (built by Jason — separate development)
│   └── engine_runner.py  — 24/5 forex engine
│
└── Config Files
    ├── RICKSHAW.md        — Context file loaded before every prompt
    ├── mcp_servers.json   — MCP server registry
    ├── rickshaw.db        — SQLite brain (messages, memory, sessions, tools)
    └── run_service.py     — Background service launcher
```

## Models
- **Qwen 3.5 9B** (think model) — 6.6GB VRAM, used for research/reasoning
- **Qwen 3.5 4B** (fast model) — 3.4GB VRAM, used for tool dispatch/quick responses
- Models stored on `D:\ollama\models` (OLLAMA_MODELS env var)
- Both pulled via `ollama pull qwen3.5:9b` and `ollama pull qwen3.5:4b`

## Hardware
- **FastBall** (10.0.0.7): Windows 11 Pro, RTX 4070 Super 12GB, 64GB RAM
- Ollama runs at `http://localhost:11434`

## How to Run

### Agent (Telegram bot + REPL)
```bash
# Interactive REPL
python -m rickshaw

# Background service (Telegram bot)
pythonw run_service.py --fast

# One-shot
python -m rickshaw "what time is it"
```

### Trader
```bash
# Interactive trading REPL
python -m trader

# Background engine (auto-trades during market hours)
pythonw trader/engine_runner.py --interval 300 --always-heartbeat

# Trader GUI
pythonw trader/trader_gui.pyw
```

### Commands
```
# REPL commands
/model <name>   /fast   /think   /tools   /memory
/stats   /reset   /save   /resume   /context   /quit

# Trader REPL commands
buy AAPL 10     sell TSLA 5      quote AAPL TSLA
positions       orders           account
trailing AAPL 10 stop 10 trail 5
copy michael-mccaul 5000
screen          auto 8           research midday qwen
strategies      pnl              run 300
```

## Tool Inventory (46 total)

### Built-in (8)
remember, recall, forget, run_command, read_file, write_file, list_files, get_time

### Home Assistant MCP (13)
ha_ping, ha_get_entities, ha_get_entity, ha_call_service, ha_list_automations, ha_toggle_automation, ha_device_health, ha_start_config_flow, ha_config_flow_step, ha_get_config_flow, ha_list_config_entries, ha_quick_config_flow, ha_delete_config_entry

### ESPHome MCP (7)
list_devices, flash_esp32, compile_esp32, get_esp32_logs, list_com_ports, esphome_validate, generate_esphome_yaml

### Hardware Planner MCP (6)
generate_bom, generate_wiring_diagram, device_registry_list, device_registry_update, device_registry_scan

### Trader MCP (12)
trade_buy, trade_sell, trade_account, trade_positions, trade_orders, trade_cancel, trade_quote, trade_close_position, capitol_recent_trades, capitol_top_traders, capitol_politician_trades, trade_setup

## Trader Engine Details

### Flow: Qwen Research → Screener → Deploy → Manage
1. **Pre-market**: Qwen 9B analyzes 60 stocks across 6 sectors, picks 10 tickers with reasons
2. **Market open**: Screener scores Qwen's picks only (no static fallback — no research = no trading)
3. **Deploy**: Creates trailing stop strategies for top picks, sized to available cash
4. **Manage**: Engine ticks every 5 min during market hours
   - Trails floor up on new highs
   - Sells if floor hit (stop loss)
   - Takes profit at +15% (sells half)
   - Ladder buys on dips
5. **Market close**: Sends EOD summary to Telegram
6. **Overnight**: Engine sleeps (checks clock every 5 min)
7. **Next morning**: Cycle repeats

### Strategy Types
- **Trailing Stop**: Entry → floor moves up → stop sells → lock gains
- **Copy Trading**: Follow politician trades from Capitol Trades
- **Profit Taking**: Auto-sell half at +15%
- **Ladder Buys**: Average down on dips (-20%, -30%)

### Screener Scoring (weighted 0-100)
- Momentum 5-day (30%), Momentum 20-day (25%)
- Spread/liquidity (15%), Price range (10%)
- Sector balance (15%), Congress signal (5%)

### Brain Switch
- **auto**: Pure mechanical rules, no AI thinking (safest)
- **qwen**: Qwen 3.5 for research/suggestions (free, local)
- **opus**: Claude makes the calls (smartest, costs credits)

### Critical Rules Learned from Testing
1. Position sizing must match account balance
2. Price filter must block stocks you can't afford
3. PDT rule: max 3 day trades per 5 days on accounts under $25K
4. Never wipe and redeploy same day on small accounts
5. No research = no trading (Qwen must curate picks first)
6. VRAM conflicts: Qwen and Trellis 2 fight for GPU memory

## Alpaca API
- Paper trading: `paper-api.alpaca.markets`
- Rate limit: 200 requests/min (we use ~3/min at 5-min intervals)
- Account A (PDT locked): keys in old config
- Account B ($500 test): keys in current `trader/trader_config.json`
- Config: `trader/trader_config.json` (api_key, secret_key, paper=true)

## Communication Layer

### Telegram Bots
- **@rickshaw_ai_bot** — Qwen agent (runs via run_service.py)
- **@powershell_claude_bot** — Claude terminal injection (separate project)

### Heartbeat System
- Engine sends heartbeat to Telegram every cycle during market hours
- Format: portfolio value, P&L, positions, actions taken
- Market-aware: pauses outside market hours
- Telegram Bridge GUI has manual heartbeat with configurable interval + random jitter

## Auto-Start (Task Scheduler)
| Task | Delay | What |
|------|-------|------|
| TelegramInjector | +15s | PostMessage bridge for Claude |
| RickshawTraderEngine | +30s | Stock trading engine |
| RickshawBot | +45s | Qwen Telegram bot |

## Database Schema (rickshaw.db)
```sql
config          -- key/value store (name, personality, bot tokens, etc.)
messages        -- conversation history (role, content, session_id)
memory          -- persistent facts (category, content, tags)
sessions        -- session save/resume (summary, next_steps)
tool_calls      -- every tool execution (name, args, result, duration)
```

## Context System (RICKSHAW.md)
Mirrors Claude Code's CLAUDE.md pattern:
- Walks upward from CWD to discover instruction files
- User-level: `~/.rickshaw/RICKSHAW.md`
- Project-level: `RICKSHAW.md`, `.rickshaw/RICKSHAW.md`
- Local: `RICKSHAW.local.md`
- Supports `@include` directives
- Injected into system prompt before every LLM call
- Memoized per session

## MCP Bridge
- Speaks JSON-RPC over stdio (newline-delimited, NOT Content-Length framing)
- Auto-discovers tools from MCP server's `list_tools` response
- Converts MCP tool schemas to OpenAI function calling format
- Servers registered in `mcp_servers.json`

## Network
- FastBall (this PC): 10.0.0.7, SSH :2222, RDP :41927
- mushroom (Mac mini): 10.0.0.242, SSH :3333, Google Drive Y:
- canned (Mac mini): 10.0.0.11, SSH :4444, Dropbox Z:

## Git
- Repo: https://github.com/jasonwelsh/rickshaw
- Branch: master

## If You're Picking This Up
1. Make sure Ollama is running (`ollama serve`)
2. Make sure qwen3.5:9b and qwen3.5:4b are pulled
3. `python -m rickshaw` to test the agent
4. `python -m trader account` to check Alpaca connection
5. Read RICKSHAW.md for the agent's personality/context
6. The engine auto-starts via Task Scheduler on reboot
7. If Qwen times out, check VRAM (`nvidia-smi`) — something else might be using the GPU
8. The trader ONLY trades if Qwen research succeeds. No research = no trades.
