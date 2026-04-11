"""Telegram Inbox Daemon — Watches Telegram, writes messages to inbox file.

Run as: pythonw telegram_inbox.py  (background, no window)
    or: python telegram_inbox.py   (foreground for debugging)

Writes incoming messages to telegram_inbox.txt.
Claude Code reads this file via a pre-prompt hook or manual check.
When Claude responds, it writes to telegram_outbox.txt and this daemon sends it.
"""
import json
import os
import sqlite3
import sys
import time
import requests
import logging

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "rickshaw.db")
INBOX_FILE = os.path.join(SCRIPT_DIR, "telegram_inbox.txt")
OUTBOX_FILE = os.path.join(SCRIPT_DIR, "telegram_outbox.txt")
LOG_FILE = os.path.join(SCRIPT_DIR, "inbox_daemon.log")
POLL_INTERVAL = 3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stderr),
    ],
)
log = logging.getLogger("inbox")


def load_config():
    conn = sqlite3.connect(DB_PATH)
    token = conn.execute("SELECT value FROM config WHERE key='tg_bot_token'").fetchone()
    chat_id = conn.execute("SELECT value FROM config WHERE key='tg_chat_id'").fetchone()
    conn.close()
    return (token[0] if token else None, int(chat_id[0]) if chat_id and chat_id[0] else None)


def send_telegram(token, chat_id, text):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text[:4096]},
            timeout=10,
        )
        return r.ok
    except Exception:
        return False


def main():
    token, chat_id = load_config()
    if not token:
        log.error("No bot token in rickshaw.db")
        sys.exit(1)

    log.info(f"Inbox daemon started. Chat ID: {chat_id}")
    offset = 0

    while True:
        # ── Poll Telegram for incoming messages ──
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{token}/getUpdates",
                json={"timeout": 10, "offset": offset},
                timeout=15,
            )
            if r.ok:
                for update in r.json().get("result", []):
                    offset = update["update_id"] + 1
                    msg = update.get("message", {})
                    text = msg.get("text", "")
                    user = msg.get("from", {})
                    new_chat_id = msg.get("chat", {}).get("id")

                    # Auto-save chat_id
                    if new_chat_id and not chat_id:
                        chat_id = new_chat_id
                        conn = sqlite3.connect(DB_PATH)
                        conn.execute(
                            "INSERT OR REPLACE INTO config (key, value) VALUES ('tg_chat_id', ?)",
                            (str(chat_id),)
                        )
                        conn.commit()
                        conn.close()

                    if text and text == "/start":
                        send_telegram(token, chat_id, "Inbox daemon connected. Messages will be forwarded to Claude.")
                        continue

                    if text:
                        sender = user.get("first_name", "unknown")
                        timestamp = time.strftime("%H:%M:%S")
                        log.info(f"[{sender}] {text}")

                        # Append to inbox file
                        with open(INBOX_FILE, "a", encoding="utf-8") as f:
                            f.write(f"[{timestamp}] {sender}: {text}\n")

                        # Acknowledge
                        send_telegram(token, chat_id, f"[queued for Claude]")

        except Exception as e:
            log.error(f"Poll error: {e}")
            time.sleep(5)

        # ── Check outbox for responses from Claude ──
        try:
            if os.path.exists(OUTBOX_FILE) and os.path.getsize(OUTBOX_FILE) > 0:
                with open(OUTBOX_FILE, "r", encoding="utf-8") as f:
                    response = f.read().strip()
                if response and chat_id:
                    send_telegram(token, chat_id, response)
                    log.info(f"Sent response: {response[:80]}")
                # Clear outbox
                with open(OUTBOX_FILE, "w") as f:
                    f.write("")
        except Exception as e:
            log.error(f"Outbox error: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
