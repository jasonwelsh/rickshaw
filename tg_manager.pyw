"""Telegram Bridge Manager — Simple GUI to manage the injector daemon."""
import ctypes
import ctypes.wintypes
import os
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
HWND_FILE = os.path.join(SCRIPT_DIR, "claude_hwnd.txt")
PID_FILE = os.path.join(SCRIPT_DIR, "inject.pid")
INJECT_SCRIPT = os.path.join(SCRIPT_DIR, "telegram_inject.py")
PYTHONW = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")

user32 = ctypes.windll.user32


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


def is_running():
    if not os.path.exists(PID_FILE):
        return False, None
    try:
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                           capture_output=True, text=True, timeout=5,
                           startupinfo=si)
        if str(pid) in r.stdout:
            return True, pid
        return False, None
    except Exception:
        return False, None


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Telegram Bridge")
        self.geometry("500x400")

        # Status frame
        sf = tk.Frame(self, pady=10, padx=10)
        sf.pack(fill="x")

        self.daemon_lbl = tk.Label(sf, text="Daemon: checking...", font=("Arial", 12))
        self.daemon_lbl.pack(anchor="w")

        self.target_lbl = tk.Label(sf, text="Target: none", font=("Arial", 12))
        self.target_lbl.pack(anchor="w")

        # Buttons
        bf = tk.Frame(self, padx=10)
        bf.pack(fill="x")

        tk.Button(bf, text="Start Daemon", font=("Arial", 11), width=14,
                  command=self.start).pack(side="left", padx=3)
        tk.Button(bf, text="Stop Daemon", font=("Arial", 11), width=14,
                  command=self.stop).pack(side="left", padx=3)
        tk.Button(bf, text="Refresh", font=("Arial", 11), width=10,
                  command=self.refresh).pack(side="left", padx=3)
        tk.Button(bf, text="Test", font=("Arial", 11), width=8,
                  command=self.test).pack(side="left", padx=3)

        # Window list
        lf = tk.Frame(self, padx=10, pady=10)
        lf.pack(fill="both", expand=True)

        tk.Label(lf, text="Console Windows (click to pin):", font=("Arial", 11, "bold")).pack(anchor="w")

        self.listbox = tk.Listbox(lf, font=("Consolas", 10), height=12, selectmode="single")
        self.listbox.pack(fill="both", expand=True, pady=5)
        self.listbox.bind("<Double-Button-1>", lambda e: self.pin_selected())

        tk.Button(lf, text="Pin Selected", font=("Arial", 11), command=self.pin_selected).pack()

        self.window_data = []
        self.refresh()
        self.auto_refresh()

    def refresh(self):
        self.listbox.delete(0, "end")
        self.window_data = find_console_windows()
        pinned = get_pinned()

        for hwnd, pid, title in self.window_data:
            tag = " << TARGET" if hwnd == pinned else ""
            display = f"{hwnd}  |  {title[:50]}{tag}"
            self.listbox.insert("end", display)
            if hwnd == pinned:
                self.listbox.itemconfig("end", bg="#d0ffd0")

        running, pid = is_running()
        if running:
            self.daemon_lbl.config(text=f"Daemon: RUNNING (pid={pid})", fg="green")
        else:
            self.daemon_lbl.config(text="Daemon: STOPPED", fg="red")

        if pinned and user32.IsWindow(pinned):
            l = user32.GetWindowTextLengthW(pinned) + 1
            b = ctypes.create_unicode_buffer(l)
            user32.GetWindowTextW(pinned, b, l)
            self.target_lbl.config(text=f"Target: {pinned} - {b.value[:40]}", fg="blue")
        else:
            self.target_lbl.config(text="Target: none (pin a window below)", fg="red")

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

    def start(self):
        subprocess.Popen(
            [PYTHONW, INJECT_SCRIPT],
            cwd=SCRIPT_DIR,
            creationflags=0x00000008,
        )
        self.after(2000, self.refresh)

    def stop(self):
        running, pid = is_running()
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        if running and pid:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True, timeout=5, startupinfo=si)
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
        self.after(1000, self.refresh)

    def test(self):
        hwnd = get_pinned()
        if not hwnd or not user32.IsWindow(hwnd):
            messagebox.showwarning("No Target", "Pin a window first.")
            return
        WM_CHAR = 0x0102
        text = "[Telegram test]: hello from manager"
        for ch in text:
            user32.PostMessageW(hwnd, WM_CHAR, ord(ch), 0)
        user32.PostMessageW(hwnd, WM_CHAR, 13, 0)


if __name__ == "__main__":
    App().mainloop()
