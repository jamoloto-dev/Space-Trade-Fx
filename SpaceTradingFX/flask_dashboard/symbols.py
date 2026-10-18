"""Authoritative paper-market instrument catalogue and security master integration.

Supports spot-FX and institutional US Equities/ETFs. A symbol must be present here
before it is displayed, analysed, or accepted by the order service.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .securities import SECURITY_REGISTRY


@dataclass(frozen=True)
class PaperInstrument:
    symbol: str
    pip_size: Decimal
    price_decimals: int
    contract_size: Decimal = Decimal("100000")


# Authoritative mapping populated with both FX and Equities/ETFs from the Security Master
PAPER_INSTRUMENTS: dict[str, PaperInstrument] = {
    symbol: PaperInstrument(
        symbol=sec.symbol,
        pip_size=sec.pip_size,
        price_decimals=sec.price_decimals,
        contract_size=sec.contract_size,
    )
    for symbol, sec in SECURITY_REGISTRY.items()
}

SUPPORTED_SYMBOLS = frozenset(PAPER_INSTRUMENTS)
# Alpha Vantage & broker intraday endpoints support these source intervals.
SUPPORTED_TIMEFRAMES = frozenset({"1M", "5M", "15M", "1H"})
DEFAULT_LOT_SIZE = Decimal("0.01")
DEFAULT_EQUITY_SHARES = Decimal("10")


def instrument(symbol: str) -> PaperInstrument:
    try:
        return PAPER_INSTRUMENTS[symbol.upper()]
    except KeyError as exc:
        raise ValueError(f"Unsupported paper symbol: {symbol}") from exc
