"""Rickshaw Forex GUI — Dashboard for forex positions, strategies, signals, and AI analysis.

Same skin as trader_gui.pyw — standard tkinter, scrollable, auto-refresh every 10s.
All logic calls into the same functions as the CLI (python -m forex).
"""
import json
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PARENT_DIR)

CONFIG_FILE = os.path.join(PARENT_DIR, "trader", "trader_config.json")
STRATEGIES_FILE = os.path.join(SCRIPT_DIR, "forex_strategies.json")
ENGINE_PID_FILE = os.path.join(SCRIPT_DIR, "forex_engine.pid")
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
    if not cfg.get("oanda_api_key") or not cfg.get("oanda_account_id"):
        return None
    from trader.oanda_client import OandaTrader
    return OandaTrader(cfg["oanda_api_key"], cfg["oanda_account_id"],
                       practice=cfg.get("oanda_practice", True))


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


class ForexApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Rickshaw Forex")
        self.geometry("700x800")
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

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        sf = self.scroll_frame

        # ── Account Bar ──────────────────────────────────────────
        acct_frame = tk.Frame(sf, pady=5, padx=10)
        acct_frame.pack(fill="x")

        self.nav_lbl = tk.Label(acct_frame, text="Loading...", font=("Arial", 14, "bold"))
        self.nav_lbl.pack(side="left")

        self.upl_lbl = tk.Label(acct_frame, text="", font=("Arial", 14, "bold"))
        self.upl_lbl.pack(side="left", padx=20)

        self.market_lbl = tk.Label(acct_frame, text="", font=("Arial", 10))
        self.market_lbl.pack(side="right", padx=10)

        self.mode_lbl = tk.Label(acct_frame, text="PRACTICE", font=("Arial", 10), fg="orange")
        self.mode_lbl.pack(side="right")

        # ── Engine Controls ──────────────────────────────────────
        engine_frame = tk.LabelFrame(sf, text="Engine", font=("Arial", 11, "bold"), padx=10, pady=5)
        engine_frame.pack(fill="x", padx=10, pady=3)

        self.engine_lbl = tk.Label(engine_frame, text="...", font=("Arial", 11))
        self.engine_lbl.pack(side="left")

        self.session_lbl = tk.Label(engine_frame, text="", font=("Arial", 10), fg="gray")
        self.session_lbl.pack(side="left", padx=15)

        tk.Button(engine_frame, text="Scan", font=("Arial", 10),
                  command=self.run_scan).pack(side="right", padx=3)
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

        pos_cols = ("pair", "side", "units", "entry", "pl", "spread")
        self.pos_tree = ttk.Treeview(pos_frame, columns=pos_cols, show="headings", height=5)
        self.pos_tree.heading("pair", text="Pair")
        self.pos_tree.heading("side", text="Side")
        self.pos_tree.heading("units", text="Units")
        self.pos_tree.heading("entry", text="Entry")
        self.pos_tree.heading("pl", text="P&L")
        self.pos_tree.heading("spread", text="Spread")

        self.pos_tree.column("pair", width=85)
        self.pos_tree.column("side", width=55)
        self.pos_tree.column("units", width=65)
        self.pos_tree.column("entry", width=90)
        self.pos_tree.column("pl", width=90)
        self.pos_tree.column("spread", width=60)
        self.pos_tree.pack(fill="x")

        pos_btn = tk.Frame(pos_frame, pady=3)
        pos_btn.pack(fill="x")
        tk.Button(pos_btn, text="Close Selected", font=("Arial", 10),
                  command=self.close_selected_position).pack(side="left", padx=3)
        tk.Button(pos_btn, text="Close All", font=("Arial", 10),
                  command=self.close_all_positions).pack(side="left", padx=3)

        # ── Strategies ───────────────────────────────────────────
        strat_frame = tk.LabelFrame(sf, text="Strategies", font=("Arial", 11, "bold"), padx=10, pady=5)
        strat_frame.pack(fill="x", padx=10, pady=3)

        strat_cols = ("id", "pair", "type", "status", "floor", "high", "units")
        self.strat_tree = ttk.Treeview(strat_frame, columns=strat_cols, show="headings", height=6)
        self.strat_tree.heading("id", text="ID")
        self.strat_tree.heading("pair", text="Pair")
        self.strat_tree.heading("type", text="Type")
        self.strat_tree.heading("status", text="Status")
        self.strat_tree.heading("floor", text="Floor/Ceil")
        self.strat_tree.heading("high", text="High/Low")
        self.strat_tree.heading("units", text="Units")

        self.strat_tree.column("id", width=140)
        self.strat_tree.column("pair", width=75)
        self.strat_tree.column("type", width=55)
        self.strat_tree.column("status", width=60)
        self.strat_tree.column("floor", width=90)
        self.strat_tree.column("high", width=90)
        self.strat_tree.column("units", width=55)
        self.strat_tree.pack(fill="x")

        strat_btn = tk.Frame(strat_frame, pady=3)
        strat_btn.pack(fill="x")
        tk.Button(strat_btn, text="New Long", font=("Arial", 10),
                  command=self.new_trailing_stop).pack(side="left", padx=3)
        tk.Button(strat_btn, text="New Short", font=("Arial", 10),
                  command=self.new_short).pack(side="left", padx=3)
        tk.Button(strat_btn, text="Cancel Selected", font=("Arial", 10),
                  command=self.cancel_selected_strategy).pack(side="left", padx=3)
        tk.Button(strat_btn, text="Auto-Deploy", font=("Arial", 10),
                  command=self.run_auto_deploy).pack(side="right", padx=3)

        # ── AI Analysis ──────────────────────────────────────────
        ai_frame = tk.LabelFrame(sf, text="AI Analysis", font=("Arial", 11, "bold"), padx=10, pady=5)
        ai_frame.pack(fill="both", expand=True, padx=10, pady=3)

        ai_btn = tk.Frame(ai_frame, pady=3)
        ai_btn.pack(fill="x")
        tk.Button(ai_btn, text="Analyze Pair", font=("Arial", 10),
                  command=self.analyze_selected).pack(side="left", padx=3)
        tk.Button(ai_btn, text="Full Scan", font=("Arial", 10),
                  command=self.run_scan).pack(side="left", padx=3)
        tk.Button(ai_btn, text="Daily Report", font=("Arial", 10),
                  command=self.run_daily).pack(side="left", padx=3)

        self.brain_var = tk.StringVar(value="qwen")
        tk.Label(ai_btn, text="Brain:", font=("Arial", 10)).pack(side="right")
        tk.OptionMenu(ai_btn, self.brain_var, "auto", "qwen", "opus").pack(side="right", padx=3)

        self.ai_text = tk.Text(ai_frame, font=("Consolas", 9), height=10, wrap="word",
                               state="disabled")
        self.ai_text.pack(fill="both", expand=True, pady=3)

        self.refresh()
        self.auto_refresh()

    # ── Refresh ──────────────────────────────────────────────────

    def refresh(self):
        if not self.trader:
            self.nav_lbl.config(text="Not connected", fg="red")
            return

        try:
            acct = self.trader.get_account()
            nav = float(acct["portfolio_value"])
            upl = float(acct["unrealized_pl"])

            self.nav_lbl.config(text=f"${nav:,.0f}", fg="black")
            upl_color = "green" if upl >= 0 else "red"
            self.upl_lbl.config(text=f"UPL: ${upl:+,.2f}", fg=upl_color)

            market_open = self.trader.is_market_open()
            self.market_lbl.config(
                text="OPEN" if market_open else "CLOSED",
                fg="green" if market_open else "red")

            try:
                from forex.strategies import get_active_session
                session = get_active_session()
                sess = ", ".join(session["sessions"]) or "gap"
                self.session_lbl.config(text=f"{sess} ({session['liquidity']:.0%})")
            except Exception:
                pass

            # Positions
            positions = self.trader.get_positions()
            self.pos_tree.delete(*self.pos_tree.get_children())
            for p in positions:
                pl = float(p["unrealized_pl"])
                long_u = float(p.get("long_units", 0))
                short_u = float(p.get("short_units", 0))
                side = "LONG" if long_u > 0 else "SHORT"
                units = abs(long_u) if long_u != 0 else abs(short_u)

                spread = ""
                try:
                    q = self.trader.get_quote(p["instrument"])
                    if "error" not in q:
                        spread = f"{q['spread_pips']}p"
                except Exception:
                    pass

                tag = "gain" if pl >= 0 else "loss"
                self.pos_tree.insert("", "end", values=(
                    p["instrument"], side, f"{units:.0f}",
                    p["avg_entry"], f"${pl:+,.2f}", spread,
                ), tags=(tag,))
            self.pos_tree.tag_configure("gain", foreground="green")
            self.pos_tree.tag_configure("loss", foreground="red")

        except Exception as e:
            self.nav_lbl.config(text=f"Error: {e}", fg="red")

        # Strategies
        self.strat_tree.delete(*self.strat_tree.get_children())
        if os.path.exists(STRATEGIES_FILE):
            with open(STRATEGIES_FILE) as f:
                strats = json.load(f)
            for s in strats:
                state = s.get("state", {})
                if s["type"] == "forex_trailing_stop":
                    fc = f"{state.get('current_floor', 0):.5f}"
                    hl = f"{state.get('highest_price', 0):.5f}"
                    stype = "Long"
                elif s["type"] == "forex_short":
                    fc = f"{state.get('current_ceiling', 0):.5f}"
                    hl = f"{state.get('lowest_price', 0):.5f}"
                    stype = "Short"
                else:
                    fc = hl = stype = ""

                tag = "active" if s["status"] == "active" else "inactive"
                self.strat_tree.insert("", "end", values=(
                    s["id"], s.get("instrument", ""), stype,
                    s["status"], fc, hl, state.get("total_units", 0),
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

    def auto_refresh(self):
        self.refresh()
        self.after(10000, self.auto_refresh)

    # ── Engine ───────────────────────────────────────────────────

    def start_engine(self):
        subprocess.Popen([PYTHONW, ENGINE_SCRIPT, "--interval", "60", "--heartbeat-every", "5"],
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

    # ── Trading ──────────────────────────────────────────────────

    def new_trailing_stop(self):
        pair = simpledialog.askstring("New Long", "Pair (e.g. EUR_USD):", parent=self)
        if not pair:
            return
        pair = pair.upper().replace("/", "_")
        units = simpledialog.askinteger("Units", f"Units for {pair}?\n(1000=micro, 10000=mini)",
                                        parent=self, minvalue=100)
        if not units:
            return
        stop = simpledialog.askinteger("Stop", "Stop distance (pips):", parent=self,
                                       initialvalue=40, minvalue=5)
        if not stop:
            return

        def _do():
            try:
                from forex.strategies import create_trailing_stop
                result = create_trailing_stop(self.trader, pair, units,
                                              stop_pips=stop, trail_pips=int(stop * 0.6),
                                              take_profit_pips=stop * 2)
                if "error" in result:
                    self.after(0, lambda: messagebox.showerror("Error", result["error"]))
                else:
                    self.after(0, lambda: self._show_ai(
                        f"Created: {result['id']}\n{result['log'][0]['msg']}"))
                    self.after(0, self.refresh)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", str(e)))
        threading.Thread(target=_do, daemon=True).start()

    def new_short(self):
        pair = simpledialog.askstring("New Short", "Pair (e.g. USD_JPY):", parent=self)
        if not pair:
            return
        pair = pair.upper().replace("/", "_")
        units = simpledialog.askinteger("Units", f"Units for {pair}?", parent=self, minvalue=100)
        if not units:
            return
        stop = simpledialog.askinteger("Stop", "Stop distance (pips):", parent=self,
                                       initialvalue=40, minvalue=5)
        if not stop:
            return

        def _do():
            try:
                from forex.strategies import create_short
                result = create_short(self.trader, pair, units,
                                      stop_pips=stop, trail_pips=int(stop * 0.6),
                                      take_profit_pips=stop * 2)
                if "error" in result:
                    self.after(0, lambda: messagebox.showerror("Error", result["error"]))
                else:
                    self.after(0, lambda: self._show_ai(
                        f"Created: {result['id']}\n{result['log'][0]['msg']}"))
                    self.after(0, self.refresh)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", str(e)))
        threading.Thread(target=_do, daemon=True).start()

    def cancel_selected_strategy(self):
        sel = self.strat_tree.selection()
        if not sel:
            return
        sid = self.strat_tree.item(sel[0])["values"][0]
        from forex.strategies import cancel_strategy
        cancel_strategy(sid)
        self.refresh()

    def close_selected_position(self):
        sel = self.pos_tree.selection()
        if not sel:
            return
        pair = self.pos_tree.item(sel[0])["values"][0]
        if messagebox.askyesno("Close", f"Close {pair} position?"):
            try:
                self.trader.close_position(pair)
                self.refresh()
            except Exception as e:
                messagebox.showerror("Error", str(e))

    def close_all_positions(self):
        if messagebox.askyesno("Close All", "Close ALL forex positions?"):
            try:
                self.trader.close_all()
                self.refresh()
            except Exception as e:
                messagebox.showerror("Error", str(e))

    # ── Analysis ─────────────────────────────────────────────────

    def analyze_selected(self):
        pair = simpledialog.askstring("Analyze", "Pair to analyze:", parent=self)
        if not pair:
            return
        pair = pair.upper().replace("/", "_")
        self._show_ai(f"Analyzing {pair}...")

        def _do():
            try:
                from forex.signals import analyze_pair, format_signal_report
                analysis = analyze_pair(self.trader, pair, timeframe="H1")
                report = format_signal_report(analysis)
                self.after(0, lambda: self._show_ai(report))
            except Exception as e:
                self.after(0, lambda: self._show_ai(f"Error: {e}"))
        threading.Thread(target=_do, daemon=True).start()

    def run_scan(self):
        self._show_ai("Scanning all pairs...")

        def _do():
            try:
                from forex.signals import scan_pairs
                results = scan_pairs(self.trader, timeframe="H1")
                lines = ["=== PAIR SCAN (H1) ===\n"]
                for r in results:
                    if "error" in r:
                        continue
                    comp = r.get("composite", {})
                    rec = comp.get("recommendation", "no_trade")
                    conf = comp.get("confidence", 0)
                    bull = comp.get("bullish", 0)
                    bear = comp.get("bearish", 0)
                    arrow = "^" if "buy" in rec else "v" if "sell" in rec else "-"
                    lines.append(f"  {arrow} {r['instrument']:<10} {rec:<12} "
                                 f"conf={conf:.0%}  ({bull}B {bear}S)")
                self.after(0, lambda: self._show_ai("\n".join(lines)))
            except Exception as e:
                self.after(0, lambda: self._show_ai(f"Scan error: {e}"))
        threading.Thread(target=_do, daemon=True).start()

    def run_daily(self):
        self._show_ai("Generating daily analysis...")

        def _do():
            try:
                from forex.brain import daily_analysis, set_brain_mode
                set_brain_mode(self.brain_var.get())
                result = daily_analysis(self.trader)
                report = result.get("analysis", "No analysis available")
                self.after(0, lambda: self._show_ai(f"=== DAILY ANALYSIS ===\n\n{report}"))
            except Exception as e:
                self.after(0, lambda: self._show_ai(f"Error: {e}"))
        threading.Thread(target=_do, daemon=True).start()

    def run_auto_deploy(self):
        if not messagebox.askyesno("Auto-Deploy", "Run auto-scanner to find and deploy trades?"):
            return
        self._show_ai("Running auto-scanner...")

        def _do():
            try:
                from forex.strategies import auto_scan_and_deploy
                results = auto_scan_and_deploy(self.trader, max_positions=6)
                lines = ["=== AUTO-SCANNER ===\n"]
                for a in results:
                    lines.append(f"  {a['msg']}")
                self.after(0, lambda: self._show_ai("\n".join(lines)))
                self.after(0, self.refresh)
            except Exception as e:
                self.after(0, lambda: self._show_ai(f"Error: {e}"))
        threading.Thread(target=_do, daemon=True).start()

    def _show_ai(self, text):
        self.ai_text.config(state="normal")
        self.ai_text.delete("1.0", "end")
        self.ai_text.insert("1.0", text)
        self.ai_text.config(state="disabled")


if __name__ == "__main__":
    ForexApp().mainloop()
