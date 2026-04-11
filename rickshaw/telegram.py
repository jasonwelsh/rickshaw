"""Rickshaw Telegram Bot — Lean bridge to engine.process()."""
import asyncio
import logging
import re
import threading
import requests

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters,
)

from . import config

log = logging.getLogger("rickshaw.telegram")


class TelegramBot:
    """Runs a Telegram bot in a background thread, routing messages to the engine."""

    def __init__(self, brain, engine, backend):
        self.brain = brain
        self.engine = engine
        self.backend = backend
        self._app = None
        self._loop = None
        self._thread = None
        self._chat_id = None
        self._running = False

    @property
    def token(self):
        return self.brain.get_config("tg_bot_token")

    @property
    def allowed_users(self):
        raw = self.brain.get_config("tg_allowed_users", "")
        return [u.strip() for u in raw.split(",") if u.strip()]

    @property
    def chat_id(self):
        if self._chat_id:
            return self._chat_id
        stored = self.brain.get_config("tg_chat_id")
        if stored and stored.lstrip("-").isdigit():
            self._chat_id = int(stored)
        return self._chat_id

    def start(self):
        if not self.token:
            log.warning("No bot token configured. Use /setup in REPL.")
            return False

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._running = True
        return True

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._async_main())

    async def _async_main(self):
        app = Application.builder().token(self.token).build()

        app.add_handler(CommandHandler("start", self._cmd_start))
        app.add_handler(CommandHandler("status", self._cmd_status))
        app.add_handler(CommandHandler("tools", self._cmd_tools))
        app.add_handler(CommandHandler("model", self._cmd_model))
        app.add_handler(CommandHandler("fast", self._cmd_fast))
        app.add_handler(CommandHandler("think", self._cmd_think))
        app.add_handler(CommandHandler("memory", self._cmd_memory))
        app.add_handler(CommandHandler("help", self._cmd_help))
        app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, self._on_message
        ))

        self._app = app
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        log.info("Telegram bot polling started")

        # Block until shutdown
        stop_event = asyncio.Event()
        self._stop_event = stop_event
        await stop_event.wait()

        await app.updater.stop()
        await app.stop()
        await app.shutdown()

    def _is_allowed(self, update):
        if not self.allowed_users:
            return True  # No restriction configured
        user = update.effective_user
        username = f"@{user.username}" if user.username else ""
        user_id = str(user.id)
        return username in self.allowed_users or user_id in self.allowed_users

    def _save_chat_id(self, chat_id):
        self._chat_id = chat_id
        self.brain.set_config("tg_chat_id", str(chat_id))

    # ── Commands ─────────────────────────────────────────────────

    async def _cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        self._save_chat_id(update.effective_chat.id)
        name = self.brain.get_config("name", config.NAME)
        await update.message.reply_text(
            f"{name} is online.\n"
            f"Chat ID: {update.effective_chat.id}\n"
            f"Model: {self.backend.model}\n"
            f"Tools: {self.engine.tool_count()}"
        )

    async def _cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update):
            return
        s = self.brain.stats()
        await update.message.reply_text(
            f"Model: {self.backend.model}\n"
            f"Messages: {s['messages']}\n"
            f"Memories: {s['memories']}\n"
            f"Tool calls: {s['tool_calls']} ({s['tool_calls_ok']} ok)"
        )

    async def _cmd_tools(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update):
            return
        lines = [f"Tools ({self.engine.tool_count()}):"]
        from .tools import BUILTIN_TOOLS
        for t in BUILTIN_TOOLS:
            fn = t["function"]
            lines.append(f"  {fn['name']}")
        if self.engine.mcp and self.engine.mcp.tool_count() > 0:
            lines.append("\nMCP:")
            for tname, server, desc in self.engine.mcp.list_tools():
                lines.append(f"  {tname} [{server}]")
        await update.message.reply_text("\n".join(lines))

    async def _cmd_model(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update):
            return
        parts = update.message.text.split(maxsplit=1)
        if len(parts) > 1:
            self.backend.model = parts[1].strip()
            await update.message.reply_text(f"Model -> {self.backend.model}")
        else:
            await update.message.reply_text(f"Current: {self.backend.model}")

    async def _cmd_fast(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update):
            return
        self.backend.model = config.MODEL_FAST
        await update.message.reply_text(f"Model -> {config.MODEL_FAST}")

    async def _cmd_think(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update):
            return
        self.backend.model = config.MODEL_THINK
        await update.message.reply_text(f"Model -> {config.MODEL_THINK}")

    async def _cmd_memory(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update):
            return
        memories = self.brain.get_memories(limit=15)
        if not memories:
            await update.message.reply_text("No memories saved.")
            return
        lines = []
        for m in memories:
            lines.append(f"#{m['id']} [{m['category']}] {m['content'][:60]}")
        await update.message.reply_text("\n".join(lines))

    async def _cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "Commands:\n"
            "/status - Stats\n"
            "/tools - List tools\n"
            "/model <name> - Switch model\n"
            "/fast - Fast model (4B)\n"
            "/think - Think model (9B)\n"
            "/memory - Show memories\n"
            "/help - This message\n\n"
            "Or just send a message to chat."
        )

    # ── Message Handler ──────────────────────────────────────────

    async def _on_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update):
            await update.message.reply_text("Not authorized.")
            return

        self._save_chat_id(update.effective_chat.id)
        text = update.message.text or ""
        if not text.strip():
            return

        # Process in thread to avoid blocking the event loop
        try:
            response = await asyncio.to_thread(self.engine.process, text)
        except Exception as e:
            response = f"Error: {e}"
            log.error(f"Engine error: {e}")

        await self._send_reply(update, response)

    async def _send_reply(self, update, text):
        """Send reply, splitting if over Telegram's 4096 char limit."""
        if not text:
            text = "(empty response)"

        while len(text) > 4000:
            # Split at last newline before limit
            split_at = text.rfind("\n", 0, 4000)
            if split_at < 100:
                split_at = 4000
            await update.message.reply_text(text[:split_at])
            text = text[split_at:].lstrip()

        if text:
            await update.message.reply_text(text)

    # ── Outbound (proactive send) ────────────────────────────────

    def send_text(self, text, prefix=""):
        """Send a message to the stored chat_id (for cross-channel sync)."""
        chat_id = self.chat_id
        if not chat_id or not self.token:
            return False

        full_text = f"{prefix}{text}" if prefix else text
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": chat_id, "text": full_text[:4096]},
                timeout=10,
            )
            return resp.ok
        except Exception as e:
            log.error(f"Telegram send error: {e}")
            return False

    def stop(self):
        if self._stop_event and self._loop:
            self._loop.call_soon_threadsafe(self._stop_event.set)
            self._running = False


def setup_bot(brain):
    """Interactive setup — called from REPL /tg-setup command."""
    print("\n  Telegram Bot Setup")
    print("  ------------------")

    current = brain.get_config("tg_bot_token")
    if current:
        masked = current[:10] + "..." + current[-5:]
        print(f"  Current token: {masked}")
        keep = input("  Keep current token? (y/n): ").strip().lower()
        if keep != "n":
            print("  Token kept.")
        else:
            token = input("  Bot token (from @BotFather): ").strip()
            if token:
                brain.set_config("tg_bot_token", token)
                print("  Token saved.")
    else:
        token = input("  Bot token (from @BotFather): ").strip()
        if token:
            brain.set_config("tg_bot_token", token)
            print("  Token saved.")
        else:
            print("  No token provided. Telegram disabled.")
            return

    users = input("  Allowed users (comma-separated @usernames or IDs, blank=all): ").strip()
    if users:
        brain.set_config("tg_allowed_users", users)
        print(f"  Allowed: {users}")

    chat_id = input("  Chat ID (blank=auto-discover on /start): ").strip()
    if chat_id:
        brain.set_config("tg_chat_id", chat_id)
        print(f"  Chat ID: {chat_id}")

    print("  Done. Restart Rickshaw to connect.\n")
