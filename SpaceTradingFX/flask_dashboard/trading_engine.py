"""Deterministic paper-trading service; it contains no broker implementation."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from uuid import uuid4

from flask import current_app
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from .audit import record_audit_event
from .extensions import db
from .forex_data import get_forex_provider, parse_market_timestamp
from .models import PaperOrderEvent, PaperReconciliationRun, Trade, TradingPreference, TradingSignal, utcnow
from .paper_orders import InvalidPaperOrder, PaperOrderIntent, assert_transition, validate_intent
from .risk import PaperRiskRejected, assert_paper_intent_allowed
from .symbols import DEFAULT_LOT_SIZE, SUPPORTED_SYMBOLS, SUPPORTED_TIMEFRAMES, instrument

logger = logging.getLogger(__name__)


class MarketDataUnavailable(RuntimeError):
    """Market data was unavailable; callers must not substitute a price."""


class PaperTradeValidationError(ValueError):
    """The proposed paper order does not satisfy deterministic risk rules."""


def _decimal(value: object, *, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PaperTradeValidationError(f"Invalid {field}") from exc


class TradingEngine:
    """Paper-only order ledger backed by explicit market-data and risk checks."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.forex_provider = get_forex_provider()
        self.preferences = TradingPreference.query.filter_by(user_id=user_id).first()
        if self.preferences is None:
            self.preferences = TradingPreference(
                user_id=user_id,
                currency_pairs=["EURUSD", "GBPUSD", "USDJPY"],
                timeframe="1H",
                risk_percentage=Decimal("1.00"),
                max_concurrent_trades=3,
                trading_enabled=False,
            )
            db.session.add(self.preferences)
            db.session.commit()

    def analyze_markets(self, *, submit_automatically: bool = False) -> list[dict]:
        """Persist deterministic signals and optionally submit *paper* intents.

        Manual orders are deliberately separate: their user-selected direction
        is retained as a manual simulation action, rather than being presented
        as a strategy recommendation.
        """
        signals: list[dict] = []
        for symbol in self.preferences.currency_pairs or []:
            if symbol not in SUPPORTED_SYMBOLS:
                logger.warning("Ignoring unsupported paper symbol %s", symbol)
                continue
            try:
                signal_data = self.forex_provider.analyze_signal(symbol, timeframe=self.preferences.timeframe)
                direction = str(signal_data.get("signal", "NEUTRAL")).upper()
                allowed = (self.preferences.direction_preferences or {}).get(symbol, "BOTH")
                if direction not in {"BUY", "SELL"} or allowed not in {"BOTH", direction}:
                    continue
                price, quote_time, quote_metadata = self._get_current_quote(symbol)
                stored_signal = TradingSignal(
                    currency_pair=symbol,
                    signal_type=direction,
                    strength=_decimal(signal_data.get("strength", 0), field="signal strength"),
                    price=price,
                    indicators={**signal_data.get("indicators", {}), "_market_data": quote_metadata},
                    timeframe=self.preferences.timeframe,
                )
                db.session.add(stored_signal)
                db.session.flush()
                signal_data = {
                    **signal_data,
                    "quote_time": quote_time,
                    "quote": quote_metadata,
                    "source": "deterministic_rsi_macd",
                }
                signals.append(signal_data)
                if submit_automatically:
                    # The bar timestamp makes a repeated worker cycle idempotent.
                    key = f"auto:{symbol}:{self.preferences.timeframe}:{quote_time}:{direction}"
                    try:
                        self.execute_trade(
                            symbol,
                            direction,
                            signal_data,
                            idempotency_key=key,
                            submission_mode="automated",
                        )
                    except PaperTradeValidationError as exc:
                        logger.info("Automated paper intent rejected for %s: %s", symbol, exc)
            except (MarketDataUnavailable, PaperTradeValidationError) as exc:
                logger.warning("Paper signal unavailable for %s: %s", symbol, exc)
        db.session.commit()
        return signals

    def run_automated_cycle(self) -> int:
        """Submit eligible deterministic signals only when automation is enabled."""
        if not (self.preferences.strategy_settings or {}).get("automated_paper_trading", False):
            return 0
        before = Trade.query.filter_by(user_id=self.user_id).count()
        self.analyze_markets(submit_automatically=True)
        return Trade.query.filter_by(user_id=self.user_id).count() - before

    def _get_current_quote(self, currency_pair: str) -> tuple[Decimal, str, dict[str, str]]:
        """Return an explicitly sourced quote after structural validation.

        Simulation fixtures are deliberately timeless and reproducible.  An
        external quote, by contrast, must have a parseable, non-future,
        sufficiently fresh timestamp.  Unknown sources fail closed so a
        provider cannot silently become an execution price source.
        """
        self._validate_symbol(currency_pair)
        try:
            data = self.forex_provider.get_forex_intraday(
                currency_pair[:3], currency_pair[3:], self.preferences.timeframe
            )
            candles = data.get("data") if isinstance(data, dict) else None
            if not data.get("success") or not candles:
                raise MarketDataUnavailable("Market price is unavailable")
            data_mode = data.get("data_mode")
            if data_mode not in {"simulation", "external"}:
                raise MarketDataUnavailable("Market data source is not declared")
            parsed_times = [parse_market_timestamp(candle.get("time")) for candle in candles]
            if any(timestamp is None for timestamp in parsed_times):
                raise MarketDataUnavailable("Market quote timestamp is missing or invalid")
            if any(parsed_times[index] < parsed_times[index + 1] for index in range(len(parsed_times) - 1)):
                raise MarketDataUnavailable("Market candles are not newest-first")
            candle = candles[0]
            quote_time = str(candle.get("time", ""))
            latest_time = parsed_times[0]
            assert latest_time is not None  # narrowed by the validation above
            if data_mode == "external":
                max_age = int(current_app.config.get("MARKET_DATA_MAX_STALENESS", 86400))
                age = (datetime.now(timezone.utc) - latest_time).total_seconds()
                if age < 0 or age > max_age:
                    raise MarketDataUnavailable("External market quote is stale or future-dated")
            price = _decimal(candle.get("close"), field="market price")
            if price <= 0:
                raise MarketDataUnavailable("Market price is invalid")
            return price, quote_time, {"mode": data_mode, "provider": str(data.get("provider", "unknown"))}
        except (KeyError, TypeError, AttributeError, ValueError) as exc:
            raise MarketDataUnavailable("Market data response is invalid") from exc

    def _get_current_price(self, currency_pair: str) -> Decimal:
        return self._get_current_quote(currency_pair)[0]

    def execute_trade(
        self,
        currency_pair: str,
        signal_type: str,
        signal_data: dict | None = None,
        *,
        idempotency_key: str | None = None,
        submission_mode: str = "manual",
    ) -> Trade:
        """Record a validated paper order. It never calls a broker."""
        if current_app.config.get("PAPER_TRADING_KILL_SWITCH"):
            raise PaperTradeValidationError("Paper trading is temporarily disabled by the kill switch")
        if idempotency_key:
            existing = Trade.query.filter_by(user_id=self.user_id, idempotency_key=idempotency_key).first()
            if existing is not None:
                return existing
        self._validate_symbol(currency_pair)
        direction = str(signal_type).upper()
        if direction not in {"BUY", "SELL"}:
            raise PaperTradeValidationError("Trade direction must be BUY or SELL")
        if self.preferences.timeframe not in SUPPORTED_TIMEFRAMES:
            raise PaperTradeValidationError("Unsupported timeframe")
        entry_price, entry_quote_time, entry_quote_metadata = self._get_current_quote(currency_pair)
        lot_size = self._calculate_lot_size(currency_pair)
        stop_loss, take_profit = self._calculate_sl_tp(entry_price, direction, currency_pair)
        planned_loss = abs(entry_price - stop_loss) * lot_size * instrument(currency_pair).contract_size
        try:
            assert_paper_intent_allowed(
                user_id=self.user_id,
                preferences=self.preferences,
                lot_size=lot_size,
                planned_loss=planned_loss,
                submission_mode=submission_mode,
            )
        except PaperRiskRejected as exc:
            raise PaperTradeValidationError(str(exc)) from exc
        try:
            validate_intent(
                PaperOrderIntent(currency_pair, direction, entry_price, lot_size, stop_loss, take_profit),
                supported_symbols=SUPPORTED_SYMBOLS,
            )
        except InvalidPaperOrder as exc:
            raise PaperTradeValidationError(str(exc)) from exc
        trade = Trade(
            user_id=self.user_id,
            currency_pair=currency_pair,
            trade_type=direction,
            entry_price=entry_price,
            lot_size=lot_size,
            stop_loss=stop_loss,
            take_profit=take_profit,
            status="draft",
            execution_mode="paper",
            idempotency_key=idempotency_key or uuid4().hex,
            signal_data={
                **(signal_data or {}),
                "entry_quote_time": entry_quote_time,
                "entry_quote": entry_quote_metadata,
                "execution_mode": "paper",
                "simulation": True,
                "submission_mode": submission_mode,
                "fill_assumption": "next observed close; no spread, commission, slippage, or partial fills",
                "pnl_units": "simulated account units (USD-assumed; no FX conversion)",
                "planned_stop_loss": str(planned_loss),
            },
        )
        try:
            # Add and flush *inside* the savepoint.  Adding before entering
            # it lets SQLAlchemy autoflush while creating the savepoint,
            # which leaves the outer request transaction unusable after a
            # concurrent unique-key collision.
            with db.session.begin_nested():
                db.session.add(trade)
                db.session.flush()
        except IntegrityError:
            existing = Trade.query.filter_by(user_id=self.user_id, idempotency_key=trade.idempotency_key).first()
            if existing is not None:
                return existing
            raise
        self._record_event(trade, "intent_recorded", None, "draft", {"symbol": currency_pair, "direction": direction})
        self._transition(trade, "validated", "risk_validated")
        self._transition(trade, "open", "opened")
        record_audit_event(
            "paper_order.opened",
            actor_id=self.user_id,
            target_type="trade",
            target_id=str(trade.id),
            metadata={"symbol": currency_pair, "direction": direction, "execution_mode": "paper"},
        )
        db.session.commit()
        logger.info("Paper trade opened: id=%s symbol=%s direction=%s", trade.id, currency_pair, direction)
        return trade

    def _calculate_lot_size(self, symbol: str) -> Decimal:
        """Use the configured fixed paper lot; risk percentage is not a lot multiplier."""
        configured = (self.preferences.strategy_settings or {}).get("lot_sizes", {})
        lot = _decimal(configured.get(symbol, DEFAULT_LOT_SIZE), field="configured paper lot size")
        if lot <= 0:
            raise PaperTradeValidationError("Configured paper lot size must be positive")
        return lot.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    def _calculate_sl_tp(self, entry_price: Decimal, direction: str, symbol: str) -> tuple[Decimal, Decimal]:
        stop_distance, target_distance = (
            instrument(symbol).pip_size * Decimal("20"),
            instrument(symbol).pip_size * Decimal("40"),
        )
        return (
            (entry_price - stop_distance, entry_price + target_distance)
            if direction == "BUY"
            else (entry_price + stop_distance, entry_price - target_distance)
        )

    def update_open_trades(self) -> int:
        """Mark paper P/L and atomically close trades whose simulated levels hit."""
        closed_count = 0
        for trade in Trade.query.filter_by(user_id=self.user_id, status="open").all():
            try:
                current_price = self._get_current_price(trade.currency_pair)
                trade.profit_loss = self._profit_loss(trade, current_price)
                if self._check_exit_conditions(trade, current_price) and self._close_trade(trade, current_price):
                    closed_count += 1
            except MarketDataUnavailable as exc:
                logger.warning("Paper monitoring skipped trade %s: %s", trade.id, exc)
        db.session.commit()
        return closed_count

    def _profit_loss(self, trade: Trade, price: Decimal) -> Decimal:
        difference = price - trade.entry_price if trade.trade_type == "BUY" else trade.entry_price - price
        return (difference * trade.lot_size * Decimal("100000")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def _check_exit_conditions(self, trade: Trade, current_price: Decimal) -> bool:
        if trade.trade_type == "BUY":
            return bool(
                (trade.stop_loss and current_price <= trade.stop_loss)
                or (trade.take_profit and current_price >= trade.take_profit)
            )
        return bool(
            (trade.stop_loss and current_price >= trade.stop_loss)
            or (trade.take_profit and current_price <= trade.take_profit)
        )

    def _close_trade(self, trade: Trade, exit_price: Decimal) -> bool:
        """Claim a close transition once, so duplicate workers cannot close twice."""
        if exit_price <= 0:
            raise PaperTradeValidationError("Paper close price must be positive")
        close_result = db.session.execute(
            update(Trade).where(Trade.id == trade.id, Trade.status == "open").values(status="closing")
        )
        claimed = int(getattr(close_result, "rowcount", 0) or 0)
        if claimed != 1:
            return False
        db.session.refresh(trade)
        self._record_event(trade, "close_requested", "open", "closing", {})
        trade.exit_price, trade.closed_at = exit_price, utcnow()
        trade.profit_loss = self._profit_loss(trade, exit_price)
        self._transition(trade, "closed", "closed", {"profit_loss": str(trade.profit_loss)})
        record_audit_event(
            "paper_order.closed",
            actor_id=self.user_id,
            target_type="trade",
            target_id=str(trade.id),
            metadata={"execution_mode": "paper"},
        )
        logger.info("Paper trade closed: id=%s profit_loss=%s", trade.id, trade.profit_loss)
        return True

    def _transition(self, trade: Trade, target: str, event_type: str, details: dict | None = None) -> None:
        previous = trade.status
        try:
            assert_transition(previous, target)
        except InvalidPaperOrder as exc:
            raise PaperTradeValidationError(str(exc)) from exc
        trade.status = target
        self._record_event(trade, event_type, previous, target, details or {})

    @staticmethod
    def _record_event(trade: Trade, event_type: str, state_before: str | None, state_after: str, details: dict) -> None:
        sequence = (
            len(
                [
                    event
                    for event in PaperOrderEvent.query.filter_by(trade_id=trade.id).with_entities(PaperOrderEvent.id)
                ]
            )
            + 1
        )
        db.session.add(
            PaperOrderEvent(
                trade_id=trade.id,
                sequence=sequence,
                event_type=event_type,
                state_before=state_before,
                state_after=state_after,
                details=details,
            )
        )

    def reconcile_paper_ledger(self) -> PaperReconciliationRun:
        """Reconcile persisted paper state against its own immutable lifecycle.

        This does not contact a broker. Any mismatch is durable and visible;
        it is never silently repaired into a successful-looking state.
        """
        run = PaperReconciliationRun(user_id=self.user_id)
        db.session.add(run)
        for trade in Trade.query.filter_by(user_id=self.user_id).all():
            run.checked_count += 1
            events = PaperOrderEvent.query.filter_by(trade_id=trade.id).order_by(PaperOrderEvent.sequence).all()
            expected = events[-1].state_after if events else "draft"
            if expected != trade.status:
                trade.reconciliation_state = "exception"
                run.exception_count += 1
                self._record_event(
                    trade, "reconciliation_exception", trade.status, trade.status, {"expected_state": expected}
                )
            else:
                trade.reconciliation_state = "reconciled"
                trade.last_reconciled_at = utcnow()
                self._record_event(trade, "reconciled", trade.status, trade.status, {})
        db.session.commit()
        return run

    def get_account_summary(self) -> dict:
        all_trades = Trade.query.filter_by(user_id=self.user_id).all()
        closed = [trade for trade in all_trades if trade.status == "closed"]
        winning = sum(1 for trade in closed if trade.profit_loss > 0)
        losing = sum(1 for trade in closed if trade.profit_loss < 0)
        return {
            "execution_mode": "paper",
            "total_trades": len(all_trades),
            "winning_trades": winning,
            "losing_trades": losing,
            "win_rate": (Decimal(winning) / Decimal(len(closed)) * 100) if closed else Decimal("0"),
            "total_profit": sum((trade.profit_loss for trade in closed), Decimal("0")),
            "active_trades": sum(1 for trade in all_trades if trade.status == "open"),
            "trades": [trade for trade in all_trades if trade.status == "open"],
        }

    @staticmethod
    def _validate_symbol(symbol: str) -> None:
        if symbol not in SUPPORTED_SYMBOLS:
            raise PaperTradeValidationError("Unsupported trading symbol")
