# Rickshaw

A Telegram-to-PowerShell bridge that lets you control [Claude Code](https://claude.ai/claude-code) from your phone.

Type a message on Telegram → it appears directly in Claude Code's terminal as typed input → Claude processes it → responds back to your phone.

Also includes a lean local LLM agentic engine powered by Qwen 3.5 via Ollama.

## How It Works

```
Phone → @your_bot → telegram_inject.py daemon
                         │
               PostMessage WM_CHAR (Win32)
                         │
               Claude Code terminal (by hwnd)
                         │
               Claude reads as typed input
                         │
               send_telegram MCP tool → Phone
```

**The key hack:** `PostMessage WM_CHAR` sends characters directly to a specific window handle without stealing focus, touching the clipboard, or flashing any windows. Your keyboard and Telegram messages both feed into the same input line simultaneously.

## Quick Start

### 1. Create a Telegram Bot
- Message `@BotFather` on Telegram → `/newbot` → name it anything
- Copy the bot token

### 2. Set Up
```bash
cd rickshaw
python -m pip install requests pyautogui pywin32

# First run — creates the database
python -m rickshaw --no-telegram "hello"
```

### 3. Configure Bot Token
Open the GUI:
```bash
pythonw tg_manager.pyw
```
Click **"Change Bot"** and paste your token. Then send `/start` to your bot on Telegram.

### 4. Pin Target Window
In the GUI, double-click the Claude Code console window to set it as the injection target.

### 5. Start the Daemon
Click **"Start Daemon"** in the GUI, or:
```bash
pythonw telegram_inject.py
```

That's it. Messages from Telegram now appear in Claude's terminal.

## Components

| File | Purpose |
|------|---------|
| `telegram_inject.py` | Daemon — polls Telegram, injects via PostMessage WM_CHAR |
| `tg_manager.pyw` | GUI — window picker, bot config, daemon control |
| `mcp_telegram.py` | MCP server — `send_telegram` tool for Claude to reply |
| `rickshaw/` | Local LLM agent engine (Qwen 3.5 via Ollama) |
| `RICKSHAW.md` | Context file loaded before every LLM prompt |

## Telegram Commands

Send these to your bot:
- `/status` — Check injector state
- `/windows` — List all console windows with their hwnd
- `/pin <hwnd>` — Retarget to a different window
- `/start` — Initialize the bot connection

## CLI

```bash
python telegram_inject.py status    # Show daemon status
python telegram_inject.py windows   # List console windows
python telegram_inject.py pin 12345 # Pin a window
python telegram_inject.py stop      # Stop the daemon
python telegram_inject.py test      # Send test injection
python telegram_inject.py --debug   # Run in foreground with logging
```

## MCP Integration

Add to `~/.claude/settings.json`:
```json
{
  "mcpServers": {
    "rickshaw-telegram": {
      "command": "python",
      "args": ["C:\\path\\to\\rickshaw\\mcp_telegram.py"]
    }
  }
}
```

Claude Code gets `send_telegram` and `telegram_status` tools to respond to Telegram messages.

## Local LLM Agent

Rickshaw also includes a standalone agent powered by Qwen 3.5:

```bash
python -m rickshaw                # Interactive REPL (9B model)
python -m rickshaw --fast         # Fast mode (4B model)
python -m rickshaw "do something" # One-shot
```

Features: native tool calling, persistent memory, session resume, MCP bridge, RICKSHAW.md context injection.

## Requirements

- Windows 10/11
- Python 3.10+
- `requests`, `pyautogui`, `pywin32`
- [Ollama](https://ollama.ai) (for local LLM agent)
- [Claude Code](https://claude.ai/claude-code) (for the bridge)

## License

MIT
