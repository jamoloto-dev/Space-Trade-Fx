"""Deprecated demo compatibility API; it performs no broker operation."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation


def execute_trade(currency_pair: str | None = None, trade_type: str | None = None, amount: object = "1.0") -> dict:
    """Return a clearly-labelled paper simulation for legacy callers.

    New dashboard code uses ``flask_dashboard.trading_engine.TradingEngine``.
    This function is retained only so an older local strategy import cannot
    accidentally become a live execution path.
    """
    try:
        lots = Decimal(str(amount))
    except (InvalidOperation, ValueError, TypeError):
        return {"status": "rejected", "execution_mode": "paper", "error": "invalid lot size"}
    if currency_pair not in {"EURUSD", "GBPUSD", "USDJPY", None} or trade_type not in {"BUY", "SELL", None} or lots <= 0:
        return {"status": "rejected", "execution_mode": "paper", "error": "invalid paper order"}
    return {
        "status": "paper_simulated",
        "execution_mode": "paper",
        "currency_pair": currency_pair,
        "trade_type": trade_type,
        "amount": lots,
    }
