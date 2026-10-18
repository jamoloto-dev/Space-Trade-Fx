"""Market Microstructure, NBBO Pricing, Order Types, and TCA Execution Model.

Simulates Central Limit Order Book (CLOB) dynamics, NBBO spread crossing,
market impact/slippage, and institutional fee schedules (SEC Section 31, FINRA TAF,
and exchange maker/taker economics).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum

from .securities import AssetClass, Security, get_security


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class TimeInForce(str, Enum):
    DAY = "DAY"
    GTC = "GTC"  # Good 'til Canceled
    IOC = "IOC"  # Immediate or Cancel
    FOK = "FOK"  # Fill or Kill


@dataclass(frozen=True)
class QuoteNBBO:
    """National Best Bid and Offer (NBBO) quote snapshot."""

    symbol: str
    bid: Decimal
    ask: Decimal
    bid_size: int = 100
    ask_size: int = 100
    timestamp: datetime = datetime.now(timezone.utc)
    venue: str = "CONSOLIDATED_SIP"

    @property
    def midpoint(self) -> Decimal:
        return ((self.bid + self.ask) / Decimal("2")).quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP)

    @property
    def spread(self) -> Decimal:
        return (self.ask - self.bid).quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP)

    @property
    def spread_bps(self) -> Decimal:
        if self.midpoint <= 0:
            return Decimal("0")
        return ((self.spread / self.midpoint) * Decimal("10000")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ExecutionFill:
    """Institutional execution report containing full TCA and fee attribution."""

    symbol: str
    direction: str  # "BUY" or "SELL"
    order_type: OrderType
    requested_quantity: Decimal
    filled_quantity: Decimal
    arrival_price: Decimal  # Prevailing mid/quote when intent entered
    fill_price: Decimal  # Actual price crossed
    slippage: Decimal  # Adverse price movement
    slippage_bps: Decimal
    gross_notional: Decimal
    sec_fee: Decimal  # SEC Section 31 fee (applies to sales)
    finra_taf: Decimal  # FINRA Trading Activity Fee (applies to sales)
    exchange_fee: Decimal  # Maker / Taker fee
    broker_commission: Decimal
    total_fees: Decimal
    net_notional: Decimal
    timestamp: datetime


# Regulatory and Transaction Fee Constants (2024-2026 Rates)
SEC_SECTION_31_RATE = Decimal("0.0000278")  # $27.80 per million dollars of sales
FINRA_TAF_RATE_PER_SHARE = Decimal("0.000166")  # Per share for equities
FINRA_TAF_MAX_PER_TRADE = Decimal("8.30")
EXCHANGE_TAKER_FEE_PER_SHARE = Decimal("0.0030")  # Standard US lit exchange taker fee
EQUITY_COMMISSION_PER_SHARE = Decimal("0.0050")  # $0.005/share institutional execution
MINIMUM_COMMISSION = Decimal("1.00")


def calculate_institutional_fees(
    security: Security,
    direction: str,
    quantity: Decimal,
    fill_price: Decimal,
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    """Calculate regulatory fees, exchange routing/taker fees, and commissions.

    Returns:
        (sec_fee, finra_taf, exchange_fee, broker_commission, total_fees)
    """
    gross_notional = (fill_price * quantity * security.contract_size).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    if security.asset_class in {AssetClass.EQUITY, AssetClass.ETF}:
        # SEC and FINRA fees apply only to sell transactions
        if direction.upper() == "SELL":
            sec_fee = (gross_notional * SEC_SECTION_31_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            taf = (quantity * FINRA_TAF_RATE_PER_SHARE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            finra_taf = min(taf, FINRA_TAF_MAX_PER_TRADE)
        else:
            sec_fee = Decimal("0.00")
            finra_taf = Decimal("0.00")

        # Exchange taker fee for crossing the spread
        exchange_fee = (quantity * EXCHANGE_TAKER_FEE_PER_SHARE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        commission = max(
            MINIMUM_COMMISSION,
            (quantity * EQUITY_COMMISSION_PER_SHARE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        )
    else:
        # OTC Forex: Regulatory exchange fees are not charged; commissions are either 0 or flat per standard lot
        sec_fee = Decimal("0.00")
        finra_taf = Decimal("0.00")
        exchange_fee = Decimal("0.00")
        commission = (quantity * Decimal("2.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)  # $2/lot

    total_fees = sec_fee + finra_taf + exchange_fee + commission
    return sec_fee, finra_taf, exchange_fee, commission, total_fees


def calculate_slippage(
    security: Security,
    direction: str,
    quantity: Decimal,
    quote: QuoteNBBO,
) -> Decimal:
    """Model dynamic market impact slippage based on square-root participation law."""
    adv = Decimal(str(security.average_daily_volume))
    if adv <= 0:
        adv = Decimal("10000000")

    participation_rate = quantity / adv
    # Impact = spread * (0.5 + sqrt(participation_rate) * 10)
    try:
        sqrt_factor = Decimal(str(round(math.sqrt(float(participation_rate)), 6)))
    except (ValueError, TypeError):
        sqrt_factor = Decimal("0.001")

    base_impact = (quote.spread * Decimal("0.50")) + (quote.midpoint * sqrt_factor * Decimal("0.01"))
    # Minimum slippage is half the tick size
    min_slippage = (security.tick_size / Decimal("2")).quantize(security.tick_size)
    return max(min_slippage, base_impact).quantize(security.tick_size, rounding=ROUND_HALF_UP)


def simulate_market_fill(
    quote: QuoteNBBO,
    direction: str,
    quantity: Decimal,
    order_type: OrderType = OrderType.MARKET,
    limit_price: Decimal | None = None,
) -> ExecutionFill:
    """Simulate institutional order execution against the NBBO."""
    direction = direction.upper()
    if direction not in {"BUY", "SELL"}:
        raise ValueError("Invalid trade direction: must be BUY or SELL")
    if quantity <= 0:
        raise ValueError("Quantity must be positive")

    security = get_security(quote.symbol)
    arrival_price = quote.midpoint
    slippage = calculate_slippage(security, direction, quantity, quote)

    if direction == "BUY":
        # Buyer crosses the spread to the Ask + adverse slippage
        raw_fill_price = quote.ask + slippage
        if order_type == OrderType.LIMIT and limit_price is not None:
            if raw_fill_price > limit_price:
                # Fill capped at limit price or rejected if ask > limit
                if quote.ask > limit_price:
                    raise ValueError(f"Limit price {limit_price} is lower than Ask {quote.ask}; cannot fill BUY order.")
                raw_fill_price = limit_price
        fill_price = raw_fill_price.quantize(security.tick_size, rounding=ROUND_HALF_UP)
        adverse_slippage = fill_price - quote.ask
    else:
        # Seller crosses the spread to the Bid - adverse slippage
        raw_fill_price = quote.bid - slippage
        if order_type == OrderType.LIMIT and limit_price is not None:
            if raw_fill_price < limit_price:
                if quote.bid < limit_price:
                    raise ValueError(
                        f"Limit price {limit_price} is higher than Bid {quote.bid}; cannot fill SELL order."
                    )
                raw_fill_price = limit_price
        fill_price = max(security.tick_size, raw_fill_price.quantize(security.tick_size, rounding=ROUND_HALF_UP))
        adverse_slippage = quote.bid - fill_price

    slippage_bps = (
        ((adverse_slippage / arrival_price) * Decimal("10000")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if arrival_price > 0
        else Decimal("0")
    )

    gross_notional = (fill_price * quantity * security.contract_size).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sec_fee, finra_taf, exchange_fee, commission, total_fees = calculate_institutional_fees(
        security, direction, quantity, fill_price
    )

    net_notional = (gross_notional + total_fees) if direction == "BUY" else (gross_notional - total_fees)

    return ExecutionFill(
        symbol=quote.symbol,
        direction=direction,
        order_type=order_type,
        requested_quantity=quantity,
        filled_quantity=quantity,
        arrival_price=arrival_price,
        fill_price=fill_price,
        slippage=adverse_slippage,
        slippage_bps=slippage_bps,
        gross_notional=gross_notional,
        sec_fee=sec_fee,
        finra_taf=finra_taf,
        exchange_fee=exchange_fee,
        broker_commission=commission,
        total_fees=total_fees,
        net_notional=net_notional,
        timestamp=datetime.now(timezone.utc),
    )
