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


CORE_TRADING_PAIRS = ["USDJPY", "GBPUSD", "EURUSD", "XAUUSD", "USDZAR"]

# Authoritative mapping populated with strictly the 5 core FX pairs
PAPER_INSTRUMENTS: dict[str, PaperInstrument] = {
    symbol: PaperInstrument(
        symbol=sec.symbol,
        pip_size=sec.pip_size,
        price_decimals=sec.price_decimals,
        contract_size=sec.contract_size,
    )
    for symbol, sec in SECURITY_REGISTRY.items()
    if symbol in CORE_TRADING_PAIRS
}

SUPPORTED_SYMBOLS = frozenset(CORE_TRADING_PAIRS)
DEFAULT_MONITORED_PAIRS = ["EURUSD", "GBPUSD", "USDJPY"]
# Alpha Vantage & broker intraday endpoints support these source intervals.
SUPPORTED_TIMEFRAMES = frozenset({"1M", "5M", "15M", "1H"})
DEFAULT_LOT_SIZE = Decimal("0.01")
DEFAULT_EQUITY_SHARES = Decimal("10")


def instrument(symbol: str) -> PaperInstrument:
    sym = symbol.upper()
    if sym in PAPER_INSTRUMENTS:
        return PAPER_INSTRUMENTS[sym]
    if sym in SECURITY_REGISTRY:
        sec = SECURITY_REGISTRY[sym]
        return PaperInstrument(
            symbol=sec.symbol,
            pip_size=sec.pip_size,
            price_decimals=sec.price_decimals,
            contract_size=sec.contract_size,
        )
    raise ValueError(f"Unsupported paper symbol: {symbol}")
