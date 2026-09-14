"""Authoritative paper-market instrument catalogue.

The application intentionally supports a small set of spot-FX simulations.  A
symbol must be present here before it is displayed, analysed, or accepted by
the paper order service.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class PaperInstrument:
    symbol: str
    pip_size: Decimal
    price_decimals: int
    contract_size: Decimal = Decimal("100000")


PAPER_INSTRUMENTS: dict[str, PaperInstrument] = {
    "EURUSD": PaperInstrument("EURUSD", Decimal("0.0001"), 5),
    "GBPUSD": PaperInstrument("GBPUSD", Decimal("0.0001"), 5),
    "USDJPY": PaperInstrument("USDJPY", Decimal("0.01"), 3),
    "AUDUSD": PaperInstrument("AUDUSD", Decimal("0.0001"), 5),
    "USDCAD": PaperInstrument("USDCAD", Decimal("0.0001"), 5),
    "USDCHF": PaperInstrument("USDCHF", Decimal("0.0001"), 5),
    "NZDUSD": PaperInstrument("NZDUSD", Decimal("0.0001"), 5),
}

SUPPORTED_SYMBOLS = frozenset(PAPER_INSTRUMENTS)
# Alpha Vantage's intraday endpoint supports these source intervals.  The
# application rejects rather than relabels 60-minute candles as 4H or daily.
SUPPORTED_TIMEFRAMES = frozenset({"1M", "5M", "15M", "1H"})
DEFAULT_LOT_SIZE = Decimal("0.01")


def instrument(symbol: str) -> PaperInstrument:
    try:
        return PAPER_INSTRUMENTS[symbol]
    except KeyError as exc:
        raise ValueError(f"Unsupported paper symbol: {symbol}") from exc
