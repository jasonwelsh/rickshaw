"""Rickshaw Trader MCP Server — Stock trading tools for Alpaca + Capitol Trades.

Tools:
  Trading: trade_buy, trade_sell, trade_positions, trade_orders,
           trade_cancel, trade_quote, trade_account
  Data:    capitol_recent_trades, capitol_top_traders, capitol_politician_trades
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp import types
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "mcp", "-q"])
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp import types

from trader.alpaca_client import AlpacaTrader
from trader import capitol_trades

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "trader_config.json")

app = Server("rickshaw-trader")


def _load_trader():
    """Load Alpaca trader from config."""
    if not os.path.exists(CONFIG_FILE):
        return None
    with open(CONFIG_FILE) as f:
        cfg = json.load(f)
    key = cfg.get("alpaca_api_key", "")
    secret = cfg.get("alpaca_secret_key", "")
    paper = cfg.get("paper", True)
    if not key or not secret:
        return None
    return AlpacaTrader(key, secret, paper=paper)


def _result(data):
    text = json.dumps(data, indent=2) if isinstance(data, (dict, list)) else str(data)
    return [types.TextContent(type="text", text=text)]


# ── Tool Definitions ─────────────────────────────────────────────────

@app.list_tools()
async def list_tools():
    return [
        # Trading
        types.Tool(
            name="trade_buy",
            description="Buy stocks via Alpaca. Supports market, limit, stop, trailing_stop orders.",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Stock ticker (e.g. AAPL, TSLA)"},
                    "qty": {"type": "number", "description": "Number of shares"},
                    "order_type": {"type": "string", "enum": ["market", "limit", "stop", "trailing_stop"], "description": "Order type (default: market)"},
                    "limit_price": {"type": "number", "description": "Limit price (for limit/stop_limit orders)"},
                    "stop_price": {"type": "number", "description": "Stop price (for stop orders)"},
                    "trail_percent": {"type": "number", "description": "Trail percent (for trailing_stop)"},
                },
                "required": ["symbol", "qty"],
            },
        ),
        types.Tool(
            name="trade_sell",
            description="Sell stocks via Alpaca. Supports market, limit, stop, trailing_stop orders.",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Stock ticker"},
                    "qty": {"type": "number", "description": "Number of shares"},
                    "order_type": {"type": "string", "enum": ["market", "limit", "stop", "trailing_stop"]},
                    "limit_price": {"type": "number"},
                    "stop_price": {"type": "number"},
                    "trail_percent": {"type": "number"},
                },
                "required": ["symbol", "qty"],
            },
        ),
        types.Tool(
            name="trade_account",
            description="Get Alpaca account info: buying power, cash, portfolio value.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="trade_positions",
            description="Get all open positions with P&L.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="trade_orders",
            description="Get recent orders.",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["open", "all"], "description": "Filter by status (default: open)"},
                },
            },
        ),
        types.Tool(
            name="trade_cancel",
            description="Cancel an order by ID, or cancel all open orders.",
            inputSchema={
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "Order ID to cancel (omit to cancel all)"},
                },
            },
        ),
        types.Tool(
            name="trade_quote",
            description="Get latest stock quote (bid/ask price).",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Stock ticker"},
                },
                "required": ["symbol"],
            },
        ),
        types.Tool(
            name="trade_close_position",
            description="Close a position (sell all shares of a symbol).",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Stock ticker to close"},
                },
                "required": ["symbol"],
            },
        ),
        # Capitol Trades
        types.Tool(
            name="capitol_recent_trades",
            description="Get recent stock trades by US politicians from Capitol Trades.",
            inputSchema={
                "type": "object",
                "properties": {
                    "page": {"type": "number", "description": "Page number (default: 1)"},
                },
            },
        ),
        types.Tool(
            name="capitol_top_traders",
            description="Get list of most active trading politicians.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="capitol_politician_trades",
            description="Get trades for a specific politician by their slug/URL name.",
            inputSchema={
                "type": "object",
                "properties": {
                    "politician": {"type": "string", "description": "Politician slug (e.g. 'nancy-pelosi', 'michael-mccaul')"},
                },
                "required": ["politician"],
            },
        ),
        # Config
        types.Tool(
            name="trade_setup",
            description="Configure Alpaca API credentials. Provide key, secret, and paper mode.",
            inputSchema={
                "type": "object",
                "properties": {
                    "api_key": {"type": "string", "description": "Alpaca API key"},
                    "secret_key": {"type": "string", "description": "Alpaca secret key"},
                    "paper": {"type": "boolean", "description": "Paper trading mode (default: true)"},
                },
                "required": ["api_key", "secret_key"],
            },
        ),
    ]


# ── Tool Handlers ────────────────────────────────────────────────────

@app.call_tool()
async def call_tool(name: str, arguments: dict):
    # Setup
    if name == "trade_setup":
        cfg = {
            "alpaca_api_key": arguments["api_key"],
            "alpaca_secret_key": arguments["secret_key"],
            "paper": arguments.get("paper", True),
        }
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
        # Verify connection
        try:
            trader = AlpacaTrader(cfg["alpaca_api_key"], cfg["alpaca_secret_key"], paper=cfg["paper"])
            acct = trader.get_account()
            return _result({"status": "connected", "account": acct})
        except Exception as e:
            return _result({"status": "error", "message": str(e)})

    # Capitol Trades (no auth needed)
    if name == "capitol_recent_trades":
        return _result(capitol_trades.get_recent_trades(page=int(arguments.get("page", 1))))

    if name == "capitol_top_traders":
        return _result(capitol_trades.get_top_traders())

    if name == "capitol_politician_trades":
        return _result(capitol_trades.get_politician_trades(arguments["politician"]))

    # Trading (needs auth)
    trader = _load_trader()
    if not trader:
        return _result({"error": "Alpaca not configured. Use trade_setup first."})

    try:
        if name == "trade_buy":
            return _result(trader.buy(
                symbol=arguments["symbol"],
                qty=int(arguments["qty"]),
                order_type=arguments.get("order_type", "market"),
                limit_price=arguments.get("limit_price"),
                stop_price=arguments.get("stop_price"),
                trail_percent=arguments.get("trail_percent"),
            ))

        elif name == "trade_sell":
            return _result(trader.sell(
                symbol=arguments["symbol"],
                qty=int(arguments["qty"]),
                order_type=arguments.get("order_type", "market"),
                limit_price=arguments.get("limit_price"),
                stop_price=arguments.get("stop_price"),
                trail_percent=arguments.get("trail_percent"),
            ))

        elif name == "trade_account":
            return _result(trader.get_account())

        elif name == "trade_positions":
            return _result(trader.get_positions())

        elif name == "trade_orders":
            return _result(trader.get_orders(
                status=arguments.get("status", "open"),
            ))

        elif name == "trade_cancel":
            order_id = arguments.get("order_id")
            if order_id:
                return _result(trader.cancel_order(order_id))
            return _result(trader.cancel_all())

        elif name == "trade_quote":
            return _result(trader.get_quote(arguments["symbol"]))

        elif name == "trade_close_position":
            return _result(trader.close_position(arguments["symbol"]))

    except Exception as e:
        return _result({"error": str(e)})

    return _result({"error": f"Unknown tool: {name}"})


async def main():
    print("Rickshaw Trader MCP started", file=sys.stderr)
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
