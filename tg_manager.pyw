"""Telegram Bridge Manager — System tray GUI for managing the injector.

Features:
  - Window picker: see all console windows, click to pin target
  - Start/stop injector daemon
  - Status indicator in system tray
  - Test injection button

Run: pythonw tg_manager.pyw
"""
import ctypes
import ctypes.wintypes
import os
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, messagebox

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
HWND_FILE = os.path.join(SCRIPT_DIR, "claude_hwnd.txt")
PID_FILE = os.path.join(SCRIPT_DIR, "inject.pid")
INJECT_SCRIPT = os.path.join(SCRIPT_DIR, "telegram_inject.py")
DB_PATH = os.path.join(SCRIPT_DIR, "rickshaw.db")

user32 = ctypes.windll.user32


def find_console_windows():
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
                results.append((hwnd, pid.value, buf.value, class_buf.value))
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
    )
    user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
    return results


def get_pinned_hwnd():
    if os.path.exists(HWND_FILE):
        try:
            with open(HWND_FILE) as f:
                return int(f.read().strip())
        except Exception:
            pass
    return None


def save_pinned_hwnd(hwnd):
    with open(HWND_FILE, "w") as f:
        f.write(str(hwnd))


def is_injector_running():
    if not os.path.exists(PID_FILE):
        return False, None
    try:
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return True, pid
    except (OSError, ValueError):
        return False, None


def inject_test(hwnd):
    WM_CHAR = 0x0102
    text = "[Telegram test]: hello from the manager GUI"
    for ch in text:
        user32.PostMessageW(hwnd, WM_CHAR, ord(ch), 0)
    user32.PostMessageW(hwnd, WM_CHAR, 13, 0)


class TelegramManager(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Telegram Bridge Manager")
        self.geometry("600x450")
        self.configure(bg="#1e1e2e")
        self.resizable(False, False)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#1e1e2e")
        style.configure("TLabel", background="#1e1e2e", foreground="#cdd6f4", font=("Consolas", 10))
        style.configure("Header.TLabel", font=("Consolas", 14, "bold"), foreground="#89b4fa")
        style.configure("Status.TLabel", font=("Consolas", 10))
        style.configure("TButton", font=("Consolas", 10))
        style.configure("Treeview", background="#313244", foreground="#cdd6f4",
                         fieldbackground="#313244", font=("Consolas", 9))
        style.configure("Treeview.Heading", font=("Consolas", 10, "bold"),
                         background="#45475a", foreground="#cdd6f4")

        # Header
        header_frame = ttk.Frame(self)
        header_frame.pack(fill="x", padx=15, pady=(15, 5))
        ttk.Label(header_frame, text="Telegram Bridge Manager", style="Header.TLabel").pack(side="left")

        # Status bar
        status_frame = ttk.Frame(self)
        status_frame.pack(fill="x", padx=15, pady=5)

        self.status_label = ttk.Label(status_frame, text="", style="Status.TLabel")
        self.status_label.pack(side="left")

        self.target_label = ttk.Label(status_frame, text="", style="Status.TLabel")
        self.target_label.pack(side="right")

        # Window list
        list_frame = ttk.Frame(self)
        list_frame.pack(fill="both", expand=True, padx=15, pady=5)

        ttk.Label(list_frame, text="Console Windows (click to pin target):").pack(anchor="w")

        self.tree = ttk.Treeview(list_frame, columns=("hwnd", "pid", "title"), show="headings", height=10)
        self.tree.heading("hwnd", text="HWND")
        self.tree.heading("pid", text="PID")
        self.tree.heading("title", text="Title")
        self.tree.column("hwnd", width=100)
        self.tree.column("pid", width=70)
        self.tree.column("title", width=400)
        self.tree.pack(fill="both", expand=True, pady=5)
        self.tree.bind("<Double-1>", self.on_pin_selected)

        # Buttons
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", padx=15, pady=(5, 15))

        ttk.Button(btn_frame, text="Refresh", command=self.refresh).pack(side="left", padx=3)
        ttk.Button(btn_frame, text="Pin Selected", command=self.pin_selected).pack(side="left", padx=3)
        ttk.Button(btn_frame, text="Test Inject", command=self.test_inject).pack(side="left", padx=3)

        self.start_btn = ttk.Button(btn_frame, text="Start Daemon", command=self.start_daemon)
        self.start_btn.pack(side="right", padx=3)

        self.stop_btn = ttk.Button(btn_frame, text="Stop Daemon", command=self.stop_daemon)
        self.stop_btn.pack(side="right", padx=3)

        self.refresh()
        self.auto_refresh()

    def refresh(self):
        # Update window list
        self.tree.delete(*self.tree.get_children())
        pinned = get_pinned_hwnd()
        windows = find_console_windows()

        for hwnd, pid, title, cls in windows:
            tag = "pinned" if hwnd == pinned else ""
            display_title = title[:60]
            self.tree.insert("", "end", values=(hwnd, pid, display_title), tags=(tag,))

        self.tree.tag_configure("pinned", background="#45475a", foreground="#a6e3a1")

        # Update status
        running, pid = is_injector_running()
        if running:
            self.status_label.config(text=f"Daemon: RUNNING (pid={pid})", foreground="#a6e3a1")
            self.start_btn.config(state="disabled")
            self.stop_btn.config(state="normal")
        else:
            self.status_label.config(text="Daemon: STOPPED", foreground="#f38ba8")
            self.start_btn.config(state="normal")
            self.stop_btn.config(state="disabled")

        if pinned and user32.IsWindow(pinned):
            length = user32.GetWindowTextLengthW(pinned) + 1
            buf = ctypes.create_unicode_buffer(length)
            user32.GetWindowTextW(pinned, buf, length)
            self.target_label.config(text=f"Target: {pinned} ({buf.value[:30]})", foreground="#89b4fa")
        else:
            self.target_label.config(text="Target: none", foreground="#f38ba8")

    def auto_refresh(self):
        self.refresh()
        self.after(5000, self.auto_refresh)

    def pin_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        hwnd = int(self.tree.item(sel[0])["values"][0])
        save_pinned_hwnd(hwnd)
        self.refresh()

    def on_pin_selected(self, event):
        self.pin_selected()

    def test_inject(self):
        hwnd = get_pinned_hwnd()
        if not hwnd or not user32.IsWindow(hwnd):
            messagebox.showwarning("No Target", "Pin a window first.")
            return
        inject_test(hwnd)

    def start_daemon(self):
        python = sys.executable.replace("python.exe", "pythonw.exe")
        subprocess.Popen(
            [python, INJECT_SCRIPT],
            cwd=SCRIPT_DIR,
            creationflags=0x00000008,  # DETACHED_PROCESS
        )
        self.after(2000, self.refresh)

    def stop_daemon(self):
        running, pid = is_injector_running()
        if running and pid:
            try:
                os.kill(pid, 9)
            except Exception:
                pass
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
        self.after(1000, self.refresh)


if __name__ == "__main__":
    app = TelegramManager()
    app.mainloop()
