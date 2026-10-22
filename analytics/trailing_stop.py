"""Automated Break-Even & Dynamic Trailing Stop Manager.

Evaluates open positions in real-time, locks in risk-free break-even stops once
profit thresholds are achieved, and prevents premature downside risk on reversals.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("TrailingStopManager")


class TrailingStopManager:
    """Automated Break-Even and Trailing Stop Loss Manager."""

    def __init__(self, trigger_pips: float = 20.0, buffer_pips: float = 2.0):
        self.trigger_pips = float(trigger_pips)
        self.buffer_pips = float(buffer_pips)
        self.modified_tickets: set[str] = set()

    def evaluate_and_trail(
        self,
        position: dict[str, Any],
        current_market_price: float,
        pip_size: float | None = None,
        digits: int = 5,
    ) -> dict[str, Any]:
        """Evaluates if a position qualifies to move its stop loss to break-even (+ buffer).

        Parameters
        ----------
        position : dict
            Dictionary containing position metadata (id, type, openPrice, stopLoss, symbol, etc.)
        current_market_price : float
            Current bid (for BUY) or ask (for SELL) market price.
        pip_size : float, optional
            Pip size for the asset (e.g., 0.0001 for EURUSD, 0.01 for USDJPY).
        digits : int, default 5
            Number of decimal places for rounding price levels.

        Returns
        -------
        dict
            Evaluation summary with 'should_modify', 'new_stop_loss', 'profit_pips', etc.
        """
        ticket = str(position.get("id") or position.get("ticket") or "")
        pos_type = str(position.get("type", "BUY")).upper()
        symbol = str(position.get("symbol", ""))
        open_price = float(position.get("openPrice", 0.0))
        current_sl = float(position.get("stopLoss") or 0.0)
        current_tp = position.get("takeProfit")

        if open_price <= 0:
            return {
                "ticket": ticket,
                "symbol": symbol,
                "should_modify": False,
                "new_stop_loss": current_sl,
                "profit_pips": 0.0,
                "reason": "Invalid position entry price",
            }

        # Resolve pip size if not provided
        if pip_size is None or pip_size <= 0:
            raw_sym = symbol.split(".")[0].upper()
            if "JPY" in raw_sym or "XAU" in raw_sym or digits <= 3:
                resolved_pip_size = 0.01
            else:
                resolved_pip_size = 0.0001
        else:
            resolved_pip_size = float(pip_size)

        is_buy = "BUY" in pos_type
        should_modify = False
        new_sl = current_sl
        reason = "Profit threshold not reached"

        if is_buy:
            profit_pips = (current_market_price - open_price) / resolved_pip_size
            target_break_even = round(open_price + (self.buffer_pips * resolved_pip_size), digits)

            # Trigger condition: profit >= trigger and SL not yet at or beyond break-even
            if profit_pips >= self.trigger_pips and (current_sl == 0.0 or current_sl < target_break_even):
                new_sl = target_break_even
                should_modify = True
                reason = (
                    f"BUY profit (+{profit_pips:.1f} pips) >= trigger ({self.trigger_pips:.1f} pips). "
                    f"Locking Break-Even SL at {target_break_even:.{digits}f} (+{self.buffer_pips:.1f} buffer pips)."
                )
        else:
            profit_pips = (open_price - current_market_price) / resolved_pip_size
            target_break_even = round(open_price - (self.buffer_pips * resolved_pip_size), digits)

            # Trigger condition: profit >= trigger and SL not yet at or beyond break-even
            if profit_pips >= self.trigger_pips and (current_sl == 0.0 or current_sl > target_break_even):
                new_sl = target_break_even
                should_modify = True
                reason = (
                    f"SELL profit (+{profit_pips:.1f} pips) >= trigger ({self.trigger_pips:.1f} pips). "
                    f"Locking Break-Even SL at {target_break_even:.{digits}f} (+{self.buffer_pips:.1f} buffer pips)."
                )

        if should_modify and ticket:
            self.modified_tickets.add(ticket)

        return {
            "ticket": ticket,
            "symbol": symbol,
            "direction": "BUY" if is_buy else "SELL",
            "open_price": open_price,
            "current_price": current_market_price,
            "current_sl": current_sl,
            "current_tp": float(current_tp) if current_tp is not None else None,
            "new_stop_loss": new_sl,
            "profit_pips": round(profit_pips, 1),
            "should_modify": should_modify,
            "reason": reason,
        }

    def mark_modified(self, ticket: str) -> None:
        """Mark a ticket as having already been modified to break-even."""
        if ticket:
            self.modified_tickets.add(str(ticket))

    def is_already_modified(self, ticket: str) -> bool:
        """Check if a ticket has already had its break-even stop applied."""
        return str(ticket) in self.modified_tickets

    def clear_ticket(self, ticket: str) -> None:
        """Clear a closed ticket from modified tracking."""
        self.modified_tickets.discard(str(ticket))
