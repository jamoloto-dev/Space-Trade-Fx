"""Unit tests for Quant Recipes 1 & 2: Order Flow Analytics and ML Signal Engine."""

from __future__ import annotations

import pytest

from analytics.order_flow import OrderFlowEngine
from analytics.trailing_stop import TrailingStopManager
from models.signal_engine import SignalEngine


class TestOrderFlowEngine:
    """Tests for OrderFlowEngine (Recipe 1)."""

    def test_initialization(self):
        engine = OrderFlowEngine(window_size=50)
        assert engine.window_size == 50
        assert len(engine.tick_buffer) == 0
        assert engine.bid_volume_total == 0.0
        assert engine.ask_volume_total == 0.0

    def test_update_tick_buy_and_sell(self):
        engine = OrderFlowEngine(window_size=10)
        engine.update_tick(bid=1.1000, ask=1.1002, volume=2.5, flag="BUY")
        engine.update_tick(bid=1.1001, ask=1.1003, volume=1.5, flag="SELL")

        assert len(engine.tick_buffer) == 2
        assert engine.ask_volume_total == 2.5
        assert engine.bid_volume_total == 1.5

    def test_imbalance_calculation(self):
        engine = OrderFlowEngine()
        # Empty buffer
        assert engine.calculate_imbalance() == 0.0

        # Strong buy pressure: 3.0 vs 1.0 => (3 - 1) / 4 = 0.5
        engine.update_tick(bid=1.10, ask=1.11, volume=3.0, flag="BUY")
        engine.update_tick(bid=1.10, ask=1.11, volume=1.0, flag="SELL")
        assert engine.calculate_imbalance() == pytest.approx(0.5, rel=1e-3)

    def test_vwap_calculation(self):
        engine = OrderFlowEngine()
        assert engine.calculate_vwap() == 0.0

        # Tick 1: mid = 100, vol = 1 => 100
        engine.update_tick(bid=99.0, ask=101.0, volume=1.0, flag="BUY")
        # Tick 2: mid = 110, vol = 3 => 330
        engine.update_tick(bid=109.0, ask=111.0, volume=3.0, flag="BUY")
        # Sum PV = 430, Sum Vol = 4 => VWAP = 107.5
        assert engine.calculate_vwap() == pytest.approx(107.5, rel=1e-3)

    def test_momentum_calculation(self):
        engine = OrderFlowEngine()
        assert engine.calculate_tick_momentum() == 0.0

        engine.update_tick(bid=100.0, ask=100.0, volume=1.0)
        # Only 1 tick => 0.0
        assert engine.calculate_tick_momentum() == 0.0

        # Second tick up
        engine.update_tick(bid=105.0, ask=105.0, volume=1.0)
        # diff = 5.0, first_mid = 100.0 => (5 / 100) * 1000 = 50.0
        assert engine.calculate_tick_momentum() == pytest.approx(50.0, rel=1e-3)

    def test_ingest_metaapi_price(self):
        engine = OrderFlowEngine()
        engine.ingest_metaapi_price({"bid": 1.0850, "ask": 1.0852, "tickVolume": 2.0})
        assert len(engine.tick_buffer) == 1
        assert engine.ask_volume_total == 2.0

        # Subsequent lower price should infer SELL flag
        engine.ingest_metaapi_price({"bid": 1.0840, "ask": 1.0842, "tickVolume": 1.0})
        assert len(engine.tick_buffer) == 2
        assert engine.bid_volume_total == 1.0

    def test_get_market_pulse(self):
        engine = OrderFlowEngine()
        engine.update_tick(bid=1.0850, ask=1.0852, volume=5.0, flag="BUY")
        pulse = engine.get_market_pulse()

        assert "imbalance" in pulse
        assert "vwap" in pulse
        assert "momentum" in pulse
        assert "dominant_pressure" in pulse
        assert pulse["dominant_pressure"] == "BULLISH"
        assert pulse["buffered_ticks"] == 1


class TestSignalEngine:
    """Tests for SignalEngine (Recipe 2)."""

    def test_initialization(self):
        engine = SignalEngine(confidence_threshold=0.65)
        assert engine.confidence_threshold == 0.65
        assert len(engine.prediction_history) == 0

    def test_evaluate_signal_buy_bullish(self):
        engine = SignalEngine(confidence_threshold=0.65)
        res = engine.evaluate_signal(
            order_flow_imbalance=0.8,
            technical_score=80.0,  # strong buy (scaled to +0.6)
            macro_sentiment=0.7,
            symbol="EURUSD",
            direction="BUY",
        )
        assert res["symbol"] == "EURUSD"
        assert res["direction"] == "BUY"
        assert res["composite_score"] > 0
        assert res["confidence"] > 65.0
        assert res["execute"] is True
        assert len(engine.prediction_history) == 1

    def test_evaluate_signal_sell_bearish(self):
        engine = SignalEngine(confidence_threshold=0.65)
        # Bearish indicators with SELL direction should trigger high confidence
        res = engine.evaluate_signal(
            order_flow_imbalance=-0.8,
            technical_score=20.0,  # strong sell (scaled to -0.6)
            macro_sentiment=-0.7,
            symbol="EURUSD",
            direction="SELL",
        )
        assert res["direction"] == "SELL"
        assert res["composite_score"] > 0
        assert res["confidence"] > 65.0
        assert res["execute"] is True

    def test_evaluate_signal_below_threshold(self):
        engine = SignalEngine(confidence_threshold=0.70)
        # Neutral indicators
        res = engine.evaluate_signal(
            order_flow_imbalance=0.0,
            technical_score=50.0,
            macro_sentiment=0.0,
            symbol="GBPUSD",
            direction="BUY",
        )
        assert res["confidence"] == pytest.approx(50.0, rel=1e-1)
        assert res["execute"] is False

    def test_log_trade_outcome(self):
        engine = SignalEngine()
        rec_win = engine.log_trade_outcome(symbol="EURUSD", actual_profit=15.5, confidence=72.0, ticket="12345")
        assert rec_win["outcome"] == "WIN"
        assert rec_win["actual_profit"] == 15.5

        rec_loss = engine.log_trade_outcome(symbol="EURUSD", actual_profit=-5.0, confidence=72.0, ticket="12346")
        assert rec_loss["outcome"] == "LOSS"

        rec_even = engine.log_trade_outcome(symbol="EURUSD", actual_profit=0.0, confidence=72.0, ticket="12347")
        assert rec_even["outcome"] == "BREAKEVEN"


class TestTrailingStopManager:
    """Tests for TrailingStopManager (Break-Even Trailing Stop)."""

    def test_initialization(self):
        manager = TrailingStopManager(trigger_pips=15.0, buffer_pips=1.5)
        assert manager.trigger_pips == 15.0
        assert manager.buffer_pips == 1.5
        assert len(manager.modified_tickets) == 0

    def test_buy_position_below_trigger(self):
        manager = TrailingStopManager(trigger_pips=20.0, buffer_pips=2.0)
        pos = {
            "id": "101",
            "symbol": "EURUSD",
            "type": "POSITION_TYPE_BUY",
            "openPrice": 1.10000,
            "stopLoss": 1.09750,
        }
        # Current price = 1.10100 -> profit is 10 pips (< 20 trigger)
        res = manager.evaluate_and_trail(pos, current_market_price=1.10100)
        assert res["should_modify"] is False
        assert res["profit_pips"] == 10.0
        assert res["new_stop_loss"] == 1.09750

    def test_buy_position_hits_trigger_moves_to_break_even(self):
        manager = TrailingStopManager(trigger_pips=20.0, buffer_pips=2.0)
        pos = {
            "id": "102",
            "symbol": "EURUSD",
            "type": "BUY",
            "openPrice": 1.10000,
            "stopLoss": 1.09750,
        }
        # Current price = 1.10250 -> profit is 25 pips (>= 20 trigger)
        # Expected new SL = open (1.10000) + 2 pips buffer (0.00020) = 1.10020
        res = manager.evaluate_and_trail(pos, current_market_price=1.10250)
        assert res["should_modify"] is True
        assert res["profit_pips"] == 25.0
        assert res["new_stop_loss"] == 1.10020
        assert manager.is_already_modified("102") is True

    def test_buy_position_already_at_break_even_no_modify(self):
        manager = TrailingStopManager(trigger_pips=20.0, buffer_pips=2.0)
        pos = {
            "id": "103",
            "symbol": "EURUSD",
            "type": "BUY",
            "openPrice": 1.10000,
            "stopLoss": 1.10020,  # Already at or above break-even + buffer
        }
        res = manager.evaluate_and_trail(pos, current_market_price=1.10300)
        assert res["should_modify"] is False
        assert res["new_stop_loss"] == 1.10020

    def test_sell_position_hits_trigger_moves_to_break_even(self):
        manager = TrailingStopManager(trigger_pips=20.0, buffer_pips=2.0)
        pos = {
            "id": "201",
            "symbol": "GBPUSD",
            "type": "POSITION_TYPE_SELL",
            "openPrice": 1.30000,
            "stopLoss": 1.30250,
        }
        # Current price = 1.29750 -> profit is 25 pips (>= 20 trigger)
        # Expected new SL = open (1.30000) - 2 pips buffer (0.00020) = 1.29980
        res = manager.evaluate_and_trail(pos, current_market_price=1.29750)
        assert res["should_modify"] is True
        assert res["profit_pips"] == 25.0
        assert res["new_stop_loss"] == 1.29980
        assert manager.is_already_modified("201") is True

    def test_sell_position_below_trigger(self):
        manager = TrailingStopManager(trigger_pips=20.0, buffer_pips=2.0)
        pos = {
            "id": "202",
            "symbol": "GBPUSD",
            "type": "SELL",
            "openPrice": 1.30000,
            "stopLoss": 1.30250,
        }
        # Current price = 1.29850 -> profit is 15 pips (< 20 trigger)
        res = manager.evaluate_and_trail(pos, current_market_price=1.29850)
        assert res["should_modify"] is False
        assert res["profit_pips"] == 15.0

    def test_jpy_pair_pip_calculation(self):
        manager = TrailingStopManager(trigger_pips=20.0, buffer_pips=2.0)
        pos = {
            "id": "301",
            "symbol": "USDJPY",
            "type": "BUY",
            "openPrice": 150.000,
            "stopLoss": 149.500,
        }
        # Current price = 150.250 -> profit is 25 pips (pip_size = 0.01)
        # Expected new SL = 150.000 + (2 * 0.01) = 150.020
        res = manager.evaluate_and_trail(pos, current_market_price=150.250, digits=3)
        assert res["should_modify"] is True
        assert res["profit_pips"] == 25.0
        assert res["new_stop_loss"] == 150.020

    def test_clear_ticket(self):
        manager = TrailingStopManager()
        manager.mark_modified("999")
        assert manager.is_already_modified("999") is True
        manager.clear_ticket("999")
        assert manager.is_already_modified("999") is False
