"""Deterministic paper-trading service; it contains no broker implementation."""

from __future__ import annotations

import logging
from uuid import uuid4
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from .extensions import db
from .forex_data import get_forex_provider
from .models import Trade, TradingPreference, TradingSignal, utcnow

logger = logging.getLogger(__name__)
SUPPORTED_SYMBOLS = frozenset({"EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD"})
SUPPORTED_TIMEFRAMES = frozenset({"1M", "5M", "15M", "1H", "4H", "D"})
PIP_SIZES = {symbol: Decimal("0.01") if symbol.endswith("JPY") else Decimal("0.0001") for symbol in SUPPORTED_SYMBOLS}


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
            self.preferences = TradingPreference(user_id=user_id, currency_pairs=["EURUSD", "GBPUSD", "USDJPY"], timeframe="1H", risk_percentage=Decimal("1.00"), max_concurrent_trades=3, trading_enabled=False)
            db.session.add(self.preferences)
            db.session.commit()

    def analyze_markets(self) -> list[dict]:
        signals: list[dict] = []
        for symbol in self.preferences.currency_pairs or []:
            if symbol not in SUPPORTED_SYMBOLS:
                logger.warning("Ignoring unsupported paper symbol %s", symbol)
                continue
            try:
                signal_data = self.forex_provider.analyze_signal(symbol)
                direction = str(signal_data.get("signal", "NEUTRAL")).upper()
                allowed = (self.preferences.direction_preferences or {}).get(symbol, "BOTH")
                if direction not in {"BUY", "SELL"} or allowed not in {"BOTH", direction}:
                    continue
                db.session.add(TradingSignal(currency_pair=symbol, signal_type=direction, strength=_decimal(signal_data.get("strength", 0), field="signal strength"), price=self._get_current_price(symbol), indicators=signal_data.get("indicators", {}), timeframe=self.preferences.timeframe))
                signals.append(signal_data)
            except (MarketDataUnavailable, PaperTradeValidationError) as exc:
                logger.warning("Paper signal unavailable for %s: %s", symbol, exc)
        db.session.commit()
        return signals

    def _get_current_price(self, currency_pair: str) -> Decimal:
        self._validate_symbol(currency_pair)
        try:
            data = self.forex_provider.get_forex_intraday(currency_pair[:3], currency_pair[3:], self.preferences.timeframe)
            candles = data.get("data") if isinstance(data, dict) else None
            if not data.get("success") or not candles:
                raise MarketDataUnavailable("Market price is unavailable")
            price = _decimal(candles[0].get("close"), field="market price")
            if price <= 0:
                raise MarketDataUnavailable("Market price is invalid")
            return price
        except (KeyError, TypeError, AttributeError) as exc:
            raise MarketDataUnavailable("Market data response is invalid") from exc

    def execute_trade(self, currency_pair: str, signal_type: str, signal_data: dict | None = None) -> Trade:
        """Record a validated paper order. It never calls a broker."""
        self._validate_symbol(currency_pair)
        direction = str(signal_type).upper()
        if direction not in {"BUY", "SELL"}:
            raise PaperTradeValidationError("Trade direction must be BUY or SELL")
        if not self.preferences.trading_enabled:
            raise PaperTradeValidationError("Paper trading is disabled in preferences")
        if self.preferences.timeframe not in SUPPORTED_TIMEFRAMES:
            raise PaperTradeValidationError("Unsupported timeframe")
        if Trade.query.filter_by(user_id=self.user_id, status="open").count() >= self.preferences.max_concurrent_trades:
            raise PaperTradeValidationError("Paper trade limit reached")
        entry_price = self._get_current_price(currency_pair)
        lot_size = self._calculate_lot_size()
        stop_loss, take_profit = self._calculate_sl_tp(entry_price, direction, currency_pair)
        trade = Trade(
            user_id=self.user_id, currency_pair=currency_pair, trade_type=direction,
            entry_price=entry_price, lot_size=lot_size, stop_loss=stop_loss,
            take_profit=take_profit, status="broker_acknowledged", execution_mode="paper",
            idempotency_key=uuid4().hex, broker_order_id=f"paper-{uuid4().hex}",
            broker_response={"mode": "paper", "acknowledged": True},
            reconciliation_state="not_required",
            signal_data={**(signal_data or {}), "execution_mode": "paper", "simulation": True},
        )
        db.session.add(trade)
        db.session.flush()
        trade.status = "open"
        db.session.commit()
        logger.info("Paper trade opened: id=%s symbol=%s direction=%s", trade.id, currency_pair, direction)
        return trade

    def _calculate_lot_size(self) -> Decimal:
        risk = _decimal(self.preferences.risk_percentage, field="risk percentage")
        if not Decimal("0") < risk <= Decimal("2"):
            raise PaperTradeValidationError("Risk percentage must be between 0 and 2")
        return (Decimal("0.01") * risk).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    def _calculate_sl_tp(self, entry_price: Decimal, direction: str, symbol: str) -> tuple[Decimal, Decimal]:
        stop_distance, target_distance = PIP_SIZES[symbol] * Decimal("20"), PIP_SIZES[symbol] * Decimal("40")
        return (entry_price - stop_distance, entry_price + target_distance) if direction == "BUY" else (entry_price + stop_distance, entry_price - target_distance)

    def update_open_trades(self) -> None:
        for trade in Trade.query.filter_by(user_id=self.user_id, status="open").all():
            current_price = self._get_current_price(trade.currency_pair)
            trade.profit_loss = self._profit_loss(trade, current_price)
            if self._check_exit_conditions(trade, current_price):
                self._close_trade(trade, current_price)
        db.session.commit()

    def _profit_loss(self, trade: Trade, price: Decimal) -> Decimal:
        difference = price - trade.entry_price if trade.trade_type == "BUY" else trade.entry_price - price
        return (difference * trade.lot_size * Decimal("100000")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def _check_exit_conditions(self, trade: Trade, current_price: Decimal) -> bool:
        if trade.trade_type == "BUY":
            return bool((trade.stop_loss and current_price <= trade.stop_loss) or (trade.take_profit and current_price >= trade.take_profit))
        return bool((trade.stop_loss and current_price >= trade.stop_loss) or (trade.take_profit and current_price <= trade.take_profit))

    def _close_trade(self, trade: Trade, exit_price: Decimal) -> None:
        if trade.status != "open":
            raise PaperTradeValidationError("Only open paper trades can be closed")
        trade.status, trade.exit_price, trade.closed_at = "closed", exit_price, utcnow()
        trade.profit_loss = self._profit_loss(trade, exit_price)
        logger.info("Paper trade closed: id=%s profit_loss=%s", trade.id, trade.profit_loss)

    def get_account_summary(self) -> dict:
        all_trades = Trade.query.filter_by(user_id=self.user_id).all()
        closed = [trade for trade in all_trades if trade.status == "closed"]
        winning = sum(1 for trade in closed if trade.profit_loss > 0)
        losing = sum(1 for trade in closed if trade.profit_loss < 0)
        return {"execution_mode": "paper", "total_trades": len(all_trades), "winning_trades": winning, "losing_trades": losing, "win_rate": (Decimal(winning) / Decimal(len(closed)) * 100) if closed else Decimal("0"), "total_profit": sum((trade.profit_loss for trade in closed), Decimal("0")), "active_trades": sum(1 for trade in all_trades if trade.status == "open"), "trades": [trade for trade in all_trades if trade.status == "open"]}

    @staticmethod
    def _validate_symbol(symbol: str) -> None:
        if symbol not in SUPPORTED_SYMBOLS:
            raise PaperTradeValidationError("Unsupported trading symbol")
