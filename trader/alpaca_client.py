"""Alpaca Trading Client — Wrapper around alpaca-py SDK."""
import os
import json
from datetime import datetime

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest, LimitOrderRequest, StopOrderRequest,
    StopLimitOrderRequest, TrailingStopOrderRequest,
    GetOrdersRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderStatus, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame


class AlpacaTrader:
    """Thin wrapper around Alpaca SDK for clean tool integration."""

    def __init__(self, api_key=None, secret_key=None, paper=True):
        self.api_key = api_key
        self.secret_key = secret_key
        self.paper = paper

        self.trading = TradingClient(api_key, secret_key, paper=paper)
        self.data = StockHistoricalDataClient(api_key, secret_key)

    # ── Account ──────────────────────────────────────────────────

    def get_account(self):
        acct = self.trading.get_account()
        return {
            "buying_power": str(acct.buying_power),
            "cash": str(acct.cash),
            "portfolio_value": str(acct.portfolio_value),
            "equity": str(acct.equity),
            "status": acct.status.value if acct.status else "unknown",
        }

    # ── Orders ───────────────────────────────────────────────────

    def buy(self, symbol, qty=1, order_type="market", limit_price=None,
            stop_price=None, trail_percent=None, time_in_force="day"):
        """Place a buy order."""
        return self._place_order(
            symbol, qty, OrderSide.BUY, order_type,
            limit_price, stop_price, trail_percent, time_in_force,
        )

    def sell(self, symbol, qty=1, order_type="market", limit_price=None,
             stop_price=None, trail_percent=None, time_in_force="day"):
        """Place a sell order."""
        return self._place_order(
            symbol, qty, OrderSide.SELL, order_type,
            limit_price, stop_price, trail_percent, time_in_force,
        )

    def _place_order(self, symbol, qty, side, order_type, limit_price,
                     stop_price, trail_percent, time_in_force):
        tif = TimeInForce.DAY if time_in_force == "day" else TimeInForce.GTC

        if order_type == "market":
            req = MarketOrderRequest(
                symbol=symbol, qty=qty, side=side, time_in_force=tif,
            )
        elif order_type == "limit":
            req = LimitOrderRequest(
                symbol=symbol, qty=qty, side=side, time_in_force=tif,
                limit_price=limit_price,
            )
        elif order_type == "stop":
            req = StopOrderRequest(
                symbol=symbol, qty=qty, side=side, time_in_force=tif,
                stop_price=stop_price,
            )
        elif order_type == "stop_limit":
            req = StopLimitOrderRequest(
                symbol=symbol, qty=qty, side=side, time_in_force=tif,
                stop_price=stop_price, limit_price=limit_price,
            )
        elif order_type == "trailing_stop":
            req = TrailingStopOrderRequest(
                symbol=symbol, qty=qty, side=side, time_in_force=tif,
                trail_percent=trail_percent,
            )
        else:
            return {"error": f"Unknown order type: {order_type}"}

        order = self.trading.submit_order(req)
        return self._format_order(order)

    def get_orders(self, status="open", limit=20):
        """Get recent orders."""
        q_status = QueryOrderStatus.OPEN if status == "open" else QueryOrderStatus.ALL
        req = GetOrdersRequest(status=q_status, limit=limit)
        orders = self.trading.get_orders(req)
        return [self._format_order(o) for o in orders]

    def cancel_order(self, order_id):
        self.trading.cancel_order_by_id(order_id)
        return {"status": "cancelled", "order_id": order_id}

    def cancel_all(self):
        self.trading.cancel_orders()
        return {"status": "all_orders_cancelled"}

    # ── Positions ────────────────────────────────────────────────

    def get_positions(self):
        positions = self.trading.get_all_positions()
        return [self._format_position(p) for p in positions]

    def get_position(self, symbol):
        try:
            p = self.trading.get_open_position(symbol)
            return self._format_position(p)
        except Exception as e:
            return {"error": str(e)}

    def close_position(self, symbol):
        self.trading.close_position(symbol)
        return {"status": "closed", "symbol": symbol}

    def close_all(self):
        self.trading.close_all_positions()
        return {"status": "all_positions_closed"}

    # ── Market Data ──────────────────────────────────────────────

    def get_quote(self, symbol):
        """Get latest quote for a symbol."""
        req = StockLatestQuoteRequest(symbol_or_symbols=symbol)
        quotes = self.data.get_stock_latest_quote(req)
        q = quotes.get(symbol)
        if q:
            return {
                "symbol": symbol,
                "bid": str(q.bid_price),
                "ask": str(q.ask_price),
                "bid_size": q.bid_size,
                "ask_size": q.ask_size,
                "timestamp": str(q.timestamp),
            }
        return {"error": f"No quote for {symbol}"}

    # ── Helpers ──────────────────────────────────────────────────

    def _format_order(self, o):
        return {
            "id": str(o.id),
            "symbol": o.symbol,
            "side": o.side.value if o.side else "?",
            "qty": str(o.qty),
            "type": o.type.value if o.type else "?",
            "status": o.status.value if o.status else "?",
            "filled_avg_price": str(o.filled_avg_price) if o.filled_avg_price else None,
            "created_at": str(o.created_at),
        }

    def _format_position(self, p):
        return {
            "symbol": p.symbol,
            "qty": str(p.qty),
            "avg_entry": str(p.avg_entry_price),
            "current_price": str(p.current_price),
            "market_value": str(p.market_value),
            "unrealized_pl": str(p.unrealized_pl),
            "unrealized_plpc": str(p.unrealized_plpc),
        }
