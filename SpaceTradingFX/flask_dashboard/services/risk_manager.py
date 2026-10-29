"""
Space-Trade-Fx Centralized Institutional Risk Manager.

Provides institutional risk guardrails, pre-trade risk evaluation,
daily drawdown circuit breakers, news blackout vetoes, and spread spike protection.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .execution_broker import ExecutionBroker, OrderIntent

logger = logging.getLogger("space_trading_fx.risk_manager")


@dataclass
class RiskLimits:
    """Configurable risk limit parameters."""

    max_daily_drawdown_pct: float = 5.0
    max_open_positions: int = 3
    max_total_lot_size: float = 1.0
    max_spread_multiplier: float = 2.5
    news_blackout_minutes: int = 15
    baseline_typical_spreads: dict[str, float] = field(
        default_factory=lambda: {
            "EURUSD": 0.00015,
            "GBPUSD": 0.00020,
            "USDJPY": 0.020,
            "USDZAR": 0.0150,
            "XAUUSD": 0.35,
        }
    )


@dataclass
class RiskAssessmentResult:
    """Outcome of pre-trade risk evaluation."""

    allowed: bool
    reasons: list[str] = field(default_factory=list)
    circuit_breaker_active: bool = False
    daily_drawdown_pct: float = 0.0


class SpaceTradeRiskManager:
    """
    Centralized Institutional Risk Guardrails for Space-Trade-Fx.
    """

    def __init__(self, limits: RiskLimits | None = None) -> None:
        self.limits = limits or RiskLimits()
        self.circuit_breaker_tripped = False
        self.circuit_breaker_reason = ""
        self.circuit_breaker_tripped_at: str | None = None
        self.daily_starting_balance: float | None = None
        self.daily_anchor_date: str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _check_and_update_daily_anchor(self, current_balance: float) -> None:
        """Reset starting balance anchor at UTC midnight rollover."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.daily_anchor_date != today or self.daily_starting_balance is None:
            self.daily_anchor_date = today
            self.daily_starting_balance = current_balance
            if self.circuit_breaker_tripped:
                logger.info("Space-Trade-Fx RiskManager: UTC Day rollover; auto-resetting daily circuit breaker.")
                self.reset_circuit_breaker()

    def check_circuit_breaker(self, telemetry: Any) -> tuple[bool, float]:
        """
        Evaluate current equity against daily starting balance.
        Trips breaker if daily drawdown >= limit (default 5.0%).
        """
        if self.circuit_breaker_tripped:
            return True, self.limits.max_daily_drawdown_pct

        balance = getattr(telemetry, "balance", 0.0)
        equity = getattr(telemetry, "equity", balance)

        self._check_and_update_daily_anchor(balance)
        start_bal = self.daily_starting_balance or balance

        if start_bal <= 0:
            return False, 0.0

        drawdown_pct = max(0.0, (start_bal - equity) / start_bal * 100.0)

        if drawdown_pct >= self.limits.max_daily_drawdown_pct:
            self.circuit_breaker_tripped = True
            self.circuit_breaker_reason = (
                f"Daily drawdown {drawdown_pct:.2f}% breached {self.limits.max_daily_drawdown_pct}% limit."
            )
            self.circuit_breaker_tripped_at = datetime.now(timezone.utc).isoformat()
            logger.warning(f"Space-Trade-Fx CIRCUIT BREAKER TRIPPED: {self.circuit_breaker_reason}")
            return True, drawdown_pct

        return False, drawdown_pct

    def reset_circuit_breaker(self) -> None:
        """Manually or automatically reset the circuit breaker."""
        self.circuit_breaker_tripped = False
        self.circuit_breaker_reason = ""
        self.circuit_breaker_tripped_at = None

    def check_news_blackout(self, symbol: str, direction: str = "BUY") -> bool:
        """Check if symbol is currently subject to high-impact macro news veto."""
        try:
            from .news_intelligence import check_ai_veto

            is_vetoed, _ = check_ai_veto(symbol, direction)
            return bool(is_vetoed)
        except Exception:
            return False

    def check_spread_expansion(self, symbol: str, live_spread: float | None) -> bool:
        """Check if live spread exceeds typical baseline by more than threshold multiplier."""
        if live_spread is None or live_spread <= 0:
            return False

        sym_upper = symbol.upper()
        typical = self.limits.baseline_typical_spreads.get(sym_upper)
        if not typical:
            return False

        max_allowed = typical * self.limits.max_spread_multiplier
        if live_spread > max_allowed:
            logger.warning(
                f"Space-Trade-Fx Spread Veto: {sym_upper} spread {live_spread:.5f} > max allowed {max_allowed:.5f}"
            )
            return True

        return False

    def evaluate_pre_trade_risk(
        self,
        intent: OrderIntent,
        broker: ExecutionBroker,
        live_spread: float | None = None,
    ) -> RiskAssessmentResult:
        """
        Evaluate full pre-trade risk criteria:
        1. Circuit breaker status
        2. Maximum concurrent positions
        3. Maximum cumulative lot size
        4. Spread expansion veto
        5. Macro news blackout veto
        """
        reasons: list[str] = []
        telemetry = broker.get_telemetry()
        is_tripped, dd_pct = self.check_circuit_breaker(telemetry)

        if is_tripped:
            return RiskAssessmentResult(
                allowed=False,
                reasons=[f"Circuit breaker active: {self.circuit_breaker_reason}"],
                circuit_breaker_active=True,
                daily_drawdown_pct=dd_pct,
            )

        positions = broker.get_positions()

        # Check maximum position count
        if len(positions) >= self.limits.max_open_positions:
            reasons.append(f"Maximum open positions limit reached: {len(positions)}/{self.limits.max_open_positions}")

        # Check maximum total open volume
        total_open_lots = sum(p.lot_size for p in positions) + float(intent.lot_size)
        if total_open_lots > self.limits.max_total_lot_size:
            reasons.append(f"Total open lots {total_open_lots:.2f} exceeds limit {self.limits.max_total_lot_size:.2f}")

        # Check spread expansion
        if self.check_spread_expansion(intent.symbol, live_spread):
            reasons.append(f"Spread expansion veto: Live spread on {intent.symbol} exceeds threshold multiplier.")

        # Check news blackout
        if self.check_news_blackout(intent.symbol, intent.trade_type):
            reasons.append(f"Macro news veto: {intent.symbol} in high-impact volatility window.")

        allowed = len(reasons) == 0
        return RiskAssessmentResult(
            allowed=allowed,
            reasons=reasons,
            circuit_breaker_active=False,
            daily_drawdown_pct=dd_pct,
        )
