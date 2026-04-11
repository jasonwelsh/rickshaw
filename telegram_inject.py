"""Telegram-to-Claude Injector — Types Telegram messages into Claude's terminal.

Run as:  pythonw telegram_inject.py   (background, no window)
    or:  python telegram_inject.py    (foreground for debugging)

Uses pyautogui + SetForegroundWindow to simulate typing into
the Claude Code terminal window. Messages arrive from Telegram,
get typed as if the user pressed the keys.
"""
import ctypes
import ctypes.wintypes
import json
import os
import sqlite3
import sys
import time
import requests
import logging
import pyautogui

# Disable pyautogui failsafe (mouse to corner won't abort)
pyautogui.FAILSAFE = False
# Faster typing
pyautogui.PAUSE = 0.01

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "rickshaw.db")
LOG_FILE = os.path.join(SCRIPT_DIR, "inject.log")
POLL_INTERVAL = 3

user32 = ctypes.windll.user32

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger("inject")


def load_config():
    conn = sqlite3.connect(DB_PATH)
    token = conn.execute("SELECT value FROM config WHERE key='tg_bot_token'").fetchone()
    chat_id = conn.execute("SELECT value FROM config WHERE key='tg_chat_id'").fetchone()
    conn.close()
    return (token[0] if token else None, int(chat_id[0]) if chat_id and chat_id[0] else None)


def send_telegram(token, chat_id, text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text[:4096]},
            timeout=10,
        )
    except Exception:
        pass


HWND_FILE = os.path.join(SCRIPT_DIR, "claude_hwnd.txt")


def find_claude_window():
    """Find the Claude Code window. Prefers pinned hwnd from file."""
    # Check for pinned hwnd first
    if os.path.exists(HWND_FILE):
        try:
            with open(HWND_FILE, "r") as f:
                pinned = int(f.read().strip())
            if user32.IsWindow(pinned):
                length = user32.GetWindowTextLengthW(pinned) + 1
                buf = ctypes.create_unicode_buffer(length)
                user32.GetWindowTextW(pinned, buf, length)
                return pinned, buf.value
        except Exception:
            pass

    # Fallback: scan for Claude windows
    result = []

    def enum_cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            class_buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_buf, 256)
            win_class = class_buf.value

            if win_class not in ("ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS"):
                return True

            length = user32.GetWindowTextLengthW(hwnd) + 1
            buf = ctypes.create_unicode_buffer(length)
            user32.GetWindowTextW(hwnd, buf, length)
            title = buf.value

            if "Claude" in title or "claude" in title:
                result.append((hwnd, title, win_class))
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
    )
    user32.EnumWindows(WNDENUMPROC(enum_cb), 0)

    for hwnd, title, cls in result:
        if cls == "ConsoleWindowClass":
            return hwnd, title
    if result:
        return result[0][0], result[0][1]
    return None, None


def type_into_window(hwnd, text):
    """Send text directly to a window via PostMessage WM_CHAR. No focus change needed."""
    WM_CHAR = 0x0102

    if not user32.IsWindow(hwnd):
        log.error(f"Window {hwnd} no longer exists")
        return False

    # Send each character
    for ch in text:
        user32.PostMessageW(hwnd, WM_CHAR, ord(ch), 0)

    # Send Enter
    user32.PostMessageW(hwnd, WM_CHAR, 13, 0)

    return True


def main():
    token, chat_id = load_config()
    if not token:
        log.error("No bot token")
        sys.exit(1)

    log.info(f"Injector started. Chat ID: {chat_id}")
    offset = 0

    while True:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{token}/getUpdates",
                json={"timeout": 10, "offset": offset},
                timeout=15,
            )
            if not r.ok:
                time.sleep(POLL_INTERVAL)
                continue

            for update in r.json().get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                text = msg.get("text", "")
                user = msg.get("from", {})
                new_chat_id = msg.get("chat", {}).get("id")

                if new_chat_id and not chat_id:
                    chat_id = new_chat_id
                    conn = sqlite3.connect(DB_PATH)
                    conn.execute(
                        "INSERT OR REPLACE INTO config (key, value) VALUES ('tg_chat_id', ?)",
                        (str(chat_id),)
                    )
                    conn.commit()
                    conn.close()

                if text == "/start":
                    send_telegram(token, chat_id, "Injector connected. Your messages will be typed into Claude's terminal.")
                    continue

                if not text:
                    continue

                sender = user.get("first_name", "?")
                log.info(f"[{sender}] {text}")

                # Format the message for Claude
                inject_text = f'[Telegram from {sender}]: {text}'

                # Find and inject
                hwnd, title = find_claude_window()
                if hwnd:
                    success = type_into_window(hwnd, inject_text)
                    if success:
                        log.info(f"Injected into: {title}")
                        send_telegram(token, chat_id, "[typed into Claude's terminal]")
                    else:
                        log.warning("Injection failed")
                        send_telegram(token, chat_id, "[could not reach Claude's window]")
                else:
                    log.warning("No Claude window found")
                    send_telegram(token, chat_id, "[no Claude session found - start 'claude' in a terminal]")

        except Exception as e:
            log.error(f"Error: {e}")
            time.sleep(5)

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
