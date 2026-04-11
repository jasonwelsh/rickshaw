"""Rickshaw Telegram MCP Server — Send messages back to Telegram from Claude Code.

Tools:
  send_telegram  - Send a message to the user's phone
  telegram_status - Check bot/injector status
"""
import asyncio
import json
import os
import sqlite3
import sys
import requests

try:
    from mcp.server import Server
    from mcp.server.stdio import run_server
    import mcp.types as types
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "mcp", "-q"])
    from mcp.server import Server
    from mcp.server.stdio import run_server
    import mcp.types as types

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "rickshaw.db")
PID_FILE = os.path.join(SCRIPT_DIR, "inject.pid")
HWND_FILE = os.path.join(SCRIPT_DIR, "claude_hwnd.txt")

app = Server("rickshaw-telegram")


def _load_config():
    conn = sqlite3.connect(DB_PATH)
    token = conn.execute("SELECT value FROM config WHERE key='tg_bot_token'").fetchone()
    chat_id = conn.execute("SELECT value FROM config WHERE key='tg_chat_id'").fetchone()
    conn.close()
    return (token[0] if token else None, int(chat_id[0]) if chat_id and chat_id[0] else None)


@app.list_tools()
async def list_tools():
    return [
        types.Tool(
            name="send_telegram",
            description=(
                "Send a message to the user's Telegram. "
                "Use this to respond to [Telegram from ...] messages, "
                "send status updates, or notify them of completed tasks."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Message to send"},
                },
                "required": ["text"],
            },
        ),
        types.Tool(
            name="telegram_status",
            description="Check Telegram bot and injector daemon status.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "send_telegram":
        text = arguments.get("text", "")
        if not text:
            return [types.TextContent(type="text", text="No text provided.")]

        token, chat_id = _load_config()
        if not token or not chat_id:
            return [types.TextContent(type="text", text="No bot token or chat_id configured.")]

        try:
            r = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text[:4096]},
                timeout=10,
            )
            if r.ok:
                return [types.TextContent(type="text", text="Sent to Telegram.")]
            return [types.TextContent(type="text", text=f"Telegram API error: {r.status_code}")]
        except Exception as e:
            return [types.TextContent(type="text", text=f"Send error: {e}")]

    elif name == "telegram_status":
        token, chat_id = _load_config()

        # Check injector daemon
        injector_running = False
        injector_pid = None
        if os.path.exists(PID_FILE):
            try:
                with open(PID_FILE) as f:
                    injector_pid = int(f.read().strip())
                os.kill(injector_pid, 0)
                injector_running = True
            except (OSError, ValueError):
                pass

        # Check pinned hwnd
        pinned = None
        if os.path.exists(HWND_FILE):
            try:
                with open(HWND_FILE) as f:
                    pinned = int(f.read().strip())
            except Exception:
                pass

        status = {
            "bot_token": f"...{token[-5:]}" if token else "not set",
            "chat_id": chat_id,
            "injector": f"running (pid={injector_pid})" if injector_running else "stopped",
            "target_hwnd": pinned,
        }
        return [types.TextContent(type="text", text=json.dumps(status, indent=2))]

    return [types.TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    print("Telegram MCP server started (send-only, no polling)", file=sys.stderr)
    async with run_server(app, app.create_initialization_options()) as streams:
        pass

if __name__ == "__main__":
    asyncio.run(main())
