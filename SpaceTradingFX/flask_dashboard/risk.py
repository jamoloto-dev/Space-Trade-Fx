"""Deterministic, paper-only risk gate.

All quantities are lots.  P/L and daily-loss limits are *simulated account
units*, not broker-reported cash; the simulator has no FX conversion feed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from flask import current_app

from .models import License, Trade, TradingPreference


class PaperRiskRejected(ValueError):
    """A paper intent failed deterministic policy."""


@dataclass(frozen=True)
class PaperRiskLimits:
    max_lot_size: Decimal = Decimal("1.00")
    max_total_lots: Decimal = Decimal("3.00")
    max_daily_loss: Decimal = Decimal("250.00")
    account_equity: Decimal = Decimal("10000.00")


def risk_limits(preferences: TradingPreference) -> PaperRiskLimits:
    configured = (preferences.strategy_settings or {}).get("risk_controls", {})
    try:
        limits = PaperRiskLimits(
            max_lot_size=Decimal(str(configured.get("max_lot_size", "1.00"))),
            max_total_lots=Decimal(str(configured.get("max_total_lots", "3.00"))),
            max_daily_loss=Decimal(str(configured.get("max_daily_loss", "250.00"))),
            account_equity=Decimal(str(configured.get("account_equity", "10000.00"))),
        )
    except Exception as exc:
        raise PaperRiskRejected("Paper risk controls contain an invalid value") from exc
    if min(limits.max_lot_size, limits.max_total_lots, limits.max_daily_loss, limits.account_equity) <= 0:
        raise PaperRiskRejected("Paper risk controls must be positive")
    return limits


def assert_paper_intent_allowed(
    *, user_id: str, preferences: TradingPreference, lot_size: Decimal, planned_loss: Decimal, submission_mode: str
) -> None:
    """Apply every new paper intent's kill, pause, position, exposure and loss checks."""
    if current_app.config.get("PAPER_TRADING_KILL_SWITCH"):
        raise PaperRiskRejected("Paper trading is temporarily disabled by the kill switch")
    if not preferences.trading_enabled:
        raise PaperRiskRejected("Paper trading is paused in preferences")
    if submission_mode == "automated" and not (preferences.strategy_settings or {}).get(
        "automated_paper_trading", False
    ):
        raise PaperRiskRejected("Automated paper trading is disabled in preferences")
    if submission_mode not in {"manual", "automated"}:
        raise PaperRiskRejected("Invalid paper submission mode")

    limits = risk_limits(preferences)
    if lot_size <= 0 or lot_size > limits.max_lot_size:
        raise PaperRiskRejected("Paper lot size exceeds the configured per-position limit")
    if planned_loss < 0:
        raise PaperRiskRejected("Paper planned loss is invalid")
    maximum_position_loss = limits.account_equity * Decimal(str(preferences.risk_percentage)) / Decimal("100")
    if planned_loss > maximum_position_loss:
        raise PaperRiskRejected("Paper stop-loss exposure exceeds the configured risk percentage")

    open_trades = Trade.query.filter_by(user_id=user_id, status="open").all()
    license_obj = License.query.filter_by(user_id=user_id, status="active").order_by(License.expires_at.desc()).first()
    license_limit = license_obj.max_active_trades if license_obj else preferences.max_concurrent_trades
    position_limit = min(preferences.max_concurrent_trades, license_limit)
    if len(open_trades) >= position_limit:
        raise PaperRiskRejected("Paper active-trade limit reached")
    if sum((trade.lot_size for trade in open_trades), Decimal("0")) + lot_size > limits.max_total_lots:
        raise PaperRiskRejected("Paper total exposure limit reached")

    today = datetime.now(timezone.utc).date()

    def is_today(trade: Trade) -> bool:
        if not trade.closed_at:
            return False
        closed_at = trade.closed_at
        if closed_at.tzinfo is None:  # SQLite can return naive timestamps.
            closed_at = closed_at.replace(tzinfo=timezone.utc)
        return closed_at.astimezone(timezone.utc).date() == today

    daily_losses = sum(
        (
            -trade.profit_loss
            for trade in Trade.query.filter_by(user_id=user_id, status="closed").all()
            if is_today(trade) and trade.profit_loss < 0
        ),
        Decimal("0"),
    )
    if daily_losses >= limits.max_daily_loss:
        raise PaperRiskRejected("Paper daily-loss limit reached")
