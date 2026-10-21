"""Deterministic paper-trading service; it contains no broker implementation."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from uuid import uuid4

from flask import current_app
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from .analytics import compute_institutional_tear_sheet
from .audit import record_audit_event
from .extensions import db
from .forex_data import get_forex_provider, parse_market_timestamp
from .market_microstructure import QuoteNBBO, simulate_market_fill
from .models import (
    BrokerAccount,
    PaperOrderEvent,
    PaperReconciliationRun,
    Trade,
    TradingPreference,
    TradingSignal,
    utcnow,
)
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
                currency_pairs=["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "USDZAR"],
                timeframe="1H",
                risk_percentage=Decimal("1.00"),
                max_concurrent_trades=3,
                trading_enabled=False,
            )
            db.session.add(self.preferences)
            db.session.commit()

    def analyze_markets(self, *, submit_automatically: bool = False) -> list[dict]:
        """Scan real live OHLCV market data, compute RSI/EMA/MACD/ATR, and persist trading signals."""
        from .forex_data import LiveMarketScanner, MockForexDataProvider
        from .symbols import DEFAULT_MONITORED_PAIRS

        # Use LiveMarketScanner unless an explicit mock was set for unit tests
        scanner = self.forex_provider
        if isinstance(scanner, MockForexDataProvider):
            try:
                scanner = LiveMarketScanner()
            except Exception:
                scanner = self.forex_provider

        pairs_to_scan = (
            self.preferences.currency_pairs
            if (self.preferences and self.preferences.currency_pairs)
            else DEFAULT_MONITORED_PAIRS
        )
        signals: list[dict] = []

        for symbol in pairs_to_scan:
            if symbol not in SUPPORTED_SYMBOLS:
                logger.warning("Ignoring unsupported symbol %s", symbol)
                continue
            try:
                signal_data = scanner.analyze_signal(symbol, timeframe=self.preferences.timeframe)
                direction = str(signal_data.get("signal", "BUY")).upper()
                if direction not in {"BUY", "SELL"}:
                    direction = "BUY"

                # Check if current quote is available or use signal price
                try:
                    price, quote_time, quote_metadata = self._get_current_quote(symbol)
                except Exception:
                    price_val = signal_data.get("price") or signal_data.get("entry_price") or Decimal("1.00000")
                    price = Decimal(str(price_val))
                    quote_time = datetime.now(timezone.utc).isoformat()
                    quote_metadata = {"provider": "live_scanner", "time": quote_time}

                # Ensure SL, TP and indicators are present
                entry_float = float(price)
                indicators = dict(signal_data.get("indicators", {}))
                sl = signal_data.get("stop_loss") or indicators.get("sl")
                tp = signal_data.get("take_profit") or indicators.get("tp")
                if sl is None or tp is None:
                    atr_val = indicators.get("atr", entry_float * 0.003)
                    if direction == "BUY":
                        sl = round(entry_float - (1.5 * atr_val), 5)
                        tp = round(entry_float + (2.5 * atr_val), 5)
                    else:
                        sl = round(entry_float + (1.5 * atr_val), 5)
                        tp = round(entry_float - (2.5 * atr_val), 5)

                indicators["entry"] = entry_float
                indicators["sl"] = sl
                indicators["tp"] = tp
                indicators["_market_data"] = quote_metadata

                stored_signal = TradingSignal(
                    currency_pair=symbol,
                    signal_type=direction,
                    strength=_decimal(signal_data.get("strength", 70), field="signal strength"),
                    price=price,
                    indicators=indicators,
                    timeframe=self.preferences.timeframe,
                )
                db.session.add(stored_signal)
                db.session.flush()

                enriched_signal = {
                    **signal_data,
                    "currency_pair": symbol,
                    "signal": direction,
                    "price": float(price),
                    "entry_price": entry_float,
                    "stop_loss": sl,
                    "take_profit": tp,
                    "quote_time": quote_time,
                    "quote": quote_metadata,
                    "source": "live_technical_indicators",
                }
                signals.append(enriched_signal)

                allowed = (self.preferences.direction_preferences or {}).get(symbol, "BOTH")
                strength_val = float(signal_data.get("strength", 70))
                # Institutional duplicate-position protection: never open a second trade on a symbol with an active open position
                existing_open = Trade.query.filter_by(user_id=self.user_id, currency_pair=symbol, status="open").first()

                if (
                    submit_automatically
                    and (allowed in {"BOTH", direction})
                    and (strength_val >= 65.0)
                    and (existing_open is None)
                ):
                    key = f"auto:{symbol}:{self.preferences.timeframe}:{quote_time}:{direction}"
                    try:
                        self.execute_trade(
                            symbol,
                            direction,
                            enriched_signal,
                            idempotency_key=key,
                            submission_mode="automated",
                        )
                    except Exception as exc:
                        logger.info("Automated broker trade not executed for %s: %s", symbol, exc)
                elif submit_automatically and existing_open is not None:
                    logger.info(
                        "Auto-pilot duplicate protection: active position exists for %s, skipping auto-trade", symbol
                    )

            except Exception as exc:
                logger.warning("Error scanning market symbol %s: %s", symbol, exc)

        db.session.commit()
        return signals

    def run_automated_cycle(self) -> int:
        """Submit eligible deterministic signals only when automation and broker connection are active."""
        settings = self.preferences.strategy_settings or {}
        if not (settings.get("automated_broker_trading", False) or settings.get("automated_paper_trading", False)):
            return 0
        broker_acct = BrokerAccount.query.filter_by(user_id=self.user_id, is_connected=True).first()
        if not broker_acct:
            logger.warning(
                "Automated execution halted for user %s: No active IFX Brokers or Deriv account connected", self.user_id
            )
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
            valid_times = [timestamp for timestamp in parsed_times if timestamp is not None]
            if len(valid_times) != len(parsed_times):
                raise MarketDataUnavailable("Market quote timestamp is missing or invalid")
            if any(valid_times[index] < valid_times[index + 1] for index in range(len(valid_times) - 1)):
                raise MarketDataUnavailable("Market candles are not newest-first")
            candle = candles[0]
            quote_time = str(candle.get("time", ""))
            latest_time = valid_times[0]
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
        # Institutional Transaction Cost Analysis (TCA) and NBBO quote model
        inst = instrument(currency_pair)
        spread = inst.pip_size * Decimal("2")
        quote_nbbo = QuoteNBBO(
            symbol=currency_pair,
            bid=entry_price - (spread / Decimal("2")),
            ask=entry_price + (spread / Decimal("2")),
        )
        fill_report = simulate_market_fill(quote_nbbo, direction, lot_size)

        # Dispatch strictly to connected MT4/MT5 broker account (IFX Brokers / Deriv)
        broker_acct = BrokerAccount.query.filter_by(user_id=self.user_id, is_connected=True).first()
        if not broker_acct:
            from .services.broker_bridge import BrokerConnectionError

            raise BrokerConnectionError(
                "Execution halted: No active broker account connected. "
                "Please connect your IFX Brokers or Deriv account to execute trades."
            )

        from .services.broker_bridge import execute_robot_trade

        broker_exec = execute_robot_trade(
            user_id=self.user_id,
            symbol=currency_pair,
            order_type=direction,
            volume=lot_size,
            sl=stop_loss,
            tp=take_profit,
            current_price=entry_price,
        )

        trade = Trade(
            user_id=self.user_id,
            currency_pair=currency_pair,
            trade_type=direction,
            entry_price=entry_price,
            lot_size=lot_size,
            stop_loss=stop_loss,
            take_profit=take_profit,
            status="draft",
            execution_mode="broker",
            idempotency_key=idempotency_key or uuid4().hex,
            mt5_ticket=str(broker_exec.get("ticket")) if (broker_exec and broker_exec.get("ticket")) else None,
            broker_order_id=str(broker_exec.get("ticket")) if (broker_exec and broker_exec.get("ticket")) else None,
            broker_response=broker_exec,
            signal_data={
                **(signal_data or {}),
                "entry_quote_time": entry_quote_time,
                "entry_quote": entry_quote_metadata,
                "execution_mode": "broker",
                "broker_execution": broker_exec,
                "broker_server": broker_acct.server,
                "broker_platform": broker_acct.platform,
                "broker_account_login": broker_acct.account_login,
                "submission_mode": submission_mode,
                "planned_stop_loss": str(planned_loss),
                "execution_fill": {
                    "fill_price": str(fill_report.fill_price),
                    "slippage": str(fill_report.slippage),
                    "slippage_bps": str(fill_report.slippage_bps),
                    "gross_notional": str(fill_report.gross_notional),
                    "sec_fee": str(fill_report.sec_fee),
                    "finra_taf": str(fill_report.finra_taf),
                    "exchange_fee": str(fill_report.exchange_fee),
                    "broker_commission": str(fill_report.broker_commission),
                    "total_fees": str(fill_report.total_fees),
                    "net_notional": str(fill_report.net_notional),
                },
            },
        )
        try:
            # Add and flush inside the savepoint
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
            "broker_order.opened",
            actor_id=self.user_id,
            target_type="trade",
            target_id=str(trade.id),
            metadata={
                "symbol": currency_pair,
                "direction": direction,
                "execution_mode": "broker",
                "server": broker_acct.server,
                "ticket": trade.mt5_ticket,
            },
        )
        db.session.commit()
        logger.info(
            "Broker trade executed: id=%s symbol=%s direction=%s server=%s ticket=%s",
            trade.id,
            currency_pair,
            direction,
            broker_acct.server,
            trade.mt5_ticket,
        )
        return trade

    def _calculate_lot_size(self, symbol: str) -> Decimal:
        """Use the configured fixed paper lot or equity shares; risk percentage is not a multiplier."""
        configured = (self.preferences.strategy_settings or {}).get("lot_sizes", {})
        inst = instrument(symbol)
        default_size = Decimal("10") if inst.contract_size == Decimal("1") else DEFAULT_LOT_SIZE
        lot = _decimal(configured.get(symbol, default_size), field="configured paper lot size")
        if lot <= 0:
            raise PaperTradeValidationError("Configured paper lot size must be positive")
        precision = Decimal("1") if inst.contract_size == Decimal("1") else Decimal("0.0001")
        return lot.quantize(precision, rounding=ROUND_HALF_UP)

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
            except Exception as exc:
                logger.warning("Paper monitoring error for trade %s: %s", trade.id, exc)
        db.session.commit()
        return closed_count

    def _profit_loss(self, trade: Trade, price: Decimal) -> Decimal:
        difference = price - trade.entry_price if trade.trade_type == "BUY" else trade.entry_price - price
        contract_size = instrument(trade.currency_pair).contract_size
        return (difference * trade.lot_size * contract_size).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

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
            "broker_order.closed",
            actor_id=self.user_id,
            target_type="trade",
            target_id=str(trade.id),
            metadata={"execution_mode": "broker"},
        )
        logger.info("Broker trade closed: id=%s profit_loss=%s", trade.id, trade.profit_loss)
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
        broker_acct = BrokerAccount.query.filter_by(user_id=self.user_id, is_connected=True).first()
        all_trades = Trade.query.filter_by(user_id=self.user_id).all()
        closed = [trade for trade in all_trades if trade.status == "closed"]
        winning = sum(1 for trade in closed if trade.profit_loss > 0)
        losing = sum(1 for trade in closed if trade.profit_loss < 0)
        tear_sheet = compute_institutional_tear_sheet(closed)

        from .services.broker_bridge import get_broker_telemetry

        telemetry = get_broker_telemetry(self.user_id)

        return {
            "execution_mode": "broker" if broker_acct else "disconnected",
            "broker_connected": broker_acct is not None,
            "broker_server": broker_acct.server if broker_acct else None,
            "broker_platform": broker_acct.platform if broker_acct else None,
            "broker_login": broker_acct.account_login if broker_acct else None,
            "currency": telemetry["currency"],
            "currency_symbol": telemetry["currency_symbol"],
            "balance": telemetry["balance"],
            "equity": telemetry["equity"],
            "free_margin": telemetry["free_margin"],
            "floating_pnl": telemetry["floating_pnl"],
            "total_trades": len(all_trades),
            "winning_trades": winning,
            "losing_trades": losing,
            "win_rate": (Decimal(winning) / Decimal(len(closed)) * 100) if closed else Decimal("0"),
            "total_profit": sum((trade.profit_loss for trade in closed), Decimal("0")),
            "active_trades": sum(1 for trade in all_trades if trade.status == "open"),
            "trades": [trade for trade in all_trades if trade.status == "open"],
            "tear_sheet": tear_sheet,
            "sharpe_ratio": tear_sheet.sharpe_ratio,
            "sortino_ratio": tear_sheet.sortino_ratio,
            "max_drawdown": tear_sheet.max_drawdown,
            "max_drawdown_pct": tear_sheet.max_drawdown_pct,
            "profit_factor": tear_sheet.profit_factor,
            "payoff_ratio": tear_sheet.payoff_ratio,
            "total_fees": tear_sheet.total_fees,
            "average_slippage": tear_sheet.average_slippage,
            "var_95": tear_sheet.var_95,
        }

    @staticmethod
    def _validate_symbol(symbol: str) -> None:
        if symbol not in SUPPORTED_SYMBOLS:
            raise PaperTradeValidationError("Unsupported trading symbol")
