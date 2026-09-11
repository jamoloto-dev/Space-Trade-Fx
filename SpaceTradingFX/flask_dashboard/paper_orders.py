"""Pure paper-order lifecycle and deterministic risk validation rules."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

PAPER_STATES = frozenset({"draft", "validated", "open", "closing", "closed", "rejected", "failed"})
TRANSITIONS = {
    "draft": frozenset({"validated", "rejected"}),
    "validated": frozenset({"open", "rejected", "failed"}),
    "open": frozenset({"closing", "failed"}),
    "closing": frozenset({"closed", "failed"}),
    "closed": frozenset(),
    "rejected": frozenset(),
    "failed": frozenset(),
}


class InvalidPaperOrder(ValueError):
    """The order violates a pure validation or lifecycle rule."""


@dataclass(frozen=True)
class PaperOrderIntent:
    symbol: str
    direction: str
    entry_price: Decimal
    lot_size: Decimal
    stop_loss: Decimal
    take_profit: Decimal


def validate_intent(
    intent: PaperOrderIntent, *, supported_symbols: frozenset[str], max_lot_size: Decimal = Decimal("10")
) -> None:
    if intent.symbol not in supported_symbols:
        raise InvalidPaperOrder("Unsupported trading symbol")
    if intent.direction not in {"BUY", "SELL"}:
        raise InvalidPaperOrder("Trade direction must be BUY or SELL")
    if intent.entry_price <= 0 or intent.lot_size <= 0 or intent.lot_size > max_lot_size:
        raise InvalidPaperOrder("Invalid paper price or lot size")
    if intent.direction == "BUY" and not (intent.stop_loss < intent.entry_price < intent.take_profit):
        raise InvalidPaperOrder("BUY stop loss and take profit are invalid")
    if intent.direction == "SELL" and not (intent.take_profit < intent.entry_price < intent.stop_loss):
        raise InvalidPaperOrder("SELL stop loss and take profit are invalid")


def assert_transition(current: str, target: str) -> None:
    if current not in PAPER_STATES or target not in TRANSITIONS.get(current, frozenset()):
        raise InvalidPaperOrder(f"Invalid paper-order transition: {current} -> {target}")
