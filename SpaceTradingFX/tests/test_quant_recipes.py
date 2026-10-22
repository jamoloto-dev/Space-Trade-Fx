"""Unit tests for Quant Recipes 1 & 2: Order Flow Analytics and ML Signal Engine."""

from __future__ import annotations

import pytest

from analytics.order_flow import OrderFlowEngine
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
