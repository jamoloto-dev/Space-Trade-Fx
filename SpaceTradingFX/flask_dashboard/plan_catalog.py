"""The single, canonical license plan catalogue.

Price and entitlement changes belong here.  Payment, licensing, referral and
presentation code consume this module rather than maintaining their own copy.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Plan:
    code: str
    price_usd: Decimal
    duration_days: int
    max_active_trades: int
    features: tuple[str, ...]

    @property
    def stripe_price_id(self) -> str:
        return os.environ.get(f"STRIPE_PRICE_{self.code.upper()}", "")

    @property
    def price_cents(self) -> int:
        return int(self.price_usd * 100)


PLANS: dict[str, Plan] = {
    "basic": Plan("basic", Decimal("29.99"), 30, 3, ("basic_signals", "paper_trading")),
    "premium": Plan("premium", Decimal("99.99"), 30, 10, ("advanced_signals", "paper_trading", "email_alerts")),
    "professional": Plan("professional", Decimal("199.99"), 30, 50, ("advanced_signals", "paper_trading", "email_alerts", "priority_support", "custom_strategies")),
}


def get_plan(code: str) -> Plan:
    try:
        return PLANS[code]
    except KeyError as exc:
        raise ValueError("Invalid license plan") from exc


def public_plan_catalog() -> dict[str, dict[str, object]]:
    return {
        code: {
            "price": str(plan.price_usd),
            "duration_days": plan.duration_days,
            "max_trades": plan.max_active_trades,
            "features": list(plan.features),
        }
        for code, plan in PLANS.items()
    }
