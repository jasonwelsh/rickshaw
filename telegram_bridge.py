"""Telegram-to-PowerShell Bridge — Injects Telegram messages into Claude Code's console.

Run this alongside any Claude Code session:
    pythonw telegram_bridge.py          (silent, no window)
    python telegram_bridge.py           (with console for debugging)
    python telegram_bridge.py --debug   (verbose logging)

When a Telegram message arrives at @powershell_claude_bot:
1. Finds the PowerShell/Terminal window running Claude Code
2. Injects "check_telegram" or the raw message as keystrokes
3. Claude reads it as normal user input and responds

The bridge does NOT process messages itself — it just types them into Claude's prompt.
"""
import ctypes
import ctypes.wintypes
import json
import os
import re
import sqlite3
import sys
import time
import threading
import logging
import requests
import argparse

# Win32 constants
PROCESS_ALL_ACCESS = 0x1F0FFF
INPUT_RECORD_SIZE = ctypes.sizeof(ctypes.wintypes.DWORD) * 4 + ctypes.sizeof(ctypes.wintypes.WORD) * 4
KEY_EVENT = 0x0001
ATTACH_PARENT_PROCESS = 0xFFFFFFFF

kernel32 = ctypes.windll.kernel32
user32 = ctypes.windll.user32

# ── Win32 Structures ─────────────────────────────────────────────────

class KEY_EVENT_RECORD(ctypes.Structure):
    _fields_ = [
        ("bKeyDown", ctypes.wintypes.BOOL),
        ("wRepeatCount", ctypes.wintypes.WORD),
        ("wVirtualKeyCode", ctypes.wintypes.WORD),
        ("wVirtualScanCode", ctypes.wintypes.WORD),
        ("UnicodeChar", ctypes.c_wchar),
        ("dwControlKeyState", ctypes.wintypes.DWORD),
    ]

class INPUT_RECORD_UNION(ctypes.Union):
    _fields_ = [
        ("KeyEvent", KEY_EVENT_RECORD),
    ]

class INPUT_RECORD(ctypes.Structure):
    _fields_ = [
        ("EventType", ctypes.wintypes.WORD),
        ("Event", INPUT_RECORD_UNION),
    ]


# ── Config ───────────────────────────────────────────────────────────

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rickshaw.db")
POLL_INTERVAL = 3
INJECT_PREFIX = "/telegram: "  # Prefix so Claude knows it came from Telegram
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bridge.log")


def setup_logging(debug=False):
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
    )

log = logging.getLogger("bridge")


# ── Console Injection ────────────────────────────────────────────────

def find_claude_console():
    """Find the console window running Claude Code (ConsoleWindowClass only)."""
    results = []

    def enum_callback(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            # Check window class — only target real consoles
            class_buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_buf, 256)
            win_class = class_buf.value

            # Only target console/terminal windows, NOT Notepad/editors
            if win_class not in ("ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS"):
                return True

            length = user32.GetWindowTextLengthW(hwnd) + 1
            buf = ctypes.create_unicode_buffer(length)
            user32.GetWindowTextW(hwnd, buf, length)
            title = buf.value.lower()
            if any(kw in title for kw in ["claude", "powershell", "terminal", "cmd"]):
                results.append((hwnd, buf.value))
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(enum_callback), 0)
    return results


def get_console_pid(hwnd):
    """Get the process ID of a window."""
    pid = ctypes.wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def inject_text_to_console(text):
    """Write text to the current console's input buffer using WriteConsoleInput."""
    STD_INPUT_HANDLE = -10
    h_stdin = kernel32.GetStdHandle(STD_INPUT_HANDLE)

    # Build input records for each character + Enter
    full_text = text + "\r"
    records = (INPUT_RECORD * len(full_text))()

    for i, char in enumerate(full_text):
        records[i].EventType = KEY_EVENT
        records[i].Event.KeyEvent.bKeyDown = True
        records[i].Event.KeyEvent.wRepeatCount = 1
        records[i].Event.KeyEvent.wVirtualKeyCode = 0
        records[i].Event.KeyEvent.wVirtualScanCode = 0
        records[i].Event.KeyEvent.UnicodeChar = char
        records[i].Event.KeyEvent.dwControlKeyState = 0

    written = ctypes.wintypes.DWORD()
    result = kernel32.WriteConsoleInputW(
        h_stdin,
        records,
        len(full_text),
        ctypes.byref(written),
    )
    return result != 0 and written.value == len(full_text)


def inject_to_target_console(target_pid, text):
    """Attach to another process's console and inject text."""
    # If we're already in the same console (child process), try direct write
    # This happens when running from the same terminal as Claude
    try:
        kernel32.FreeConsole()
    except Exception:
        pass

    attached = kernel32.AttachConsole(target_pid)
    if not attached:
        # Try re-attaching to parent
        kernel32.AttachConsole(ATTACH_PARENT_PROCESS)
        return False

    success = inject_text_to_console(text)

    kernel32.FreeConsole()
    # Re-attach to own console (may fail if we're pythonw, that's ok)
    kernel32.AllocConsole()

    return success


def inject_via_sendmessage(hwnd, text):
    """Fallback: Send text via WM_CHAR messages to a window."""
    WM_CHAR = 0x0102
    VK_RETURN = 0x0D

    for char in text:
        user32.SendMessageW(hwnd, WM_CHAR, ord(char), 0)
    # Send Enter
    user32.SendMessageW(hwnd, WM_CHAR, VK_RETURN, 0)
    return True


# ── Telegram Poller ──────────────────────────────────────────────────

class TelegramWatcher:
    def __init__(self, db_path):
        self.db_path = db_path
        self.token = None
        self.chat_id = None
        self.allowed_users = []
        self._offset = 0
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
        except Exception as e:
            log.error(f"Config load error: {e}")

    def poll(self):
        """Poll for new messages. Returns list of message texts."""
        if not self.token:
            return []
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{self.token}/getUpdates",
                json={"timeout": 10, "offset": self._offset},
                timeout=15,
            )
            if not r.ok:
                return []

            messages = []
            for update in r.json().get("result", []):
                self._offset = update["update_id"] + 1
                msg = update.get("message", {})
                text = msg.get("text", "")
                user = msg.get("from", {})
                chat_id = msg.get("chat", {}).get("id")

                # Auto-save chat_id
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

                if text and not text.startswith("/"):
                    messages.append({
                        "from": user.get("first_name", "?"),
                        "username": f"@{user.get('username', '?')}",
                        "text": text,
                    })
                elif text == "/start":
                    self.send("Bridge connected. Send any message and it will appear in Claude's terminal.")

            return messages
        except Exception as e:
            log.error(f"Poll error: {e}")
            return []

    def send(self, text):
        if not self.token or not self.chat_id:
            return False
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": self.chat_id, "text": text[:4096]},
                timeout=10,
            )
            return r.ok
        except Exception:
            return False


# ── Main Loop ────────────────────────────────────────────────────────

def find_claude_target():
    """Find the best console window to inject into."""
    windows = find_claude_console()
    # Prefer windows with "claude" in title
    for hwnd, title in windows:
        if "claude" in title.lower():
            return hwnd, title, get_console_pid(hwnd)
    # Fall back to any terminal
    for hwnd, title in windows:
        if any(kw in title.lower() for kw in ["terminal", "powershell"]):
            return hwnd, title, get_console_pid(hwnd)
    return None, None, None


def main():
    parser = argparse.ArgumentParser(description="Telegram-to-PowerShell Bridge")
    parser.add_argument("--debug", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    setup_logging(args.debug)
    log.info("Telegram bridge starting...")

    watcher = TelegramWatcher(DB_PATH)
    if not watcher.token:
        log.error("No bot token in rickshaw.db. Run Rickshaw /tg-setup first.")
        sys.exit(1)

    log.info(f"Bot token loaded. Chat ID: {watcher.chat_id}")
    log.info("Polling for Telegram messages...")

    consecutive_empty = 0

    while True:
        messages = watcher.poll()

        if not messages:
            consecutive_empty += 1
            time.sleep(POLL_INTERVAL)
            continue

        consecutive_empty = 0

        for msg in messages:
            text = msg["text"].strip()
            sender = msg["from"]
            log.info(f"Telegram [{sender}]: {text}")

            # Build the injection text
            # Tell Claude to check telegram and respond
            inject = f'check telegram and respond to the message from {sender}: "{text}"'

            # Try to find and inject into Claude's console
            hwnd, title, pid = find_claude_target()

            if hwnd:
                log.info(f"Injecting into: {title} (PID {pid})")
                # Try console injection first
                success = inject_to_target_console(pid, inject)
                if not success:
                    log.warning("Console injection failed, trying SendMessage...")
                    success = inject_via_sendmessage(hwnd, inject)

                if success:
                    log.info("Injected successfully")
                    watcher.send(f"[bridge] Message forwarded to Claude.")
                else:
                    log.error("All injection methods failed")
                    watcher.send(f"[bridge] Could not reach Claude's terminal. Is it running?")
            else:
                log.warning("No Claude/PowerShell window found")
                watcher.send(f"[bridge] No Claude session found. Start 'claude' in a terminal first.")

            time.sleep(1)  # Small delay between injections


if __name__ == "__main__":
    main()
