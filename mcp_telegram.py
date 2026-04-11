"""Rickshaw Telegram MCP Server — Lets Claude Code send/receive Telegram messages.

Add to ~/.claude/settings.json:
  "rickshaw-telegram": {
    "command": "python",
    "args": ["C:\\Users\\jasonwelsh\\rickshaw\\mcp_telegram.py"]
  }

Then in any Claude Code session:
  - check_telegram()     -> read new messages
  - send_telegram(text)  -> send to your phone
  - telegram_status()    -> connection info
"""
import asyncio
import json
import os
import sqlite3
import sys
import time
import threading
import requests

# MCP SDK imports
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

# ── Config ───────────────────────────────────────────────────────────

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rickshaw.db")
POLL_INTERVAL = 2  # seconds between Telegram polls


# ── Telegram Poller ──────────────────────────────────────────────────

class TelegramPoller:
    """Polls Telegram for new messages, stores them for MCP retrieval."""

    def __init__(self, db_path):
        self.db_path = db_path
        self.token = None
        self.chat_id = None
        self.allowed_users = []
        self._offset = 0
        self._messages = []  # Queue of unread messages
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        self._load_config()

    def _load_config(self):
        try:
            conn = sqlite3.connect(self.db_path)
            row = conn.execute("SELECT value FROM config WHERE key='tg_bot_token'").fetchone()
            self.token = row[0] if row else None
            row = conn.execute("SELECT value FROM config WHERE key='tg_chat_id'").fetchone()
            self.chat_id = int(row[0]) if row and row[0] else None
            row = conn.execute("SELECT value FROM config WHERE key='tg_allowed_users'").fetchone()
            self.allowed_users = [u.strip() for u in row[0].split(",")] if row and row[0] else []
            conn.close()
        except Exception:
            pass

    def start(self):
        if not self.token:
            return False
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        return True

    def _poll_loop(self):
        while self._running:
            try:
                params = {"timeout": 10, "offset": self._offset}
                r = requests.post(
                    f"https://api.telegram.org/bot{self.token}/getUpdates",
                    json=params, timeout=15,
                )
                if r.ok:
                    data = r.json()
                    for update in data.get("result", []):
                        self._offset = update["update_id"] + 1
                        msg = update.get("message", {})
                        text = msg.get("text", "")
                        user = msg.get("from", {})
                        username = f"@{user.get('username', '')}"
                        chat_id = msg.get("chat", {}).get("id")

                        # Save chat_id on first message
                        if chat_id and not self.chat_id:
                            self.chat_id = chat_id
                            try:
                                conn = sqlite3.connect(self.db_path)
                                conn.execute(
                                    "INSERT OR REPLACE INTO config (key, value) VALUES ('tg_chat_id', ?)",
                                    (str(chat_id),)
                                )
                                conn.commit()
                                conn.close()
                            except Exception:
                                pass

                        if text:
                            with self._lock:
                                self._messages.append({
                                    "from": user.get("first_name", "unknown"),
                                    "username": username,
                                    "text": text,
                                    "time": time.strftime("%H:%M:%S"),
                                    "chat_id": chat_id,
                                })
            except Exception:
                time.sleep(5)

            time.sleep(POLL_INTERVAL)

    def get_messages(self):
        """Return and clear unread messages."""
        with self._lock:
            msgs = list(self._messages)
            self._messages.clear()
        return msgs

    def peek_messages(self):
        """Return unread messages without clearing."""
        with self._lock:
            return list(self._messages)

    def send(self, text):
        """Send a message to the stored chat."""
        if not self.token or not self.chat_id:
            return "No token or chat_id configured. User must /start the bot first."
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": self.chat_id, "text": text[:4096]},
                timeout=10,
            )
            if r.ok:
                return "Sent."
            return f"Telegram API error: {r.text}"
        except Exception as e:
            return f"Send error: {e}"

    def stop(self):
        self._running = False


# ── MCP Server ───────────────────────────────────────────────────────

app = Server("rickshaw-telegram")
poller = TelegramPoller(DB_PATH)


@app.list_tools()
async def list_tools():
    return [
        types.Tool(
            name="check_telegram",
            description=(
                "Check for new Telegram messages from the user. "
                "Returns any unread messages and clears the queue. "
                "Call this when the user asks you to check Telegram, "
                "or proactively if you know they might message you."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "peek": {
                        "type": "boolean",
                        "description": "If true, show messages without clearing them (default: false)",
                    }
                },
            },
        ),
        types.Tool(
            name="send_telegram",
            description=(
                "Send a message to the user's Telegram. "
                "Use this to respond to their Telegram messages, "
                "send status updates, or notify them of completed tasks."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Message to send",
                    }
                },
                "required": ["text"],
            },
        ),
        types.Tool(
            name="telegram_status",
            description="Check Telegram bot connection status and config.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "check_telegram":
        peek = arguments.get("peek", False)
        msgs = poller.peek_messages() if peek else poller.get_messages()
        if not msgs:
            return [types.TextContent(type="text", text="No new Telegram messages.")]
        lines = []
        for m in msgs:
            lines.append(f"[{m['time']}] {m['from']}: {m['text']}")
        return [types.TextContent(type="text", text="\n".join(lines))]

    elif name == "send_telegram":
        text = arguments.get("text", "")
        if not text:
            return [types.TextContent(type="text", text="No text provided.")]
        result = poller.send(text)
        return [types.TextContent(type="text", text=result)]

    elif name == "telegram_status":
        status = {
            "bot_token": f"...{poller.token[-5:]}" if poller.token else "not set",
            "chat_id": poller.chat_id,
            "allowed_users": poller.allowed_users,
            "polling": poller._running,
            "unread": len(poller.peek_messages()),
        }
        return [types.TextContent(type="text", text=json.dumps(status, indent=2))]

    return [types.TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    started = poller.start()
    if started:
        # Log to stderr so it doesn't pollute MCP stdout
        print(f"Telegram poller started (chat_id={poller.chat_id})", file=sys.stderr)
    else:
        print("Warning: No Telegram bot token configured", file=sys.stderr)

    async with run_server(app, app.create_initialization_options()) as streams:
        pass


if __name__ == "__main__":
    asyncio.run(main())
