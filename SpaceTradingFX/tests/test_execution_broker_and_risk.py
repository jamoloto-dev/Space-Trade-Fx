"""
Unit and integration tests for Unified Execution Broker, SpaceTradeRiskManager, and SpaceTradeWorker.
"""

from __future__ import annotations

from unittest.mock import patch

from SpaceTradingFX.flask_dashboard.services.execution_broker import (
    AccountTelemetry,
    ExecutionBroker,
    LiveMetaApiBroker,
    OrderIntent,
    PaperExecutionBroker,
)
from SpaceTradingFX.flask_dashboard.services.risk_manager import (
    RiskLimits,
    SpaceTradeRiskManager,
)
from SpaceTradingFX.flask_dashboard.services.trade_worker import SpaceTradeWorker


class TestExecutionBroker:
    def test_paper_execution_broker_lifecycle(self):
        broker = PaperExecutionBroker(initial_balance=10000.0)
        assert isinstance(broker, ExecutionBroker)

        # 1. Check initial telemetry
        tele = broker.get_telemetry()
        assert tele.balance == 10000.0
        assert tele.open_trades == 0

        # 2. Submit order
        intent = OrderIntent(symbol="EURUSD", trade_type="BUY", lot_size=0.10)
        res = broker.submit_order(intent)
        assert res.success is True
        assert res.ticket is not None
        assert res.execution_mode == "paper"

        # 3. Verify position created
        positions = broker.get_positions()
        assert len(positions) == 1
        pos = positions[0]
        assert pos.symbol == "EURUSD"
        assert pos.trade_type == "BUY"
        assert pos.lot_size == 0.10

        # 4. Close position
        close_res = broker.close_position(res.ticket)
        assert close_res.success is True
        assert len(broker.get_positions()) == 0
        assert broker.total_trades == 1

    def test_live_metaapi_broker_interface(self):
        broker = LiveMetaApiBroker(user_id="test_user_metaapi")
        assert isinstance(broker, ExecutionBroker)


class TestSpaceTradeRiskManager:
    def setup_method(self):
        self.risk = SpaceTradeRiskManager(
            limits=RiskLimits(
                max_daily_drawdown_pct=5.0,
                max_open_positions=2,
                max_total_lot_size=0.5,
                max_spread_multiplier=2.5,
            )
        )
        self.broker = PaperExecutionBroker(initial_balance=10000.0)

    def test_circuit_breaker_trips_on_5_percent_drawdown(self):
        telemetry_safe = AccountTelemetry(balance=10000.0, equity=9800.0, free_margin=9000.0)
        tripped, dd = self.risk.check_circuit_breaker(telemetry_safe)
        assert tripped is False
        assert dd == 2.0

        # 600 drawdown on 10,000 = 6.0% drawdown (exceeds 5%)
        telemetry_breach = AccountTelemetry(balance=10000.0, equity=9400.0, free_margin=8000.0)
        tripped, dd = self.risk.check_circuit_breaker(telemetry_breach)
        assert tripped is True
        assert dd == 6.0
        assert self.risk.circuit_breaker_tripped is True
        assert "Daily drawdown" in self.risk.circuit_breaker_reason

        # Attempt pre-trade risk when tripped
        intent = OrderIntent(symbol="EURUSD", trade_type="BUY", lot_size=0.01)
        eval_res = self.risk.evaluate_pre_trade_risk(intent, self.broker)
        assert eval_res.allowed is False
        assert eval_res.circuit_breaker_active is True

        # Reset circuit breaker
        self.risk.reset_circuit_breaker()
        assert self.risk.circuit_breaker_tripped is False

    def test_max_open_positions_limit(self):
        # Open 2 positions (the limit)
        self.broker.submit_order(OrderIntent(symbol="EURUSD", trade_type="BUY", lot_size=0.01))
        self.broker.submit_order(OrderIntent(symbol="GBPUSD", trade_type="BUY", lot_size=0.01))

        # 3rd position should be vetoed
        intent = OrderIntent(symbol="USDJPY", trade_type="BUY", lot_size=0.01)
        eval_res = self.risk.evaluate_pre_trade_risk(intent, self.broker)
        assert eval_res.allowed is False
        assert any("Maximum open positions limit reached" in r for r in eval_res.reasons)

    def test_max_total_lot_size_limit(self):
        # Limit is 0.5; try ordering 0.6 lots
        intent = OrderIntent(symbol="EURUSD", trade_type="BUY", lot_size=0.60)
        eval_res = self.risk.evaluate_pre_trade_risk(intent, self.broker)
        assert eval_res.allowed is False
        assert any("Total open lots" in r for r in eval_res.reasons)

    def test_spread_expansion_veto(self):
        # EURUSD typical is 0.00015; 2.5x is 0.000375
        assert self.risk.check_spread_expansion("EURUSD", 0.00020) is False
        assert self.risk.check_spread_expansion("EURUSD", 0.00045) is True


class TestSpaceTradeWorker:
    def setup_method(self):
        self.broker = PaperExecutionBroker(initial_balance=10000.0)
        self.risk = SpaceTradeRiskManager()
        self.worker = SpaceTradeWorker(broker=self.broker, risk_manager=self.risk)

    def test_run_cycle_paused_when_unauthorized(self):
        with patch("trading_state.load_execution_state", return_value=False):
            res = self.worker.run_cycle()
            assert res["status"] == "paused"
            assert res["trades_executed"] == 0

    def test_run_cycle_executes_orders_when_authorized(self):
        with patch("trading_state.load_execution_state", return_value=True):
            with patch.object(
                self.worker,
                "_evaluate_market_signal",
                side_effect=lambda s: {"action": "BUY", "confidence": 80.0} if s == "EURUSD" else None,
            ):
                res = self.worker.run_cycle()
                assert res["status"] == "completed"
                assert res["trades_executed"] == 1
                assert len(self.broker.get_positions()) == 1

    def test_run_cycle_trips_circuit_breaker(self):
        # Force a large drawdown
        self.risk.circuit_breaker_tripped = True
        self.risk.circuit_breaker_reason = "Manual breach test"

        with patch("trading_state.load_execution_state", return_value=True):
            with patch("trading_state.save_execution_state") as mock_save:
                res = self.worker.run_cycle()
                assert res["status"] == "circuit_breaker_tripped"
                mock_save.assert_called_with(False, source="circuit_breaker")
