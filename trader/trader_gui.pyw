"""Rickshaw Trader GUI — Dashboard for positions, strategies, engine, and research."""
import json
import os
import subprocess
import sys
import time
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PARENT_DIR)

CONFIG_FILE = os.path.join(SCRIPT_DIR, "trader_config.json")
STRATEGIES_FILE = os.path.join(SCRIPT_DIR, "strategies.json")
ENGINE_PID_FILE = os.path.join(SCRIPT_DIR, "engine.pid")
ENGINE_SCRIPT = os.path.join(SCRIPT_DIR, "engine_runner.py")
PYTHONW = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")

SI = subprocess.STARTUPINFO()
SI.dwFlags |= subprocess.STARTF_USESHOWWINDOW
SI.wShowWindow = 0


def load_trader():
    if not os.path.exists(CONFIG_FILE):
        return None
    with open(CONFIG_FILE) as f:
        cfg = json.load(f)
    from trader.alpaca_client import AlpacaTrader
    return AlpacaTrader(cfg["alpaca_api_key"], cfg["alpaca_secret_key"], paper=cfg.get("paper", True))


def is_engine_running():
    if not os.path.exists(ENGINE_PID_FILE):
        return False, None
    try:
        with open(ENGINE_PID_FILE) as f:
            pid = int(f.read().strip())
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                           capture_output=True, text=True, timeout=5, startupinfo=SI)
        if str(pid) in r.stdout:
            return True, pid
        return False, None
    except Exception:
        return False, None


class TraderApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Rickshaw Trader")
        self.geometry("700x750")
        self.minsize(650, 550)
        self.trader = load_trader()

        # ── Scrollable container ─────────────────────────────────
        outer = tk.Frame(self)
        outer.pack(fill="both", expand=True)

        canvas = tk.Canvas(outer)
        scrollbar = tk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        self.scroll_frame = tk.Frame(canvas)

        self.scroll_frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Mouse wheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # All widgets go into self.scroll_frame instead of self
        sf = self.scroll_frame

        # ── Account Bar ──────────────────────────────────────────
        acct_frame = tk.Frame(sf, pady=5, padx=10)
        acct_frame.pack(fill="x")

        self.acct_lbl = tk.Label(acct_frame, text="Loading...", font=("Arial", 14, "bold"))
        self.acct_lbl.pack(side="left")

        self.pl_lbl = tk.Label(acct_frame, text="", font=("Arial", 14, "bold"))
        self.pl_lbl.pack(side="left", padx=20)

        self.mode_lbl = tk.Label(acct_frame, text="PAPER", font=("Arial", 10), fg="orange")
        self.mode_lbl.pack(side="right")

        # ── Engine Controls ──────────────────────────────────────
        engine_frame = tk.LabelFrame(sf, text="Engine", font=("Arial", 11, "bold"), padx=10, pady=5)
        engine_frame.pack(fill="x", padx=10, pady=3)

        self.engine_lbl = tk.Label(engine_frame, text="...", font=("Arial", 11))
        self.engine_lbl.pack(side="left")

        tk.Button(engine_frame, text="Research", font=("Arial", 10),
                  command=self.run_research).pack(side="right", padx=3)
        tk.Button(engine_frame, text="Refresh", font=("Arial", 10),
                  command=self.refresh).pack(side="right", padx=3)

        self.stop_eng_btn = tk.Button(engine_frame, text="Stop", font=("Arial", 10),
                                      bg="#ffc0c0", command=self.stop_engine)
        self.stop_eng_btn.pack(side="right", padx=3)

        self.start_eng_btn = tk.Button(engine_frame, text="Start", font=("Arial", 10),
                                       bg="#c0ffc0", command=self.start_engine)
        self.start_eng_btn.pack(side="right", padx=3)

        # ── Positions ────────────────────────────────────────────
        pos_frame = tk.LabelFrame(sf, text="Positions", font=("Arial", 11, "bold"), padx=10, pady=5)
        pos_frame.pack(fill="x", padx=10, pady=3)

        cols = ("symbol", "qty", "entry", "current", "pl", "pl_pct")
        self.pos_tree = ttk.Treeview(pos_frame, columns=cols, show="headings", height=6)
        self.pos_tree.heading("symbol", text="Symbol")
        self.pos_tree.heading("qty", text="Qty")
        self.pos_tree.heading("entry", text="Entry")
        self.pos_tree.heading("current", text="Current")
        self.pos_tree.heading("pl", text="P&L")
        self.pos_tree.heading("pl_pct", text="P&L%")

        self.pos_tree.column("symbol", width=70)
        self.pos_tree.column("qty", width=50)
        self.pos_tree.column("entry", width=90)
        self.pos_tree.column("current", width=90)
        self.pos_tree.column("pl", width=90)
        self.pos_tree.column("pl_pct", width=70)
        self.pos_tree.pack(fill="x")

        # ── Strategies ───────────────────────────────────────────
        strat_frame = tk.LabelFrame(sf, text="Strategies", font=("Arial", 11, "bold"), padx=10, pady=5)
        strat_frame.pack(fill="x", padx=10, pady=3)

        strat_cols = ("id", "symbol", "type", "status", "floor", "high")
        self.strat_tree = ttk.Treeview(strat_frame, columns=strat_cols, show="headings", height=6)
        self.strat_tree.heading("id", text="ID")
        self.strat_tree.heading("symbol", text="Symbol")
        self.strat_tree.heading("type", text="Type")
        self.strat_tree.heading("status", text="Status")
        self.strat_tree.heading("floor", text="Floor")
        self.strat_tree.heading("high", text="High")

        self.strat_tree.column("id", width=130)
        self.strat_tree.column("symbol", width=60)
        self.strat_tree.column("type", width=100)
        self.strat_tree.column("status", width=80)
        self.strat_tree.column("floor", width=80)
        self.strat_tree.column("high", width=80)
        self.strat_tree.pack(fill="x")

        strat_btn = tk.Frame(strat_frame, pady=3)
        strat_btn.pack(fill="x")
        tk.Button(strat_btn, text="New Trailing Stop", font=("Arial", 10),
                  command=self.new_trailing_stop).pack(side="left", padx=3)
        tk.Button(strat_btn, text="Cancel Selected", font=("Arial", 10),
                  command=self.cancel_selected_strategy).pack(side="left", padx=3)

        # ── Watchlist ────────────────────────────────────────────
        wl_frame = tk.LabelFrame(sf, text="Watchlist", font=("Arial", 11, "bold"), padx=10, pady=5)
        wl_frame.pack(fill="x", padx=10, pady=3)

        wl_cols = ("symbol", "price", "reason", "added")
        self.wl_tree = ttk.Treeview(wl_frame, columns=wl_cols, show="headings", height=3)
        self.wl_tree.heading("symbol", text="Symbol")
        self.wl_tree.heading("price", text="Price")
        self.wl_tree.heading("reason", text="Reason")
        self.wl_tree.heading("added", text="Added")
        self.wl_tree.column("symbol", width=60)
        self.wl_tree.column("price", width=80)
        self.wl_tree.column("reason", width=350)
        self.wl_tree.column("added", width=80)
        self.wl_tree.pack(fill="x", pady=3)

        wl_btn = tk.Frame(wl_frame)
        wl_btn.pack(fill="x")
        tk.Button(wl_btn, text="Add", font=("Arial", 10), command=self.add_watchlist).pack(side="left", padx=3)
        tk.Button(wl_btn, text="Remove", font=("Arial", 10), command=self.rm_watchlist).pack(side="left", padx=3)
        tk.Button(wl_btn, text="Buy Selected", font=("Arial", 10), command=self.buy_from_watchlist).pack(side="left", padx=3)

        # ── Research Pane (toggle) ───────────────────────────────
        research_toggle = tk.LabelFrame(sf, text="Research", font=("Arial", 11, "bold"), padx=10, pady=5)
        research_toggle.pack(fill="x", padx=10, pady=3)

        self.research_visible = tk.BooleanVar(value=False)
        tk.Checkbutton(research_toggle, text="Show Research", variable=self.research_visible,
                       font=("Arial", 11, "bold"), command=self.toggle_research).pack(side="left")
        tk.Button(research_toggle, text="Force Research Now", font=("Arial", 10),
                  command=self.force_research).pack(side="right", padx=3)
        self.research_brain = tk.StringVar(value="qwen")
        tk.OptionMenu(research_toggle, self.research_brain, "qwen", "opus").pack(side="right", padx=3)
        tk.Label(research_toggle, text="Brain:", font=("Arial", 10)).pack(side="right")

        self.research_frame = tk.LabelFrame(sf, text="Latest Research Report",
                                             font=("Arial", 11, "bold"), padx=10, pady=5)
        self.research_text = tk.Text(self.research_frame, font=("Consolas", 9),
                                     height=10, wrap="word", state="disabled")
        self.research_text.pack(fill="both", expand=True, pady=3)
        # Hidden by default
        self.research_frame.pack_forget()

        self.wl_data = []
        self.refresh()
        self.auto_refresh()

    def refresh(self):
        if not self.trader:
            self.acct_lbl.config(text="Not connected", fg="red")
            return

        try:
            acct = self.trader.get_account()
            portfolio = float(acct["portfolio_value"])
            cash = float(acct["cash"])
            self.acct_lbl.config(text=f"${portfolio:,.0f}", fg="black")

            positions = self.trader.get_positions()
            total_pl = sum(float(p["unrealized_pl"]) for p in positions)
            pl_color = "green" if total_pl >= 0 else "red"
            self.pl_lbl.config(text=f"P&L: ${total_pl:+,.2f}", fg=pl_color)

            # Positions tree
            self.pos_tree.delete(*self.pos_tree.get_children())
            for p in positions:
                pl = float(p["unrealized_pl"])
                plpc = float(p["unrealized_plpc"]) * 100
                tag = "gain" if pl >= 0 else "loss"
                self.pos_tree.insert("", "end", values=(
                    p["symbol"], p["qty"],
                    f"${float(p['avg_entry']):,.2f}",
                    f"${float(p['current_price']):,.2f}",
                    f"${pl:+,.2f}",
                    f"{plpc:+.1f}%",
                ), tags=(tag,))
            self.pos_tree.tag_configure("gain", foreground="green")
            self.pos_tree.tag_configure("loss", foreground="red")

        except Exception as e:
            self.acct_lbl.config(text=f"Error: {e}", fg="red")

        # Strategies
        self.strat_tree.delete(*self.strat_tree.get_children())
        if os.path.exists(STRATEGIES_FILE):
            with open(STRATEGIES_FILE) as f:
                strats = json.load(f)
            for s in strats:
                state = s.get("state", {})
                floor = f"${state.get('current_floor', 0):,.2f}"
                high = f"${state.get('highest_price', 0):,.2f}"
                tag = "active" if s["status"] == "active" else "inactive"
                self.strat_tree.insert("", "end", values=(
                    s["id"], s["symbol"], s["type"], s["status"], floor, high,
                ), tags=(tag,))
            self.strat_tree.tag_configure("active", foreground="green")
            self.strat_tree.tag_configure("inactive", foreground="gray")

        # Engine
        running, pid = is_engine_running()
        if running:
            self.engine_lbl.config(text=f"Running (pid={pid})", fg="green")
            self.start_eng_btn.config(state="disabled")
            self.stop_eng_btn.config(state="normal")
        else:
            self.engine_lbl.config(text="Stopped", fg="red")
            self.start_eng_btn.config(state="normal")
            self.stop_eng_btn.config(state="disabled")

        # Watchlist with live quotes
        self.wl_tree.delete(*self.wl_tree.get_children())
        wl_file = os.path.join(SCRIPT_DIR, "watchlist.json")
        self.wl_data = []
        if os.path.exists(wl_file):
            with open(wl_file) as f:
                self.wl_data = json.load(f)
            for w in self.wl_data:
                price = ""
                try:
                    q = self.trader.get_quote(w["symbol"])
                    if "bid" in q:
                        price = f"${(float(q['bid']) + float(q['ask'])) / 2:,.2f}"
                except Exception:
                    pass
                self.wl_tree.insert("", "end", values=(
                    w["symbol"], price, w.get("reason", ""), w.get("added", ""),
                ))

        # Load last research if pane is visible
        if self.research_visible.get():
            self._load_last_research()

    def auto_refresh(self):
        self.refresh()
        self.after(10000, self.auto_refresh)

    def start_engine(self):
        subprocess.Popen([PYTHONW, ENGINE_SCRIPT, "--interval", "300", "--always-heartbeat"],
                         cwd=SCRIPT_DIR, creationflags=0x00000008)
        self.after(2000, self.refresh)

    def stop_engine(self):
        running, pid = is_engine_running()
        if running and pid:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True, timeout=5, startupinfo=SI)
        if os.path.exists(ENGINE_PID_FILE):
            os.remove(ENGINE_PID_FILE)
        self.after(1000, self.refresh)

    def new_trailing_stop(self):
        symbol = simpledialog.askstring("New Trailing Stop", "Symbol:", parent=self)
        if not symbol:
            return
        qty = simpledialog.askinteger("Shares", f"How many shares of {symbol.upper()}?", parent=self, minvalue=1)
        if not qty:
            return
        try:
            from trader.strategies import create_trailing_stop
            result = create_trailing_stop(self.trader, symbol.upper(), qty)
            if "error" in result:
                messagebox.showerror("Error", result["error"])
            else:
                messagebox.showinfo("Created", f"Strategy {result['id']} created")
                self.refresh()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def cancel_selected_strategy(self):
        sel = self.strat_tree.selection()
        if not sel:
            return
        sid = self.strat_tree.item(sel[0])["values"][0]
        from trader.strategies import cancel_strategy
        cancel_strategy(sid)
        self.refresh()

    def run_research(self):
        self.force_research()

    def toggle_research(self):
        if self.research_visible.get():
            self.research_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
            self._load_last_research()
        else:
            self.research_frame.pack_forget()

    def _load_last_research(self):
        from trader.research import get_last_research
        last = get_last_research()
        self.research_text.config(state="normal")
        self.research_text.delete("1.0", "end")
        if last:
            header = f"[{last.get('session', '?').upper()}] {last.get('time', '?')[:19]} ({last.get('mode', '?')} brain)\n\n"
            self.research_text.insert("1.0", header + last.get("report", "No report"))
        else:
            self.research_text.insert("1.0", "No research reports yet. Click 'Force Research Now'.")
        self.research_text.config(state="disabled")

    def force_research(self):
        import threading
        brain = self.research_brain.get()
        self.research_text.config(state="normal")
        self.research_text.delete("1.0", "end")
        self.research_text.insert("1.0", f"Running {brain} research (this takes a minute)...")
        self.research_text.config(state="disabled")

        if not self.research_visible.get():
            self.research_visible.set(True)
            self.research_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        def _run():
            try:
                from trader.research import run_research
                result = run_research(self.trader, "midday", brain)
                report = result.get("report", "No report generated")
                header = f"[MIDDAY] {result.get('time', '?')[:19]} ({brain} brain)\n\n"
                self.after(0, lambda: self._show_research(header + report))
            except Exception as e:
                self.after(0, lambda: self._show_research(f"Error: {e}"))

        threading.Thread(target=_run, daemon=True).start()

    def _show_research(self, text):
        self.research_text.config(state="normal")
        self.research_text.delete("1.0", "end")
        self.research_text.insert("1.0", text)
        self.research_text.config(state="disabled")

    def add_watchlist(self):
        symbol = simpledialog.askstring("Add to Watchlist", "Symbol:", parent=self)
        if not symbol:
            return
        reason = simpledialog.askstring("Reason", f"Why watch {symbol.upper()}?", parent=self) or ""
        from trader.research import load_watchlist, save_watchlist
        wl = load_watchlist()
        if any(w["symbol"] == symbol.upper() for w in wl):
            return
        wl.append({"symbol": symbol.upper(), "reason": reason, "added": time.strftime("%Y-%m-%d")})
        save_watchlist(wl)
        self.refresh()

    def rm_watchlist(self):
        sel = self.wl_tree.selection()
        if not sel:
            return
        idx = self.wl_tree.index(sel[0])
        from trader.research import load_watchlist, save_watchlist
        wl = load_watchlist()
        if idx < len(wl):
            wl.pop(idx)
            save_watchlist(wl)
            self.refresh()

    def buy_from_watchlist(self):
        sel = self.wl_tree.selection()
        if not sel:
            return
        idx = self.wl_tree.index(sel[0])
        if idx >= len(self.wl_data):
            return
        symbol = self.wl_data[idx]["symbol"]
        qty = simpledialog.askinteger("Buy", f"How many shares of {symbol}?", parent=self, minvalue=1)
        if not qty:
            return
        try:
            from trader.strategies import create_trailing_stop
            result = create_trailing_stop(self.trader, symbol, qty)
            if "error" in result:
                messagebox.showerror("Error", result["error"])
            else:
                messagebox.showinfo("Created", f"Trailing stop {result['id']} on {symbol}")
                self.refresh()
        except Exception as e:
            messagebox.showerror("Error", str(e))


if __name__ == "__main__":
    TraderApp().mainloop()
