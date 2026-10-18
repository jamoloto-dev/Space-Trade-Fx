"""Institutional Pre-Trade Risk Management Gateway (SEC Rule 15c3-5 Compliant).

Enforces pre-trade risk controls required for electronic market access desks:
1. Fat-finger limits (notional capital and share quantity caps).
2. Average Daily Volume (ADV) participation caps.
3. Price sanity collars (rejecting limit orders deviating excessively from NBBO).
4. Short-sale locate verification and Reg SHO borrowing constraints.
5. Single-name and sector portfolio concentration limits.
6. Buying power and Regulation T / Portfolio Margin verification.
7. Algorithmic rate throttling to prevent runaway submission loops.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from .market_microstructure import OrderType, QuoteNBBO
from .securities import Security


class PreTradeRiskRejected(ValueError):
    """Raised when an order fails SEC Rule 15c3-5 pre-trade risk gating."""


@dataclass(frozen=True)
class PreTradeRiskConfig:
    """Configurable risk boundaries per account, strategy, or firm-wide desk."""

    max_order_notional: Decimal = Decimal("50000.00")
    max_order_quantity: Decimal = Decimal("5000.00")
    max_adv_percentage: Decimal = Decimal("2.0")  # Max 2% of 30-day ADV
    price_collar_percentage: Decimal = Decimal("5.0")  # Max 5% deviation from NBBO midpoint
    max_portfolio_leverage: Decimal = Decimal("2.0")  # 2.0x = Reg T 50% initial margin
    max_symbol_concentration_pct: Decimal = Decimal("30.0")  # Max 30% of portfolio in one symbol
    max_orders_per_minute: int = 60  # Algorithmic runaway circuit breaker
    require_short_locate: bool = True


# In-memory sliding window for rate throttling: user_id -> deque of UTC timestamps
_RATE_THROTTLE_WINDOWS: dict[str, deque[datetime]] = {}


def clear_rate_throttle_history() -> None:
    """Clear sliding windows (used for test isolation)."""
    _RATE_THROTTLE_WINDOWS.clear()


def check_algorithmic_rate_limit(user_id: str, max_orders_per_minute: int) -> None:
    """Enforce circuit breaker against algorithmic runaway order generation."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=60)

    if user_id not in _RATE_THROTTLE_WINDOWS:
        _RATE_THROTTLE_WINDOWS[user_id] = deque()

    window = _RATE_THROTTLE_WINDOWS[user_id]
    # Evict timestamps older than 60 seconds
    while window and window[0] < cutoff:
        window.popleft()

    if len(window) >= max_orders_per_minute:
        raise PreTradeRiskRejected(
            f"Algorithmic rate limit exceeded: maximum {max_orders_per_minute} orders/min permitted."
        )

    window.append(now)


def validate_pre_trade_risk(
    *,
    user_id: str,
    security: Security,
    direction: str,
    quantity: Decimal,
    order_type: OrderType,
    quote: QuoteNBBO,
    portfolio_equity: Decimal,
    limit_price: Decimal | None = None,
    existing_symbol_position: Decimal = Decimal("0"),
    open_positions_notional: Decimal = Decimal("0"),
    config: PreTradeRiskConfig | None = None,
) -> None:
    """Apply SEC Rule 15c3-5 pre-trade market access risk gating."""
    if config is None:
        config = PreTradeRiskConfig()

    direction = direction.upper()
    if direction not in {"BUY", "SELL"}:
        raise PreTradeRiskRejected(f"Invalid order direction: {direction}")
    if quantity <= 0:
        raise PreTradeRiskRejected("Order quantity must be positive")
    if portfolio_equity <= 0:
        raise PreTradeRiskRejected("Account equity must be positive to open positions")

    # 1. Algorithmic Runaway Rate Throttling
    check_algorithmic_rate_limit(user_id, config.max_orders_per_minute)

    # 2. Single-Order Quantity Cap
    if quantity > config.max_order_quantity:
        raise PreTradeRiskRejected(
            f"Order quantity {quantity} exceeds single-order limit of {config.max_order_quantity} shares/contracts."
        )

    # 3. Notional Value / Fat-Finger Check
    reference_price = limit_price if (order_type == OrderType.LIMIT and limit_price) else quote.midpoint
    order_notional = reference_price * quantity * security.contract_size
    if order_notional > config.max_order_notional:
        raise PreTradeRiskRejected(
            f"Order notional value ${order_notional:.2f} exceeds fat-finger cap of ${config.max_order_notional:.2f}."
        )

    # 4. Average Daily Volume (ADV) Participation Cap
    adv = Decimal(str(security.average_daily_volume))
    max_adv_allowed = (adv * config.max_adv_percentage) / Decimal("100")
    if quantity > max_adv_allowed:
        raise PreTradeRiskRejected(
            f"Order size {quantity} exceeds {config.max_adv_percentage}% ADV cap ({max_adv_allowed:.0f} shares)."
        )

    # 5. Price Collar / Sanity Band
    if order_type == OrderType.LIMIT and limit_price is not None:
        if limit_price <= 0:
            raise PreTradeRiskRejected("Limit price must be positive")
        mid = quote.midpoint
        if mid > 0:
            deviation_pct = (abs(limit_price - mid) / mid) * Decimal("100")
            if deviation_pct > config.price_collar_percentage:
                raise PreTradeRiskRejected(
                    f"Limit price ${limit_price} deviates {deviation_pct:.2f}% from NBBO mid (${mid}), "
                    f"exceeding collar threshold of {config.price_collar_percentage}%."
                )

    # 6. Reg SHO Short-Sale Locate Verification
    # If selling and currently flat or short, this is an opening or additive short sale
    if direction == "SELL" and existing_symbol_position <= 0:
        if not security.is_shortable:
            raise PreTradeRiskRejected(
                f"Security {security.symbol} is currently on the Hard-to-Borrow list and cannot be shorted."
            )

    # 7. Single-Stock Concentration Limit
    new_symbol_notional = (abs(existing_symbol_position) * quote.midpoint * security.contract_size) + order_notional
    max_symbol_notional = (portfolio_equity * config.max_symbol_concentration_pct) / Decimal("100")
    if new_symbol_notional > max_symbol_notional:
        raise PreTradeRiskRejected(
            f"Resulting symbol exposure (${new_symbol_notional:.2f}) exceeds "
            f"{config.max_symbol_concentration_pct}% concentration limit (${max_symbol_notional:.2f})."
        )

    # 8. Regulation T Margin & Purchasing Power Check
    required_initial_margin = order_notional * security.margin_rate
    if required_initial_margin > portfolio_equity:
        raise PreTradeRiskRejected(
            f"Required initial margin ${required_initial_margin:.2f} exceeds available equity ${portfolio_equity:.2f}."
        )
    # Maximum gross exposure allowed by portfolio leverage
    max_total_exposure = portfolio_equity * config.max_portfolio_leverage
    if open_positions_notional + order_notional > max_total_exposure:
        raise PreTradeRiskRejected(
            f"Order requires leverage exceeding maximum portfolio leverage of {config.max_portfolio_leverage}x "
            f"(Total exposure would be ${open_positions_notional + order_notional:.2f} on equity ${portfolio_equity:.2f})."
        )
