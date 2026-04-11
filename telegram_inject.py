"""Telegram-to-Claude Injector — Types Telegram messages into any console window.

Run as daemon:  pythonw telegram_inject.py          (background)
Debug mode:     python telegram_inject.py --debug   (foreground with logging)

Uses PostMessage WM_CHAR to inject text directly into a target window
by its handle (hwnd). No focus change, no clipboard, no blue box.

Target window hwnd is read from claude_hwnd.txt (set via the GUI picker
or /tg-pin command). Auto-falls back to scanning for Claude windows.
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
import argparse

user32 = ctypes.windll.user32

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "rickshaw.db")
HWND_FILE = os.path.join(SCRIPT_DIR, "claude_hwnd.txt")
LOG_FILE = os.path.join(SCRIPT_DIR, "inject.log")
PID_FILE = os.path.join(SCRIPT_DIR, "inject.pid")
POLL_INTERVAL = 3

log = logging.getLogger("inject")


def setup_logging(debug=False):
    handlers = [logging.FileHandler(LOG_FILE, encoding="utf-8")]
    if debug:
        handlers.append(logging.StreamHandler(sys.stderr))
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s %(message)s",
        handlers=handlers,
    )


# ── Config ───────────────────────────────────────────────────────────

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


# ── Window Management ────────────────────────────────────────────────

def get_pinned_hwnd():
    """Read pinned hwnd from file."""
    if os.path.exists(HWND_FILE):
        try:
            with open(HWND_FILE, "r") as f:
                hwnd = int(f.read().strip())
            if user32.IsWindow(hwnd):
                return hwnd
        except Exception:
            pass
    return None


def save_pinned_hwnd(hwnd):
    with open(HWND_FILE, "w") as f:
        f.write(str(hwnd))


def find_console_windows():
    """Find all visible console windows. Returns [(hwnd, pid, title), ...]."""
    results = []

    def enum_cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            class_buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_buf, 256)
            if class_buf.value in ("ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS"):
                length = user32.GetWindowTextLengthW(hwnd) + 1
                buf = ctypes.create_unicode_buffer(length)
                user32.GetWindowTextW(hwnd, buf, length)
                pid = ctypes.wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                results.append((hwnd, pid.value, buf.value))
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
    )
    user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
    return results


def find_claude_window():
    """Find the best Claude window. Prefers pinned, then scans."""
    pinned = get_pinned_hwnd()
    if pinned:
        return pinned

    windows = find_console_windows()
    # Prefer windows with "Claude" in title
    for hwnd, pid, title in windows:
        if "Claude" in title or "claude" in title:
            return hwnd
    return None


def get_window_title(hwnd):
    if not user32.IsWindow(hwnd):
        return "(dead)"
    length = user32.GetWindowTextLengthW(hwnd) + 1
    buf = ctypes.create_unicode_buffer(length)
    user32.GetWindowTextW(hwnd, buf, length)
    return buf.value


# ── Injection ────────────────────────────────────────────────────────

def inject_text(hwnd, text):
    """Send text + Enter to a window via PostMessage WM_CHAR."""
    WM_CHAR = 0x0102

    if not user32.IsWindow(hwnd):
        return False

    for ch in text:
        user32.PostMessageW(hwnd, WM_CHAR, ord(ch), 0)

    # Enter
    user32.PostMessageW(hwnd, WM_CHAR, 13, 0)
    return True


# ── Main Loop ────────────────────────────────────────────────────────

def run_daemon(debug=False):
    setup_logging(debug)
    token, chat_id = load_config()

    if not token:
        log.error("No bot token in rickshaw.db")
        sys.exit(1)

    # Write PID file
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    hwnd = find_claude_window()
    if hwnd:
        log.info(f"Target: hwnd={hwnd} title=\"{get_window_title(hwnd)}\"")
    else:
        log.info("No target window found yet. Will scan when messages arrive.")

    log.info(f"Injector started (pid={os.getpid()}, chat_id={chat_id})")
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
                    send_telegram(token, chat_id, "Injector online. Messages will be typed into Claude's terminal.")
                    continue

                if text == "/status":
                    h = find_claude_window()
                    title = get_window_title(h) if h else "none"
                    send_telegram(token, chat_id, f"Target: hwnd={h} \"{title}\"")
                    continue

                if text == "/windows":
                    windows = find_console_windows()
                    lines = ["Console windows:"]
                    pinned = get_pinned_hwnd()
                    for h, p, t in windows:
                        tag = " [TARGET]" if h == pinned else ""
                        lines.append(f"  {h}: {t}{tag}")
                    send_telegram(token, chat_id, "\n".join(lines) if windows else "No console windows found.")
                    continue

                if text and text.startswith("/pin "):
                    try:
                        new_hwnd = int(text.split()[1])
                        if user32.IsWindow(new_hwnd):
                            save_pinned_hwnd(new_hwnd)
                            hwnd = new_hwnd
                            send_telegram(token, chat_id, f"Pinned to hwnd={new_hwnd} \"{get_window_title(new_hwnd)}\"")
                        else:
                            send_telegram(token, chat_id, f"Window {new_hwnd} not found.")
                    except Exception:
                        send_telegram(token, chat_id, "Usage: /pin <hwnd>")
                    continue

                if not text or text.startswith("/"):
                    continue

                sender = user.get("first_name", "?")
                log.info(f"[{sender}] {text}")

                # Re-check hwnd in case window changed
                hwnd = find_claude_window()
                if not hwnd:
                    log.warning("No target window")
                    send_telegram(token, chat_id, "No Claude window found. Use /windows to list, /pin <hwnd> to target.")
                    continue

                inject_msg = f"[Telegram from {sender}]: {text}"
                if inject_text(hwnd, inject_msg):
                    log.info(f"Injected into hwnd={hwnd}")
                else:
                    log.warning(f"Injection failed for hwnd={hwnd}")
                    send_telegram(token, chat_id, "Injection failed. Window may have closed.")

        except Exception as e:
            log.error(f"Error: {e}")
            time.sleep(5)

        time.sleep(POLL_INTERVAL)


# ── CLI ──────────────────────────────────────────────────────────────

def cmd_status():
    """Show injector status."""
    pid = None
    if os.path.exists(PID_FILE):
        with open(PID_FILE) as f:
            pid = f.read().strip()

    running = False
    if pid:
        try:
            os.kill(int(pid), 0)
            running = True
        except (OSError, ValueError):
            pass

    hwnd = get_pinned_hwnd()
    title = get_window_title(hwnd) if hwnd else "none"

    print(f"Injector:  {'RUNNING (pid={})'.format(pid) if running else 'STOPPED'}")
    print(f"Target:    hwnd={hwnd} \"{title}\"")
    print(f"PID file:  {PID_FILE}")
    print(f"HWND file: {HWND_FILE}")


def cmd_windows():
    """List all console windows."""
    windows = find_console_windows()
    pinned = get_pinned_hwnd()
    for hwnd, pid, title in windows:
        tag = " <-- TARGET" if hwnd == pinned else ""
        print(f"  hwnd={hwnd:>10}  pid={pid:>6}  {title}{tag}")


def cmd_pin(hwnd_str):
    """Pin a specific window handle."""
    hwnd = int(hwnd_str)
    if user32.IsWindow(hwnd):
        save_pinned_hwnd(hwnd)
        print(f"Pinned hwnd={hwnd} \"{get_window_title(hwnd)}\"")
    else:
        print(f"Window {hwnd} not found.")


def cmd_stop():
    """Stop the running injector."""
    if os.path.exists(PID_FILE):
        with open(PID_FILE) as f:
            pid = f.read().strip()
        try:
            os.kill(int(pid), 9)
            print(f"Killed pid={pid}")
        except Exception:
            print(f"Could not kill pid={pid}")
        os.remove(PID_FILE)
    else:
        print("No PID file found.")


def cmd_test(text="test injection 1234"):
    """Send a test message to the pinned window."""
    hwnd = find_claude_window()
    if not hwnd:
        print("No target window. Use: python telegram_inject.py pin <hwnd>")
        return
    msg = f"[Telegram test]: {text}"
    ok = inject_text(hwnd, msg)
    print(f"{'OK' if ok else 'FAILED'} -> hwnd={hwnd} \"{get_window_title(hwnd)}\"")


def main():
    parser = argparse.ArgumentParser(description="Telegram-to-Claude Injector")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("start", help="Start daemon (use pythonw for background)")
    sub.add_parser("status", help="Show injector status")
    sub.add_parser("windows", help="List console windows")
    sub.add_parser("stop", help="Stop running injector")

    pin_parser = sub.add_parser("pin", help="Pin target window")
    pin_parser.add_argument("hwnd", help="Window handle to target")

    test_parser = sub.add_parser("test", help="Send test injection")
    test_parser.add_argument("text", nargs="*", default=["test", "injection", "1234"])

    parser.add_argument("--debug", action="store_true", help="Verbose logging")

    args = parser.parse_args()

    if args.command == "status":
        cmd_status()
    elif args.command == "windows":
        cmd_windows()
    elif args.command == "pin":
        cmd_pin(args.hwnd)
    elif args.command == "stop":
        cmd_stop()
    elif args.command == "test":
        cmd_test(" ".join(args.text))
    elif args.command == "start" or args.command is None:
        run_daemon(debug=args.debug)


if __name__ == "__main__":
    main()
