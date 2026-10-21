"""Authoritative Institutional Security Master and Asset Class Taxonomy.

Provides polymorphic security definitions for Equities, ETFs, and Forex,
incorporating exchange metadata, tick sizes, Reg T / Portfolio Margin rates,
Reg SHO short-locate parameters, T+1 settlement cycles, and corporate actions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any


class AssetClass(str, Enum):
    EQUITY = "EQUITY"
    ETF = "ETF"
    FOREX = "FOREX"
    INDEX = "INDEX"


class MarketHours(str, Enum):
    REGULAR_US = "09:30-16:00 ET"
    EXTENDED_US = "04:00-20:00 ET"
    CONTINUOUS_24_5 = "24/5 OTC"


class CorporateActionType(str, Enum):
    STOCK_SPLIT = "STOCK_SPLIT"
    REVERSE_SPLIT = "REVERSE_SPLIT"
    CASH_DIVIDEND = "CASH_DIVIDEND"
    SPINOFF = "SPINOFF"


@dataclass(frozen=True)
class CorporateAction:
    symbol: str
    action_type: CorporateActionType
    effective_date: date
    ratio: Decimal  # Split multiplier (e.g., Decimal("2.0") for 2:1) or dividend per share
    description: str = ""


@dataclass(frozen=True)
class Security:
    symbol: str
    name: str
    asset_class: AssetClass
    exchange: str
    currency: str = "USD"
    cusip: str | None = None
    isin: str | None = None
    tick_size: Decimal = Decimal("0.01")
    price_decimals: int = 2
    contract_size: Decimal = Decimal("1")
    pip_size: Decimal = Decimal("0.01")
    min_order_size: Decimal = Decimal("1")
    max_order_size: Decimal = Decimal("100000")
    margin_rate: Decimal = Decimal("0.50")  # 50% initial margin (Reg T standard)
    maintenance_margin_rate: Decimal = Decimal("0.25")  # 25% FINRA maintenance margin
    is_shortable: bool = True
    borrow_fee_annual: Decimal = Decimal("0.005")  # 0.5% annual borrow rate
    settlement_days: int = 1  # US Equities transitioned to T+1 in May 2024
    average_daily_volume: int = 10_000_000
    sector: str | None = None


# Institutional Security Master Registry
SECURITY_REGISTRY: dict[str, Security] = {
    # Liquid US Equities
    "AAPL": Security(
        symbol="AAPL",
        name="Apple Inc.",
        asset_class=AssetClass.EQUITY,
        exchange="NASDAQ",
        cusip="037833100",
        isin="US0378331005",
        tick_size=Decimal("0.01"),
        price_decimals=2,
        contract_size=Decimal("1"),
        pip_size=Decimal("0.01"),
        min_order_size=Decimal("1"),
        max_order_size=Decimal("50000"),
        margin_rate=Decimal("0.50"),
        maintenance_margin_rate=Decimal("0.25"),
        is_shortable=True,
        borrow_fee_annual=Decimal("0.003"),
        settlement_days=1,
        average_daily_volume=55_000_000,
        sector="Technology",
    ),
    "MSFT": Security(
        symbol="MSFT",
        name="Microsoft Corporation",
        asset_class=AssetClass.EQUITY,
        exchange="NASDAQ",
        cusip="594918104",
        isin="US5949181045",
        tick_size=Decimal("0.01"),
        price_decimals=2,
        contract_size=Decimal("1"),
        pip_size=Decimal("0.01"),
        min_order_size=Decimal("1"),
        max_order_size=Decimal("50000"),
        margin_rate=Decimal("0.50"),
        maintenance_margin_rate=Decimal("0.25"),
        is_shortable=True,
        borrow_fee_annual=Decimal("0.003"),
        settlement_days=1,
        average_daily_volume=22_000_000,
        sector="Technology",
    ),
    "NVDA": Security(
        symbol="NVDA",
        name="NVIDIA Corporation",
        asset_class=AssetClass.EQUITY,
        exchange="NASDAQ",
        cusip="67066G104",
        isin="US67066G1040",
        tick_size=Decimal("0.01"),
        price_decimals=2,
        contract_size=Decimal("1"),
        pip_size=Decimal("0.01"),
        min_order_size=Decimal("1"),
        max_order_size=Decimal("50000"),
        margin_rate=Decimal("0.50"),
        maintenance_margin_rate=Decimal("0.25"),
        is_shortable=True,
        borrow_fee_annual=Decimal("0.004"),
        settlement_days=1,
        average_daily_volume=45_000_000,
        sector="Technology",
    ),
    "AMZN": Security(
        symbol="AMZN",
        name="Amazon.com, Inc.",
        asset_class=AssetClass.EQUITY,
        exchange="NASDAQ",
        cusip="023135106",
        isin="US0231351067",
        tick_size=Decimal("0.01"),
        price_decimals=2,
        contract_size=Decimal("1"),
        pip_size=Decimal("0.01"),
        min_order_size=Decimal("1"),
        max_order_size=Decimal("50000"),
        margin_rate=Decimal("0.50"),
        maintenance_margin_rate=Decimal("0.25"),
        is_shortable=True,
        borrow_fee_annual=Decimal("0.003"),
        settlement_days=1,
        average_daily_volume=35_000_000,
        sector="Consumer Discretionary",
    ),
    "TSLA": Security(
        symbol="TSLA",
        name="Tesla, Inc.",
        asset_class=AssetClass.EQUITY,
        exchange="NASDAQ",
        cusip="88160R101",
        isin="US88160R1014",
        tick_size=Decimal("0.01"),
        price_decimals=2,
        contract_size=Decimal("1"),
        pip_size=Decimal("0.01"),
        min_order_size=Decimal("1"),
        max_order_size=Decimal("50000"),
        margin_rate=Decimal("0.50"),
        maintenance_margin_rate=Decimal("0.30"),
        is_shortable=True,
        borrow_fee_annual=Decimal("0.006"),
        settlement_days=1,
        average_daily_volume=70_000_000,
        sector="Consumer Discretionary",
    ),
    # Broad-Market Benchmarks & ETFs
    "SPY": Security(
        symbol="SPY",
        name="SPDR S&P 500 ETF Trust",
        asset_class=AssetClass.ETF,
        exchange="NYSE ARCA",
        cusip="78462F103",
        isin="US78462F1030",
        tick_size=Decimal("0.01"),
        price_decimals=2,
        contract_size=Decimal("1"),
        pip_size=Decimal("0.01"),
        min_order_size=Decimal("1"),
        max_order_size=Decimal("100000"),
        margin_rate=Decimal("0.30"),  # Highly liquid ETF eligible for lower margin
        maintenance_margin_rate=Decimal("0.15"),
        is_shortable=True,
        borrow_fee_annual=Decimal("0.0025"),
        settlement_days=1,
        average_daily_volume=65_000_000,
        sector="Broad Market",
    ),
    "QQQ": Security(
        symbol="QQQ",
        name="Invesco QQQ Trust (Nasdaq-100)",
        asset_class=AssetClass.ETF,
        exchange="NASDAQ",
        cusip="46090E103",
        isin="US46090E1038",
        tick_size=Decimal("0.01"),
        price_decimals=2,
        contract_size=Decimal("1"),
        pip_size=Decimal("0.01"),
        min_order_size=Decimal("1"),
        max_order_size=Decimal("100000"),
        margin_rate=Decimal("0.30"),
        maintenance_margin_rate=Decimal("0.15"),
        is_shortable=True,
        borrow_fee_annual=Decimal("0.0025"),
        settlement_days=1,
        average_daily_volume=45_000_000,
        sector="Broad Market Technology",
    ),
    # Currencies (Retaining full backwards compatibility)
    "EURUSD": Security(
        symbol="EURUSD",
        name="Euro / US Dollar",
        asset_class=AssetClass.FOREX,
        exchange="OTC",
        tick_size=Decimal("0.00001"),
        price_decimals=5,
        contract_size=Decimal("100000"),
        pip_size=Decimal("0.0001"),
        min_order_size=Decimal("0.01"),
        max_order_size=Decimal("100"),
        margin_rate=Decimal("0.02"),  # 50:1 leverage = 2% margin
        maintenance_margin_rate=Decimal("0.01"),
        is_shortable=True,
        borrow_fee_annual=Decimal("0"),
        settlement_days=2,
        average_daily_volume=500_000_000,
        sector="G10 FX",
    ),
    "GBPUSD": Security(
        symbol="GBPUSD",
        name="British Pound / US Dollar",
        asset_class=AssetClass.FOREX,
        exchange="OTC",
        tick_size=Decimal("0.00001"),
        price_decimals=5,
        contract_size=Decimal("100000"),
        pip_size=Decimal("0.0001"),
        min_order_size=Decimal("0.01"),
        max_order_size=Decimal("100"),
        margin_rate=Decimal("0.02"),
        maintenance_margin_rate=Decimal("0.01"),
        is_shortable=True,
        borrow_fee_annual=Decimal("0"),
        settlement_days=2,
        average_daily_volume=300_000_000,
        sector="G10 FX",
    ),
    "USDJPY": Security(
        symbol="USDJPY",
        name="US Dollar / Japanese Yen",
        asset_class=AssetClass.FOREX,
        exchange="OTC",
        tick_size=Decimal("0.001"),
        price_decimals=3,
        contract_size=Decimal("100000"),
        pip_size=Decimal("0.01"),
        min_order_size=Decimal("0.01"),
        max_order_size=Decimal("100"),
        margin_rate=Decimal("0.02"),
        maintenance_margin_rate=Decimal("0.01"),
        is_shortable=True,
        borrow_fee_annual=Decimal("0"),
        settlement_days=2,
        average_daily_volume=400_000_000,
        sector="G10 FX",
    ),
    "AUDUSD": Security(
        symbol="AUDUSD",
        name="Australian Dollar / US Dollar",
        asset_class=AssetClass.FOREX,
        exchange="OTC",
        tick_size=Decimal("0.00001"),
        price_decimals=5,
        contract_size=Decimal("100000"),
        pip_size=Decimal("0.0001"),
        min_order_size=Decimal("0.01"),
        max_order_size=Decimal("100"),
        margin_rate=Decimal("0.02"),
        maintenance_margin_rate=Decimal("0.01"),
        is_shortable=True,
        borrow_fee_annual=Decimal("0"),
        settlement_days=2,
        average_daily_volume=200_000_000,
        sector="G10 FX",
    ),
    "USDCAD": Security(
        symbol="USDCAD",
        name="US Dollar / Canadian Dollar",
        asset_class=AssetClass.FOREX,
        exchange="OTC",
        tick_size=Decimal("0.00001"),
        price_decimals=5,
        contract_size=Decimal("100000"),
        pip_size=Decimal("0.0001"),
        min_order_size=Decimal("0.01"),
        max_order_size=Decimal("100"),
        margin_rate=Decimal("0.02"),
        maintenance_margin_rate=Decimal("0.01"),
        is_shortable=True,
        borrow_fee_annual=Decimal("0"),
        settlement_days=2,
        average_daily_volume=200_000_000,
        sector="G10 FX",
    ),
    "USDCHF": Security(
        symbol="USDCHF",
        name="US Dollar / Swiss Franc",
        asset_class=AssetClass.FOREX,
        exchange="OTC",
        tick_size=Decimal("0.00001"),
        price_decimals=5,
        contract_size=Decimal("100000"),
        pip_size=Decimal("0.0001"),
        min_order_size=Decimal("0.01"),
        max_order_size=Decimal("100"),
        margin_rate=Decimal("0.02"),
        maintenance_margin_rate=Decimal("0.01"),
        is_shortable=True,
        borrow_fee_annual=Decimal("0"),
        settlement_days=2,
        average_daily_volume=150_000_000,
        sector="G10 FX",
    ),
    "NZDUSD": Security(
        symbol="NZDUSD",
        name="New Zealand Dollar / US Dollar",
        asset_class=AssetClass.FOREX,
        exchange="OTC",
        tick_size=Decimal("0.00001"),
        price_decimals=5,
        contract_size=Decimal("100000"),
        pip_size=Decimal("0.0001"),
        min_order_size=Decimal("0.01"),
        max_order_size=Decimal("100"),
        margin_rate=Decimal("0.02"),
        maintenance_margin_rate=Decimal("0.01"),
        is_shortable=True,
        borrow_fee_annual=Decimal("0"),
        settlement_days=2,
        average_daily_volume=100_000_000,
        sector="G10 FX",
    ),
    "XAUUSD": Security(
        symbol="XAUUSD",
        name="Gold / US Dollar",
        asset_class=AssetClass.FOREX,
        exchange="OTC",
        tick_size=Decimal("0.01"),
        price_decimals=2,
        contract_size=Decimal("100"),
        pip_size=Decimal("0.10"),
        min_order_size=Decimal("0.01"),
        max_order_size=Decimal("100"),
        margin_rate=Decimal("0.05"),
        maintenance_margin_rate=Decimal("0.03"),
        is_shortable=True,
        borrow_fee_annual=Decimal("0"),
        settlement_days=2,
        average_daily_volume=450_000_000,
        sector="Commodities",
    ),
    "USDZAR": Security(
        symbol="USDZAR",
        name="US Dollar / South African Rand",
        asset_class=AssetClass.FOREX,
        exchange="OTC",
        tick_size=Decimal("0.0001"),
        price_decimals=4,
        contract_size=Decimal("100000"),
        pip_size=Decimal("0.001"),
        min_order_size=Decimal("0.01"),
        max_order_size=Decimal("100"),
        margin_rate=Decimal("0.05"),
        maintenance_margin_rate=Decimal("0.03"),
        is_shortable=True,
        borrow_fee_annual=Decimal("0"),
        settlement_days=2,
        average_daily_volume=80_000_000,
        sector="Emerging Market FX",
    ),
}


def get_security(symbol: str) -> Security:
    """Retrieve security specifications from the authoritative security master."""
    try:
        return SECURITY_REGISTRY[symbol.upper()]
    except KeyError as exc:
        raise ValueError(f"Unknown or unsupported security symbol: {symbol}") from exc


def is_supported_security(symbol: str) -> bool:
    """Check if the given ticker or currency pair is supported."""
    return symbol.upper() in SECURITY_REGISTRY


def apply_corporate_action_to_candle(
    candle: dict[str, Any],
    action: CorporateAction,
) -> dict[str, Any]:
    """Adjust historical OHLCV data for stock splits or dividends backward in time."""
    adjusted = dict(candle)
    ratio = action.ratio
    if action.action_type in {CorporateActionType.STOCK_SPLIT, CorporateActionType.REVERSE_SPLIT}:
        for price_field in ("open", "high", "low", "close"):
            if price_field in adjusted:
                adjusted[price_field] = (Decimal(str(adjusted[price_field])) / ratio).quantize(Decimal("0.0001"))
        if "volume" in adjusted:
            adjusted["volume"] = int(Decimal(str(adjusted["volume"])) * ratio)
    elif action.action_type == CorporateActionType.CASH_DIVIDEND:
        for price_field in ("open", "high", "low", "close"):
            if price_field in adjusted:
                adjusted[price_field] = max(Decimal("0.01"), Decimal(str(adjusted[price_field])) - ratio).quantize(
                    Decimal("0.0001")
                )
    return adjusted
