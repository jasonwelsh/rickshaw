"""Rickshaw Trader Daily Report — Full journal of the trading day.

Captures everything that happened: research, deploys, P&L, stops, EOD summary.
Saved as JSON and formatted for the GUI research pane.
"""
import json
import os
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(SCRIPT_DIR, "daily_reports")
os.makedirs(REPORTS_DIR, exist_ok=True)


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def _timestamp():
    return datetime.now().strftime("%H:%M:%S")


def _report_path(date=None):
    return os.path.join(REPORTS_DIR, f"{date or _today()}.json")


def load_report(date=None):
    path = _report_path(date)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {
        "date": date or _today(),
        "start_value": None,
        "end_value": None,
        "start_cash": None,
        "end_cash": None,
        "pnl_realized": 0,
        "pnl_unrealized": 0,
        "day_trades_used": 0,
        "events": [],
        "research_picks": [],
        "deployed": [],
        "positions_eod": [],
        "stops_triggered": [],
        "profits_taken": [],
    }


def save_report(report):
    path = _report_path(report["date"])
    with open(path, "w") as f:
        json.dump(report, f, indent=2)


def log_event(event_type, message, data=None):
    """Add an event to today's report."""
    report = load_report()
    report["events"].append({
        "time": _timestamp(),
        "type": event_type,
        "message": message,
        **(data or {}),
    })
    save_report(report)


def log_market_open(portfolio_value, cash):
    report = load_report()
    report["start_value"] = portfolio_value
    report["start_cash"] = cash
    report["events"].append({
        "time": _timestamp(),
        "type": "market_open",
        "message": f"Market opened. Portfolio: ${portfolio_value:,.2f} Cash: ${cash:,.2f}",
    })
    save_report(report)


def log_research(picks):
    report = load_report()
    report["research_picks"] = picks
    report["events"].append({
        "time": _timestamp(),
        "type": "research",
        "message": f"Qwen picked {len(picks)} stocks: {', '.join(p['symbol'] for p in picks)}",
    })
    save_report(report)


def log_deploy(symbol, qty, price, score, sector):
    report = load_report()
    deploy = {"symbol": symbol, "qty": qty, "price": price, "score": score,
              "sector": sector, "time": _timestamp()}
    report["deployed"].append(deploy)
    report["events"].append({
        "time": _timestamp(),
        "type": "deploy",
        "message": f"Deployed {qty}x {symbol} @ ${price:,.2f} (score={score}, {sector})",
    })
    save_report(report)


def log_stop_triggered(symbol, qty, price, pnl):
    report = load_report()
    report["stops_triggered"].append({
        "symbol": symbol, "qty": qty, "price": price, "pnl": pnl, "time": _timestamp(),
    })
    report["pnl_realized"] += pnl
    report["events"].append({
        "time": _timestamp(),
        "type": "stop",
        "message": f"STOP: Sold {qty}x {symbol} @ ${price:,.2f} P&L: ${pnl:+,.2f}",
    })
    save_report(report)


def log_profit_taken(symbol, qty, price, pnl):
    report = load_report()
    report["profits_taken"].append({
        "symbol": symbol, "qty": qty, "price": price, "pnl": pnl, "time": _timestamp(),
    })
    report["pnl_realized"] += pnl
    report["events"].append({
        "time": _timestamp(),
        "type": "profit",
        "message": f"PROFIT: Sold {qty}x {symbol} @ ${price:,.2f} P&L: ${pnl:+,.2f}",
    })
    save_report(report)


def log_market_close(portfolio_value, cash, positions, pnl_realized):
    report = load_report()
    report["end_value"] = portfolio_value
    report["end_cash"] = cash
    report["pnl_realized"] = pnl_realized
    report["pnl_unrealized"] = sum(p.get("pl", 0) for p in positions)
    report["positions_eod"] = positions
    report["events"].append({
        "time": _timestamp(),
        "type": "market_close",
        "message": f"Market closed. Portfolio: ${portfolio_value:,.2f}",
    })
    save_report(report)


def format_report(date=None):
    """Format daily report as readable text for GUI/Telegram."""
    report = load_report(date)

    lines = [f"=== DAILY REPORT: {report['date']} ==="]
    lines.append("")

    # Summary
    if report["start_value"] and report["end_value"]:
        change = report["end_value"] - report["start_value"]
        lines.append(f"Portfolio: ${report['start_value']:,.2f} -> ${report['end_value']:,.2f} (${change:+,.2f})")
    elif report["start_value"]:
        lines.append(f"Portfolio at open: ${report['start_value']:,.2f}")

    if report["pnl_realized"]:
        lines.append(f"Realized P&L: ${report['pnl_realized']:+,.2f}")

    # Research
    if report["research_picks"]:
        lines.append(f"\nResearch ({len(report['research_picks'])} picks):")
        for p in report["research_picks"]:
            lines.append(f"  {p['symbol']:5s} | {p.get('reason', '')[:55]}")

    # Deploys
    if report["deployed"]:
        lines.append(f"\nDeployed ({len(report['deployed'])} positions):")
        for d in report["deployed"]:
            lines.append(f"  {d['time']} {d['symbol']} {d['qty']}x @ ${d['price']:,.2f} ({d['sector']})")

    # Stops
    if report["stops_triggered"]:
        lines.append(f"\nStops triggered ({len(report['stops_triggered'])}):")
        for s in report["stops_triggered"]:
            lines.append(f"  {s['time']} {s['symbol']} ${s['pnl']:+,.2f}")

    # Profits
    if report["profits_taken"]:
        lines.append(f"\nProfits taken ({len(report['profits_taken'])}):")
        for p in report["profits_taken"]:
            lines.append(f"  {p['time']} {p['symbol']} ${p['pnl']:+,.2f}")

    # EOD positions
    if report["positions_eod"]:
        lines.append(f"\nEnd of day positions:")
        for p in report["positions_eod"]:
            lines.append(f"  {p['symbol']:5s} {p.get('qty', '?')} shares P&L: ${p.get('pl', 0):+,.2f}")

    # Event timeline
    if report["events"]:
        lines.append(f"\nTimeline ({len(report['events'])} events):")
        for e in report["events"]:
            lines.append(f"  {e['time']} [{e['type']}] {e['message']}")

    return "\n".join(lines)


def get_latest_report_date():
    """Get the most recent report date."""
    files = sorted([f.replace(".json", "") for f in os.listdir(REPORTS_DIR) if f.endswith(".json")])
    return files[-1] if files else None
