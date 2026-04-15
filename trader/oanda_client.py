"""OANDA Forex Trading Client — Mirrors AlpacaTrader interface for forex pairs.

Same pattern as alpaca_client.py so the engine, brain, and strategies
can talk to either broker through the same interface.

Uses OANDA v3 REST API directly (no SDK dependency).
"""
import os
import json
import requests
from datetime import datetime, timezone


class OandaTrader:
    """Thin wrapper around OANDA v3 REST API for clean tool integration."""

    PRACTICE_URL = "https://api-fxpractice.oanda.com"
    LIVE_URL = "https://api-fxtrade.oanda.com"

    def __init__(self, api_key=None, account_id=None, practice=True):
        self.api_key = api_key
        self.account_id = account_id
        self.practice = practice
        self.base_url = self.PRACTICE_URL if practice else self.LIVE_URL
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _get(self, path, params=None):
        url = f"{self.base_url}{path}"
        r = requests.get(url, headers=self.headers, params=params, timeout=10)
        r.raise_for_status()
        return r.json()

    def _post(self, path, data):
        url = f"{self.base_url}{path}"
        r = requests.post(url, headers=self.headers, json=data, timeout=10)
        if r.status_code >= 400:
            err = r.json()
            return {"error": json.dumps(err)}
        return r.json()

    def _put(self, path, data):
        url = f"{self.base_url}{path}"
        r = requests.put(url, headers=self.headers, json=data, timeout=10)
        if r.status_code >= 400:
            err = r.json()
            return {"error": json.dumps(err)}
        return r.json()

    # ── Account ──────────────────────────────────────────────────

    def get_account(self):
        data = self._get(f"/v3/accounts/{self.account_id}/summary")
        acct = data["account"]
        return {
            "balance": acct["balance"],
            "cash": acct["balance"],  # compat with AlpacaTrader
            "portfolio_value": acct["NAV"],
            "equity": acct["NAV"],
            "unrealized_pl": acct["unrealizedPL"],
            "margin_used": acct["marginUsed"],
            "margin_available": acct["marginAvailable"],
            "open_trade_count": acct["openTradeCount"],
            "open_position_count": acct["openPositionCount"],
            "currency": acct["currency"],
            "status": "active",
        }

    # ── Orders ───────────────────────────────────────────────────

    def buy(self, instrument, units, order_type="market", price=None,
            stop_loss=None, take_profit=None, trailing_stop_pips=None):
        """Place a buy (long) order. Units = number of currency units."""
        return self._place_order(
            instrument, abs(units), order_type, price,
            stop_loss, take_profit, trailing_stop_pips,
        )

    def sell(self, instrument, units, order_type="market", price=None,
             stop_loss=None, take_profit=None, trailing_stop_pips=None):
        """Place a sell (short) order. Units passed as negative to OANDA."""
        return self._place_order(
            instrument, -abs(units), order_type, price,
            stop_loss, take_profit, trailing_stop_pips,
        )

    def _place_order(self, instrument, units, order_type, price,
                     stop_loss, take_profit, trailing_stop_pips):
        order = {
            "instrument": instrument,
            "units": str(units),
            "timeInForce": "FOK",  # Fill or Kill for market
            "positionFill": "DEFAULT",
        }

        if order_type == "market":
            order["type"] = "MARKET"
        elif order_type == "limit":
            order["type"] = "LIMIT"
            order["price"] = str(price)
            order["timeInForce"] = "GTC"
        elif order_type == "stop":
            order["type"] = "STOP"
            order["price"] = str(price)
            order["timeInForce"] = "GTC"

        if stop_loss:
            order["stopLossOnFill"] = {"price": str(stop_loss)}
        if take_profit:
            order["takeProfitOnFill"] = {"price": str(take_profit)}
        if trailing_stop_pips:
            order["trailingStopLossOnFill"] = {
                "distance": str(trailing_stop_pips * self._pip_size(instrument))
            }

        result = self._post(
            f"/v3/accounts/{self.account_id}/orders",
            {"order": order},
        )

        if "error" in result:
            return result

        # Parse the response
        if "orderFillTransaction" in result:
            fill = result["orderFillTransaction"]
            return self._format_fill(fill)
        elif "orderCreateTransaction" in result:
            create = result["orderCreateTransaction"]
            return {
                "id": create.get("id", ""),
                "instrument": instrument,
                "units": str(units),
                "type": order_type,
                "status": "pending",
                "created_at": create.get("time", ""),
            }
        return result

    def get_orders(self, status="pending", limit=20):
        """Get orders. OANDA uses 'pending' instead of 'open'."""
        params = {"count": limit}
        if status == "pending" or status == "open":
            data = self._get(f"/v3/accounts/{self.account_id}/pendingOrders")
        else:
            data = self._get(f"/v3/accounts/{self.account_id}/orders", params)
        return [self._format_order(o) for o in data.get("orders", [])]

    def cancel_order(self, order_id):
        url = f"{self.base_url}/v3/accounts/{self.account_id}/orders/{order_id}/cancel"
        r = requests.put(url, headers=self.headers, timeout=10)
        if r.status_code >= 400:
            return {"error": r.text}
        return {"status": "cancelled", "order_id": order_id}

    def cancel_all(self):
        orders = self.get_orders(status="pending")
        cancelled = []
        for o in orders:
            self.cancel_order(o["id"])
            cancelled.append(o["id"])
        return {"status": "all_orders_cancelled", "count": len(cancelled)}

    # ── Positions ────────────────────────────────────────────────

    def get_positions(self):
        data = self._get(f"/v3/accounts/{self.account_id}/openPositions")
        return [self._format_position(p) for p in data.get("positions", [])]

    def get_position(self, instrument):
        try:
            data = self._get(
                f"/v3/accounts/{self.account_id}/positions/{instrument}"
            )
            return self._format_position(data["position"])
        except Exception as e:
            return {"error": str(e)}

    def close_position(self, instrument, units="ALL"):
        """Close a position. units='ALL' closes entire position."""
        # Determine if long or short
        pos = self.get_position(instrument)
        if "error" in pos:
            return pos

        body = {}
        long_units = int(float(pos.get("long_units", 0)))
        short_units = int(float(pos.get("short_units", 0)))

        if long_units > 0:
            body["longUnits"] = str(units) if units != "ALL" else "ALL"
        if short_units > 0:
            body["shortUnits"] = str(units) if units != "ALL" else "ALL"

        if not body:
            return {"error": f"No open position for {instrument}"}

        url = f"{self.base_url}/v3/accounts/{self.account_id}/positions/{instrument}/close"
        r = requests.put(url, headers=self.headers, json=body, timeout=10)
        if r.status_code >= 400:
            return {"error": r.text}
        return {"status": "closed", "instrument": instrument}

    def close_all(self):
        positions = self.get_positions()
        closed = []
        for p in positions:
            self.close_position(p["instrument"])
            closed.append(p["instrument"])
        return {"status": "all_positions_closed", "count": len(closed)}

    # ── Trades (OANDA-specific — individual fills) ───────────────

    def get_trades(self, instrument=None, state="OPEN", limit=20):
        """Get individual trades (more granular than positions)."""
        params = {"state": state, "count": limit}
        if instrument:
            params["instrument"] = instrument
        data = self._get(f"/v3/accounts/{self.account_id}/trades", params)
        return [self._format_trade(t) for t in data.get("trades", [])]

    def close_trade(self, trade_id, units=None):
        """Close a specific trade."""
        body = {}
        if units:
            body["units"] = str(units)
        url = f"{self.base_url}/v3/accounts/{self.account_id}/trades/{trade_id}/close"
        r = requests.put(url, headers=self.headers, json=body, timeout=10)
        if r.status_code >= 400:
            return {"error": r.text}
        return {"status": "closed", "trade_id": trade_id}

    def modify_trade(self, trade_id, stop_loss=None, take_profit=None,
                     trailing_stop_distance=None):
        """Modify stop loss / take profit on an open trade."""
        body = {}
        if stop_loss:
            body["stopLoss"] = {"price": str(stop_loss)}
        if take_profit:
            body["takeProfit"] = {"price": str(take_profit)}
        if trailing_stop_distance:
            body["trailingStopLoss"] = {"distance": str(trailing_stop_distance)}
        return self._put(
            f"/v3/accounts/{self.account_id}/trades/{trade_id}",
            body,
        )

    # ── Market Data ──────────────────────────────────────────────

    def get_quote(self, instrument):
        """Get latest quote for a currency pair."""
        data = self._get(
            f"/v3/accounts/{self.account_id}/pricing",
            {"instruments": instrument},
        )
        prices = data.get("prices", [])
        if not prices:
            return {"error": f"No quote for {instrument}"}

        p = prices[0]
        bid = float(p["bids"][0]["price"]) if p.get("bids") else 0
        ask = float(p["asks"][0]["price"]) if p.get("asks") else 0
        spread_pips = (ask - bid) / self._pip_size(instrument)

        return {
            "instrument": instrument,
            "symbol": instrument,  # compat with AlpacaTrader
            "bid": str(bid),
            "ask": str(ask),
            "mid": str((bid + ask) / 2),
            "spread_pips": round(spread_pips, 1),
            "tradeable": p.get("tradeable", False),
            "timestamp": p.get("time", ""),
        }

    def get_candles(self, instrument, granularity="M5", count=100):
        """Get historical candles. Granularity: S5,M1,M5,M15,H1,H4,D,W,M."""
        data = self._get(
            f"/v3/instruments/{instrument}/candles",
            {"granularity": granularity, "count": count, "price": "MBA"},
        )
        candles = []
        for c in data.get("candles", []):
            mid = c.get("mid", {})
            candles.append({
                "time": c["time"],
                "open": float(mid.get("o", 0)),
                "high": float(mid.get("h", 0)),
                "low": float(mid.get("l", 0)),
                "close": float(mid.get("c", 0)),
                "volume": c.get("volume", 0),
                "complete": c.get("complete", False),
            })
        return candles

    def get_instruments(self):
        """Get all tradeable instruments."""
        data = self._get(f"/v3/accounts/{self.account_id}/instruments")
        instruments = []
        for i in data.get("instruments", []):
            instruments.append({
                "name": i["name"],
                "type": i["type"],
                "display_name": i["displayName"],
                "pip_location": i.get("pipLocation", -4),
                "margin_rate": i.get("marginRate", "0.02"),
            })
        return instruments

    # ── Forex Market Hours ───────────────────────────────────────

    @staticmethod
    def is_market_open():
        """Forex is open 24/5: Sunday 5pm ET to Friday 5pm ET."""
        now = datetime.now(timezone.utc)
        weekday = now.weekday()  # 0=Mon, 6=Sun

        # Closed all day Saturday
        if weekday == 5:
            return False

        # Sunday: opens at 22:00 UTC (5pm ET)
        if weekday == 6:
            return now.hour >= 22

        # Friday: closes at 22:00 UTC (5pm ET)
        if weekday == 4:
            return now.hour < 22

        # Mon-Thu: open 24h
        return True

    # ── Helpers ──────────────────────────────────────────────────

    @staticmethod
    def _pip_size(instrument):
        """Get pip size for an instrument. JPY pairs = 0.01, others = 0.0001."""
        if "JPY" in instrument:
            return 0.01
        return 0.0001

    def _format_fill(self, fill):
        return {
            "id": fill.get("id", ""),
            "instrument": fill.get("instrument", ""),
            "symbol": fill.get("instrument", ""),  # compat
            "units": fill.get("units", "0"),
            "side": "buy" if int(float(fill.get("units", 0))) > 0 else "sell",
            "price": fill.get("price", "0"),
            "filled_avg_price": fill.get("price", "0"),
            "pl": fill.get("pl", "0"),
            "status": "filled",
            "created_at": fill.get("time", ""),
        }

    def _format_order(self, o):
        return {
            "id": o.get("id", ""),
            "instrument": o.get("instrument", ""),
            "symbol": o.get("instrument", ""),  # compat
            "units": o.get("units", "0"),
            "type": o.get("type", ""),
            "price": o.get("price", ""),
            "status": o.get("state", ""),
            "created_at": o.get("createTime", ""),
        }

    def _format_position(self, p):
        long_units = float(p.get("long", {}).get("units", 0))
        short_units = float(p.get("short", {}).get("units", 0))
        long_pl = float(p.get("long", {}).get("unrealizedPL", 0))
        short_pl = float(p.get("short", {}).get("unrealizedPL", 0))
        long_avg = p.get("long", {}).get("averagePrice", "0")
        short_avg = p.get("short", {}).get("averagePrice", "0")

        # Net position
        net_units = long_units + short_units  # short is negative
        unrealized_pl = long_pl + short_pl

        return {
            "instrument": p.get("instrument", ""),
            "symbol": p.get("instrument", ""),  # compat
            "qty": str(net_units),
            "long_units": str(long_units),
            "short_units": str(short_units),
            "avg_entry": long_avg if long_units != 0 else short_avg,
            "unrealized_pl": str(unrealized_pl),
            "unrealized_plpc": "0",  # OANDA doesn't provide this directly
            "current_price": "0",  # filled by quote if needed
            "market_value": "0",
        }

    def _format_trade(self, t):
        return {
            "id": t.get("id", ""),
            "instrument": t.get("instrument", ""),
            "symbol": t.get("instrument", ""),
            "units": t.get("currentUnits", t.get("initialUnits", "0")),
            "side": "buy" if int(float(t.get("currentUnits", 0))) > 0 else "sell",
            "price": t.get("price", "0"),
            "unrealized_pl": t.get("unrealizedPL", "0"),
            "state": t.get("state", ""),
            "opened_at": t.get("openTime", ""),
        }
