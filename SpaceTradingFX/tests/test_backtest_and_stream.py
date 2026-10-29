"""
Tests for Space-Trade-Fx Vectorized Backtesting Engine and Real-Time SSE Telemetry Stream.
Verifies:
1. SpaceTradeBacktestRunner OHLCV generation and vectorized execution
2. Strategy transpilation to vectorized backtest tear sheet calculation (Sharpe, Profit Factor, Drawdown)
3. POST /api/strategy/backtest Flask REST API endpoint
4. GET /api/stream/telemetry Server-Sent Events (SSE) streaming endpoint
5. Strict naming rule enforcement (zero occurrences of banned terminology)
"""

from __future__ import annotations

import json
import os

import pandas as pd
import pytest

from SpaceTradingFX.flask_dashboard import create_app
from SpaceTradingFX.flask_dashboard.services.backtest_runner import (
    BacktestConfig,
    BacktestReport,
    SpaceTradeBacktestRunner,
)


@pytest.fixture
def app():
    """Create Flask application configured for testing."""
    os.environ["SECRET_KEY"] = "test-secret-key-space-trading-fx"
    os.environ["FLASK_ENV"] = "testing"
    test_app = create_app()
    test_app.config["TESTING"] = True
    return test_app


@pytest.fixture
def client(app):
    """Create Flask test client."""
    return app.test_client()


class MockStrategy:
    """Mock strategy generating alternating signals for backtester validation."""

    def __init__(self, frequency: int = 20) -> None:
        self.frequency = frequency

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        signals = [0] * len(df)
        for i in range(len(df)):
            if i > 0 and i % (self.frequency * 2) == 0:
                signals[i] = 1  # BUY
            elif i > 0 and i % self.frequency == 0:
                signals[i] = -1  # SELL
        out["signal"] = signals
        return out


class TestSpaceTradeBacktestRunner:
    def test_synthetic_ohlcv_generation(self):
        runner = SpaceTradeBacktestRunner()
        df = runner.generate_synthetic_ohlcv(symbol="EURUSD", bars=250, start_price=1.1000)
        assert len(df) == 250
        assert "open" in df.columns
        assert "high" in df.columns
        assert "low" in df.columns
        assert "close" in df.columns
        assert "volume" in df.columns
        assert (df["high"] >= df["low"]).all()

    def test_run_backtest_with_mock_strategy(self):
        cfg = BacktestConfig(initial_capital=10000.0, lot_size=0.10)
        runner = SpaceTradeBacktestRunner(cfg)
        df = runner.generate_synthetic_ohlcv(bars=200)

        strategy = MockStrategy(frequency=25)
        report = runner.run_backtest(strategy, df)

        assert isinstance(report, BacktestReport)
        assert report.initial_capital == 10000.0
        assert isinstance(report.ending_capital, float)
        assert isinstance(report.total_net_profit, float)
        assert report.total_trades > 0
        assert 0.0 <= report.win_rate_pct <= 100.0
        assert report.profit_factor >= 0.0
        assert report.max_drawdown_dollars >= 0.0
        assert report.max_drawdown_pct >= 0.0
        assert len(report.equity_curve) == 200
        assert len(report.trades) == report.total_trades

        # Verify to_dict serializability
        d = report.to_dict()
        assert "initial_capital" in d
        assert "sharpe_ratio" in d
        assert "equity_curve" in d

    def test_backtest_source_code_mql4(self):
        mql4_rsi_source = """
        // SpaceTrade RSI Strategy
        extern int InpRsiPeriod = 14;
        extern double InpRsiOversold = 35.0;
        extern double InpRsiOverbought = 65.0;

        int start() {
            double rsi = iRSI(NULL, 0, InpRsiPeriod, PRICE_CLOSE, 0);
            if(rsi < InpRsiOversold) {
                OrderSend(Symbol(), OP_BUY, 0.1, Ask, 3, 0, 0, "Buy", 88123, 0, Green);
            }
            if(rsi > InpRsiOverbought) {
                OrderSend(Symbol(), OP_SELL, 0.1, Bid, 3, 0, 0, "Sell", 88123, 0, Red);
            }
            return(0);
        }
        """
        runner = SpaceTradeBacktestRunner()
        report = runner.backtest_source_code(
            source_code=mql4_rsi_source,
            source_language="mq4",
            symbol="EURUSD",
            bars=350,
        )
        assert isinstance(report, BacktestReport)
        assert report.initial_capital == 10000.0
        assert len(report.equity_curve) == 350
        assert report.win_rate_pct >= 0.0

    def test_backtest_invalid_dataframe_raises(self):
        runner = SpaceTradeBacktestRunner()
        bad_df = pd.DataFrame({"dummy": [1, 2, 3]})
        strategy = MockStrategy()
        with pytest.raises(ValueError, match="non-empty DataFrame containing 'close' column"):
            runner.run_backtest(strategy, bad_df)


class TestBacktestAndStreamEndpoints:
    def test_api_strategy_backtest_success(self, client):
        mql4_code = """
        extern int InpRsiPeriod = 14;
        int start() {
            double rsi = iRSI(NULL, 0, InpRsiPeriod, PRICE_CLOSE, 0);
            if(rsi < 30) OrderSend(Symbol(), OP_BUY, 0.1, Ask, 3, 0, 0, "Buy", 123, 0, Green);
            if(rsi > 70) OrderSend(Symbol(), OP_SELL, 0.1, Bid, 3, 0, 0, "Sell", 123, 0, Red);
            return(0);
        }
        """
        res = client.post(
            "/api/strategy/backtest",
            json={
                "source_code": mql4_code,
                "source_type": "mq4",
                "symbol": "EURUSD",
                "initial_capital": 25000.0,
                "lot_size": 0.2,
                "bars": 200,
            },
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        assert "report" in data
        assert data["report"]["initial_capital"] == 25000.0
        assert "sharpe_ratio" in data["report"]
        assert "profit_factor" in data["report"]
        assert len(data["report"]["equity_curve"]) == 200

    def test_api_strategy_backtest_empty_code(self, client):
        res = client.post(
            "/api/strategy/backtest",
            json={"source_code": ""},
        )
        assert res.status_code == 400
        data = res.get_json()
        assert "error" in data

    def test_api_stream_telemetry_sse(self, client):
        res = client.get("/api/stream/telemetry")
        assert res.status_code == 200
        assert "text/event-stream" in res.content_type
        assert res.headers.get("X-Accel-Buffering") == "no"
        assert res.headers.get("Cache-Control") == "no-cache"

        # In testing mode, exactly 1 SSE frame is returned
        body = res.get_data(as_text=True)
        assert "event: telemetry" in body
        assert "data: {" in body

        # Parse json line from SSE
        for line in body.splitlines():
            if line.startswith("data: "):
                payload = json.loads(line[len("data: ") :])
                assert "timestamp" in payload
                assert "balance" in payload
                assert "equity" in payload
                assert "free_margin" in payload
                assert "positions" in payload
                break


class TestStrictNamingConvention:
    def test_no_banned_terms_in_codebase(self):
        """Ensure the banned terminology is completely absent from all source and test files."""
        banned_term = "EA " + "Converter"
        forbidden_lower = banned_term.lower()

        search_paths = [
            "SpaceTradingFX/flask_dashboard/services/backtest_runner.py",
            "SpaceTradingFX/flask_dashboard/services/execution_broker.py",
            "SpaceTradingFX/flask_dashboard/services/risk_manager.py",
            "SpaceTradingFX/flask_dashboard/services/trade_worker.py",
            "SpaceTradingFX/flask_dashboard/blueprints/strategy_adaptation.py",
            "SpaceTradingFX/flask_dashboard/blueprints/trading.py",
            "SpaceTradingFX/tests/test_backtest_and_stream.py",
            "SpaceTradingFX/tests/test_execution_broker_and_risk.py",
            "dashboard/app.py",
            "trading_state.py",
        ]

        for rel_path in search_paths:
            if not os.path.exists(rel_path):
                continue
            with open(rel_path, "r", encoding="utf-8") as f:
                content = f.read()
            assert forbidden_lower not in content.lower(), f"Banned terminology found in {rel_path}!"
