"""Rickshaw Telegram MCP Server — File-based inbox/outbox (no polling conflict).

The telegram_inbox.py daemon handles Telegram polling.
This MCP server just reads/writes the inbox/outbox files.

Tools:
  check_telegram  - Read inbox file (messages from user's phone)
  send_telegram   - Write to outbox file (daemon sends to Telegram)
  telegram_status - Show queue status
"""
import asyncio
import json
import os
import sys

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
INBOX_FILE = os.path.join(SCRIPT_DIR, "telegram_inbox.txt")
OUTBOX_FILE = os.path.join(SCRIPT_DIR, "telegram_outbox.txt")

app = Server("rickshaw-telegram")


@app.list_tools()
async def list_tools():
    return [
        types.Tool(
            name="check_telegram",
            description=(
                "Check for new Telegram messages from the user. "
                "Reads and clears the inbox file. "
                "Call this when the user asks you to check Telegram, "
                "or proactively when you think they might have messaged."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "peek": {
                        "type": "boolean",
                        "description": "If true, show messages without clearing (default: false)",
                    }
                },
            },
        ),
        types.Tool(
            name="send_telegram",
            description=(
                "Send a message to the user's Telegram. "
                "Writes to the outbox file which the daemon sends. "
                "Use this to respond to Telegram messages or send notifications."
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
            description="Check if there are pending Telegram messages.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "check_telegram":
        peek = arguments.get("peek", False)
        if not os.path.exists(INBOX_FILE):
            return [types.TextContent(type="text", text="No new Telegram messages.")]

        try:
            with open(INBOX_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
        except Exception:
            content = ""

        if not content:
            return [types.TextContent(type="text", text="No new Telegram messages.")]

        if not peek:
            # Clear inbox after reading
            with open(INBOX_FILE, "w") as f:
                f.write("")

        return [types.TextContent(type="text", text=content)]

    elif name == "send_telegram":
        text = arguments.get("text", "")
        if not text:
            return [types.TextContent(type="text", text="No text provided.")]
        try:
            with open(OUTBOX_FILE, "a", encoding="utf-8") as f:
                f.write(text + "\n")
            return [types.TextContent(type="text", text="Queued for Telegram delivery.")]
        except Exception as e:
            return [types.TextContent(type="text", text=f"Error: {e}")]

    elif name == "telegram_status":
        inbox_exists = os.path.exists(INBOX_FILE)
        inbox_size = os.path.getsize(INBOX_FILE) if inbox_exists else 0
        outbox_exists = os.path.exists(OUTBOX_FILE)
        outbox_size = os.path.getsize(OUTBOX_FILE) if outbox_exists else 0

        msgs = 0
        if inbox_exists and inbox_size > 0:
            with open(INBOX_FILE, "r") as f:
                msgs = len([l for l in f.readlines() if l.strip()])

        status = f"Inbox: {msgs} message(s) ({inbox_size} bytes)\nOutbox: {outbox_size} bytes pending"
        return [types.TextContent(type="text", text=status)]

    return [types.TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    print("Telegram MCP server started (file-based, no polling)", file=sys.stderr)
    async with run_server(app, app.create_initialization_options()) as streams:
        pass


if __name__ == "__main__":
    asyncio.run(main())
