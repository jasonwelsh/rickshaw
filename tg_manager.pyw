"""Telegram Bridge Manager — GUI to manage bot + window targeting + daemon."""
import ctypes
import ctypes.wintypes
import json
import os
import sqlite3
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox, simpledialog

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "rickshaw.db")
HWND_FILE = os.path.join(SCRIPT_DIR, "claude_hwnd.txt")
PID_FILE = os.path.join(SCRIPT_DIR, "inject.pid")
INJECT_SCRIPT = os.path.join(SCRIPT_DIR, "telegram_inject.py")
PYTHONW = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")

user32 = ctypes.windll.user32
SI = subprocess.STARTUPINFO()
SI.dwFlags |= subprocess.STARTF_USESHOWWINDOW
SI.wShowWindow = 0


# ── Helpers ──────────────────────────────────────────────────────────

def find_console_windows():
    results = []
    def enum_cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            cb = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cb, 256)
            if cb.value in ("ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS"):
                l = user32.GetWindowTextLengthW(hwnd) + 1
                b = ctypes.create_unicode_buffer(l)
                user32.GetWindowTextW(hwnd, b, l)
                p = ctypes.wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
                results.append((hwnd, p.value, b.value))
        return True
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
    return results


def get_pinned():
    if os.path.exists(HWND_FILE):
        try:
            with open(HWND_FILE) as f:
                return int(f.read().strip())
        except Exception:
            pass
    return None


def save_pinned(hwnd):
    with open(HWND_FILE, "w") as f:
        f.write(str(hwnd))


def get_window_title(hwnd):
    if not hwnd or not user32.IsWindow(hwnd):
        return ""
    l = user32.GetWindowTextLengthW(hwnd) + 1
    b = ctypes.create_unicode_buffer(l)
    user32.GetWindowTextW(hwnd, b, l)
    return b.value


def is_daemon_running():
    if not os.path.exists(PID_FILE):
        return False, None
    try:
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                           capture_output=True, text=True, timeout=5, startupinfo=SI)
        if str(pid) in r.stdout:
            return True, pid
        return False, None
    except Exception:
        return False, None


def db_get(key, default=None):
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
        conn.close()
        return row[0] if row else default
    except Exception:
        return default


def db_set(key, value):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, str(value)))
        conn.commit()
        conn.close()
    except Exception:
        pass


# ── App ──────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Telegram Bridge Manager")
        self.geometry("560x480")
        self.minsize(500, 400)

        # ── Bot Config Section ───────────────────────────────────
        bot_frame = tk.LabelFrame(self, text="Bot Configuration", font=("Arial", 11, "bold"),
                                  padx=10, pady=5)
        bot_frame.pack(fill="x", padx=10, pady=(10, 5))

        row1 = tk.Frame(bot_frame)
        row1.pack(fill="x", pady=2)
        tk.Label(row1, text="Bot:", font=("Arial", 10), width=6, anchor="w").pack(side="left")
        self.bot_lbl = tk.Label(row1, text="loading...", font=("Consolas", 10), fg="blue")
        self.bot_lbl.pack(side="left", fill="x", expand=True)
        tk.Button(row1, text="Change Bot", font=("Arial", 9), command=self.change_bot).pack(side="right")

        row2 = tk.Frame(bot_frame)
        row2.pack(fill="x", pady=2)
        tk.Label(row2, text="Chat:", font=("Arial", 10), width=6, anchor="w").pack(side="left")
        self.chat_lbl = tk.Label(row2, text="", font=("Consolas", 10))
        self.chat_lbl.pack(side="left")

        # ── Status Section ───────────────────────────────────────
        status_frame = tk.LabelFrame(self, text="Status", font=("Arial", 11, "bold"),
                                     padx=10, pady=5)
        status_frame.pack(fill="x", padx=10, pady=5)

        self.daemon_lbl = tk.Label(status_frame, text="Daemon: ...", font=("Arial", 11))
        self.daemon_lbl.pack(anchor="w")

        self.target_lbl = tk.Label(status_frame, text="Target: ...", font=("Arial", 11))
        self.target_lbl.pack(anchor="w")

        # Buttons
        btn_frame = tk.Frame(status_frame, pady=5)
        btn_frame.pack(fill="x")

        self.start_btn = tk.Button(btn_frame, text="Start Daemon", font=("Arial", 10),
                                   width=13, command=self.start_daemon, bg="#c0ffc0")
        self.start_btn.pack(side="left", padx=3)

        self.stop_btn = tk.Button(btn_frame, text="Stop Daemon", font=("Arial", 10),
                                  width=13, command=self.stop_daemon, bg="#ffc0c0")
        self.stop_btn.pack(side="left", padx=3)

        tk.Button(btn_frame, text="Test Inject", font=("Arial", 10),
                  width=10, command=self.test_inject).pack(side="left", padx=3)

        tk.Button(btn_frame, text="Refresh", font=("Arial", 10),
                  width=8, command=self.refresh).pack(side="right", padx=3)

        # ── Window Picker Section ────────────────────────────────
        win_frame = tk.LabelFrame(self, text="Target Window (double-click to pin)",
                                  font=("Arial", 11, "bold"), padx=10, pady=5)
        win_frame.pack(fill="both", expand=True, padx=10, pady=(5, 10))

        self.listbox = tk.Listbox(win_frame, font=("Consolas", 10), selectmode="single")
        self.listbox.pack(fill="both", expand=True, pady=5)
        self.listbox.bind("<Double-Button-1>", lambda e: self.pin_selected())

        self.window_data = []
        self.refresh()
        self.auto_refresh()

    def refresh(self):
        # Bot info
        token = db_get("tg_bot_token")
        chat_id = db_get("tg_chat_id")

        if token:
            masked = f"...{token[-8:]}"
            # Try to get bot username from a cached value or show token
            bot_name = db_get("tg_bot_name", masked)
            self.bot_lbl.config(text=bot_name, fg="blue")
        else:
            self.bot_lbl.config(text="Not configured", fg="red")

        self.chat_lbl.config(text=f"Chat ID: {chat_id}" if chat_id else "No chat ID (send /start to bot)")

        # Daemon status
        running, pid = is_daemon_running()
        if running:
            self.daemon_lbl.config(text=f"Daemon: RUNNING (pid={pid})", fg="green")
            self.start_btn.config(state="disabled")
            self.stop_btn.config(state="normal")
        else:
            self.daemon_lbl.config(text="Daemon: STOPPED", fg="red")
            self.start_btn.config(state="normal")
            self.stop_btn.config(state="disabled")

        # Target window
        pinned = get_pinned()
        if pinned and user32.IsWindow(pinned):
            title = get_window_title(pinned)
            self.target_lbl.config(text=f"Target: {pinned} - {title[:45]}", fg="blue")
        else:
            self.target_lbl.config(text="Target: none (pick a window below)", fg="red")

        # Window list
        self.listbox.delete(0, "end")
        self.window_data = find_console_windows()

        for hwnd, pid, title in self.window_data:
            is_target = hwnd == pinned
            tag = "  <<< TARGET" if is_target else ""
            display = f"  {hwnd}  |  {title[:45]}{tag}"
            self.listbox.insert("end", display)
            if is_target:
                self.listbox.itemconfig("end", bg="#d0ffd0")

    def auto_refresh(self):
        self.refresh()
        self.after(5000, self.auto_refresh)

    def pin_selected(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        hwnd = self.window_data[sel[0]][0]
        save_pinned(hwnd)
        self.refresh()

    def change_bot(self):
        token = simpledialog.askstring("Bot Token",
                                       "Paste bot token from @BotFather:",
                                       parent=self)
        if not token or not token.strip():
            return
        token = token.strip()

        # Verify token
        try:
            import requests
            r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=5)
            if r.ok:
                bot_name = f"@{r.json()['result']['username']}"
                db_set("tg_bot_token", token)
                db_set("tg_bot_name", bot_name)
                messagebox.showinfo("Bot Updated", f"Connected to {bot_name}")
                self.refresh()
            else:
                messagebox.showerror("Invalid Token", "Telegram rejected the token.")
        except Exception as e:
            messagebox.showerror("Error", f"Could not verify token:\n{e}")

    def start_daemon(self):
        if not db_get("tg_bot_token"):
            messagebox.showwarning("No Bot", "Configure a bot token first.")
            return
        if not get_pinned():
            messagebox.showwarning("No Target", "Pin a target window first.")
            return
        subprocess.Popen(
            [PYTHONW, INJECT_SCRIPT],
            cwd=SCRIPT_DIR,
            creationflags=0x00000008,
        )
        self.after(2000, self.refresh)

    def stop_daemon(self):
        running, pid = is_daemon_running()
        if running and pid:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True, timeout=5, startupinfo=SI)
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
        self.after(1000, self.refresh)

    def test_inject(self):
        hwnd = get_pinned()
        if not hwnd or not user32.IsWindow(hwnd):
            messagebox.showwarning("No Target", "Pin a window first.")
            return
        WM_CHAR = 0x0102
        text = "[Telegram test]: hello from the bridge manager"
        for ch in text:
            user32.PostMessageW(hwnd, WM_CHAR, ord(ch), 0)
        user32.PostMessageW(hwnd, WM_CHAR, 13, 0)


if __name__ == "__main__":
    # Cache bot username on launch
    token = db_get("tg_bot_token")
    if token and not db_get("tg_bot_name"):
        try:
            import requests
            r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=5)
            if r.ok:
                db_set("tg_bot_name", f"@{r.json()['result']['username']}")
        except Exception:
            pass

    App().mainloop()
