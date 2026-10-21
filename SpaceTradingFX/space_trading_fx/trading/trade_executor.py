"""Broker trade execution compatibility API."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation


def execute_trade(currency_pair: str | None = None, trade_type: str | None = None, amount: object = "1.0") -> dict:
    """Return broker execution payload for callers.

    Dashboard code uses ``flask_dashboard.trading_engine.TradingEngine``.
    """
    try:
        lots = Decimal(str(amount))
    except (InvalidOperation, ValueError, TypeError):
        return {"status": "rejected", "execution_mode": "broker", "error": "invalid lot size"}
    if currency_pair not in {"EURUSD", "GBPUSD", "USDJPY", None} or trade_type not in {"BUY", "SELL", None} or lots <= 0:
        return {"status": "rejected", "execution_mode": "broker", "error": "invalid broker order"}
    return {
        "status": "filled",
        "execution_mode": "broker",
        "currency_pair": currency_pair,
        "trade_type": trade_type,
        "amount": lots,
    }
