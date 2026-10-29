"""
Tests for Space-Trade-Fx Strategy Adaptation, Signal Interception & File Diagnostics Engine.
Verifies:
1. Pipeline 1: Source-to-Source Strategy Transpilation (.mq4 / Pine Script -> .mq5 / Python)
2. Pipeline 2: Universal Indicator Signal Bridge Generator (Buffer & Object Scanner)
3. Pipeline 3: Binary Metadata & Compatibility Triage (.ex4 / .ex5 static analysis)
4. Flask REST API endpoints in strategy_adaptation blueprint
5. Strict naming rule verification (zero occurrences of banned term)
"""

from __future__ import annotations

import base64
import os
import tempfile

import numpy as np
import pandas as pd
import pytest

from SpaceTradingFX.flask_dashboard import create_app
from SpaceTradingFX.flask_dashboard.services.binary_inspector import (
    SpaceTradeBinaryInspector,
    SpaceTradeBinaryReport,
)
from SpaceTradingFX.flask_dashboard.services.signal_bridge import (
    SignalBridgeConfig,
    SpaceTradeSignalBridge,
)
from SpaceTradingFX.flask_dashboard.services.strategy_transpiler import (
    SpaceTradeStrategyEngine,
    SpaceTradeStrategyTranspiler,
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


# =============================================================================
# Pipeline 1: Strategy Transpilation Engine Tests
# =============================================================================
class TestSpaceTradeStrategyTranspiler:
    def setup_method(self):
        self.engine = SpaceTradeStrategyEngine()

    def test_alias_equivalence(self):
        """Verify SpaceTradeStrategyTranspiler alias points to the same engine."""
        assert SpaceTradeStrategyTranspiler is SpaceTradeStrategyEngine

    def test_detect_source_language(self):
        mq4_sample = "int start() { OrderSend(Symbol(), OP_BUY, 0.1, Ask, 3, 0, 0); }"
        pine_sample = "//@version=5\nstrategy('Test Pine', overlay=true)\nrsi = ta.rsi(close, 14)"

        assert self.engine.detect_source_language(mq4_sample) == "mq4"
        assert self.engine.detect_source_language(pine_sample) == "pine"

    def test_transpile_mq4_to_mql5(self):
        mq4_code = """
        extern int InpRsiPeriod = 14;
        extern double InpLotSize = 0.05;

        int start()
        {
            double rsi = iRSI(NULL, 0, InpRsiPeriod, PRICE_CLOSE, 0);
            double ma = iMA(NULL, 0, 20, 0, MODE_SMA, PRICE_CLOSE, 0);

            if(OrdersTotal() == 0 && rsi < 30)
            {
                OrderSend(Symbol(), OP_BUY, InpLotSize, Ask, 5, 0, 0, "BuyOrder", 12345, 0, Green);
            }
            if(OrdersTotal() == 0 && rsi > 70)
            {
                OrderSend(Symbol(), OP_SELL, InpLotSize, Bid, 5, 0, 0, "SellOrder", 12345, 0, Red);
            }
            return(0);
        }
        """

        res = self.engine.transpile(mq4_code, target_language="mql5", strategy_name="TestMql5Strategy")
        assert res.success is True
        assert res.source_language == "mq4"
        assert res.target_language == "mql5"

        # Verification of MQL5 Architecture
        code = res.target_code
        assert "#include <Trade\\Trade.mqh>" in code
        assert "CTrade trade;" in code
        assert "GetFillingMode()" in code
        assert "trade.SetTypeFilling(GetFillingMode());" in code
        assert "int OnInit()" in code
        assert "handle_rsi" in code
        assert "iRSI(_Symbol, _Period" in code
        assert "INVALID_HANDLE" in code
        assert "void OnDeinit(const int reason)" in code
        assert "IndicatorRelease(handle_rsi);" in code
        assert "void OnTick()" in code
        assert "CopyRates(_Symbol, _Period" in code
        assert "CopyBuffer(handle_rsi" in code
        assert "trade.Buy(" in code
        assert "trade.Sell(" in code
        assert "RSI" in res.indicators_detected

    def test_transpile_mq4_to_python(self):
        mq4_code = """
        extern int InpRsiPeriod = 14;
        extern double InpLotSize = 0.1;

        int start()
        {
            double rsi = iRSI(NULL, 0, InpRsiPeriod, PRICE_CLOSE, 0);
            return(0);
        }
        """

        res = self.engine.transpile(mq4_code, target_language="python", strategy_name="SpaceTradePyStrategy")
        assert res.success is True
        assert res.target_language == "python"

        code = res.target_code
        assert "class SpaceTradePyStrategy:" in code
        assert "def compute_indicators(self, df: pd.DataFrame)" in code
        assert "def generate_signals(self, df: pd.DataFrame)" in code
        assert "def evaluate_tick(" in code
        assert "rsi_14" in code

        # Verify generated Python code compiles and executes validly
        namespace = {}
        exec(code, namespace)  # noqa: S102
        strat_cls = namespace["SpaceTradePyStrategy"]
        strategy_instance = strat_cls(magic_number=88123, lot_size=0.05)

        # Execute with synthetic DataFrame
        dates = pd.date_range("2026-01-01", periods=50, freq="1h")
        prices = np.linspace(1.1000, 1.1500, 50) + np.random.randn(50) * 0.001
        df = pd.DataFrame(
            {
                "close": prices,
                "open": prices - 0.0005,
                "high": prices + 0.0010,
                "low": prices - 0.0010,
            },
            index=dates,
        )

        out_df = strategy_instance.generate_signals(df)
        assert "signal" in out_df.columns
        assert "rsi_14" in out_df.columns

        tick_result = strategy_instance.evaluate_tick({"symbol": "EURUSD", "ask": 1.1200, "bid": 1.1198})
        assert tick_result["magic_number"] == 88123
        assert tick_result["symbol"] == "EURUSD"

    def test_transpile_pine_to_mql5(self):
        pine_code = """//@version=5
        strategy("Pine RSI", overlay=true)
        len = input.int(14, "Length")
        rsi = ta.rsi(close, len)
        if (rsi < 30)
            strategy.entry("Long", strategy.long)
        if (rsi > 70)
            strategy.entry("Short", strategy.short)
        """

        res = self.engine.transpile(pine_code, target_language="mql5")
        assert res.success is True
        assert res.source_language == "pine"
        assert res.target_language == "mql5"
        assert "#include <Trade\\Trade.mqh>" in res.target_code
        assert "trade.Buy(" in res.target_code or "trade.Sell(" in res.target_code

    def test_transpile_pine_to_python(self):
        pine_code = """//@version=5
        strategy("Pine SMA Cross", overlay=true)
        sma20 = ta.sma(close, 20)
        rsi = ta.rsi(close, 14)
        """

        res = self.engine.transpile(pine_code, target_language="python")
        assert res.success is True
        assert "class SpaceTradeAdaptedStrategy:" in res.target_code
        assert "df['sma_20']" in res.target_code
        assert "df['rsi']" in res.target_code


# =============================================================================
# Pipeline 2: Universal Signal Bridge Generator Tests
# =============================================================================
class TestSpaceTradeSignalBridge:
    def test_generate_buffer_interceptor_mql5(self):
        cfg = SignalBridgeConfig(
            indicator_name="SuperTrendPro",
            bridge_type="buffer",
            buffer_buy_index=0,
            buffer_sell_index=1,
            lot_size=0.02,
            magic_number=99123,
            use_atr_trailing_stop=True,
            atr_period=14,
            atr_multiplier=2.0,
            enable_webhook_dispatch=True,
            webhook_url="http://localhost:5000/api/broker/execute-signal",
        )
        bridge = SpaceTradeSignalBridge(cfg)
        mql5 = bridge.generate_mql5_code()

        assert "Space-Trade-Fx Universal Indicator Signal Bridge" in mql5
        assert 'input string InpIndicatorName   = "SuperTrendPro";' in mql5
        assert "iCustom(_Symbol, _Period" in mql5
        assert "CopyBuffer(handle_custom_ind, InpBuyBufferIndex" in mql5
        assert "CopyBuffer(handle_custom_ind, InpSellBufferIndex" in mql5
        assert "IsNewBar()" in mql5
        assert "ApplyAtrTrailingStop()" in mql5
        assert "SendWebhookSignal" in mql5
        assert "WebRequest(" in mql5
        assert "trade.Buy(InpLotSize" in mql5
        assert "trade.Sell(InpLotSize" in mql5

    def test_generate_object_scanner_mql5(self):
        cfg = SignalBridgeConfig(
            indicator_name="VisualArrowIndicator",
            bridge_type="object_scanner",
            object_name_prefix="TrendArrow",
            buy_color_name="clrLime",
            sell_color_name="clrRed",
            scan_lookback_bars=3,
            magic_number=99456,
        )
        bridge = SpaceTradeSignalBridge(cfg)
        mql5 = bridge.generate_mql5_code()

        assert "Chart Graphical Object Scanner (Bufferless Fallback)" in mql5
        assert 'input string   InpObjectPrefix    = "TrendArrow";' in mql5
        assert "ObjectsTotal(0, 0, -1)" in mql5
        assert "ObjectName(0, i, 0, -1)" in mql5
        assert "OBJPROP_COLOR" in mql5
        assert "OBJPROP_TIME" in mql5
        assert "last_processed_object_name" in mql5
        assert "trade.Buy(" in mql5
        assert "trade.Sell(" in mql5

    def test_generate_python_consumer(self):
        bridge = SpaceTradeSignalBridge(SignalBridgeConfig(magic_number=88444, lot_size=0.03))
        py_code = bridge.generate_python_bridge()

        assert "class SpaceTradeSignalConsumer:" in py_code
        assert "self.magic_number = 88444" in py_code
        assert "self.default_lot = 0.03" in py_code

        # Test execute in Python
        ns = {}
        exec(py_code, ns)  # noqa: S102
        consumer_cls = ns["SpaceTradeSignalConsumer"]
        consumer = consumer_cls()
        res = consumer.process_incoming_signal({"symbol": "GBPUSD", "action": "BUY", "price": 1.2500})
        assert res["status"] == "received"
        assert res["symbol"] == "GBPUSD"


# =============================================================================
# Pipeline 3: Binary Metadata & File Diagnostics Tests
# =============================================================================
class TestSpaceTradeBinaryInspector:
    def setup_method(self):
        self.inspector = SpaceTradeBinaryInspector()

    def test_shannon_entropy(self):
        # Zero entropy for identical bytes
        uniform_bytes = b"A" * 500
        assert self.inspector.calculate_shannon_entropy(uniform_bytes) == 0.0

        # High entropy for pseudorandom bytes (approaching 8.0)
        np.random.seed(42)
        rand_bytes = np.random.randint(0, 256, size=2048, dtype=np.uint8).tobytes()
        entropy = self.inspector.calculate_shannon_entropy(rand_bytes)
        assert entropy > 7.5

    def test_string_extraction(self):
        # Create byte stream with ASCII and UTF-16LE strings (2-byte aligned)
        ascii_text = b"InpPeriod_MA\x00extern_Lots\x00EURUSD\x00\x00"
        utf16_text = "InpStopLoss".encode("utf-16le") + b"\x00\x00" + "kernel32.dll".encode("utf-16le")
        payload = ascii_text + utf16_text

        ascii_res, utf16_res = self.inspector.extract_strings(payload)
        all_strs = ascii_res + utf16_res
        assert "InpPeriod_MA" in all_strs
        assert "EURUSD" in all_strs
        assert "InpStopLoss" in all_strs
        assert "kernel32.dll" in all_strs

    def test_inspect_mock_ex4_file(self):
        # Create a mock .ex4 with Build 600+ Unicode markers and params
        content = (
            b"\x84\x00\x00\x00"  # Magic header
            + b"InpFastMA\x00InpSlowMA\x00iRSI\x00EURUSD\x00"
            + "InpMagicNumber".encode("utf-16le")
            + b"\x00\x00"
            + ("A" * 300).encode("utf-8")
        )

        with tempfile.NamedTemporaryFile(suffix=".ex4", delete=False) as f:
            f.write(content)
            temp_path = f.name

        try:
            report = self.inspector.inspect_file(temp_path)
            assert isinstance(report, SpaceTradeBinaryReport)
            assert report.file_type == "ex4"
            assert report.architecture == "32-bit"
            assert report.is_encrypted_or_packed is False
            assert "InpFastMA" in report.extracted_parameters
            assert "EURUSD" in report.currency_symbols
            assert "iRSI" in report.detected_indicators
            assert "Space-Trade-Fx Strategy Transpilation Engine" in report.recommended_strategy
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_inspect_mock_ex5_file_with_dll(self):
        # Create a mock .ex5 with DLL import
        content = (
            b"EX5_HEADER_MQL5_64BIT"
            + b"\x00\x00"
            + b"user32.dll\x00"
            + b"InpTrailingATR\x00"
            + b"indicator_buffers\x00"
            + ("B" * 200).encode("utf-8")
        )

        report = self.inspector.inspect_file(content, filename="CustomStrategy.ex5")
        assert report.file_type == "ex5"
        assert report.architecture == "64-bit"
        assert report.build_era == "MQL5"
        assert "user32.dll" in report.dll_imports
        assert report.risk_level == "HIGH"
        assert "user32.dll" in "".join(report.analysis_notes)

    def test_inspect_high_entropy_drm_file(self):
        # High entropy payload representing Market DRM
        np.random.seed(123)
        encrypted_bytes = b"EX5_MARKET_" + np.random.randint(0, 256, size=4096, dtype=np.uint8).tobytes()
        report = self.inspector.inspect_file(encrypted_bytes, filename="ProtectedIndicator.ex5")

        assert report.file_type == "ex5"
        assert report.is_encrypted_or_packed is True
        assert report.max_chunk_entropy > 7.3
        assert "Object Scanner Signal Bridge" in report.recommended_strategy


# =============================================================================
# Flask REST API Endpoint Tests
# =============================================================================
class TestStrategyAdaptationAPI:
    def test_get_status(self, client):
        resp = client.get("/api/strategy/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "active"
        assert "Space-Trade-Fx" in data["engine"]
        assert "transpilation" in data["pipelines"]
        assert "signal_bridge" in data["pipelines"]
        assert "binary_diagnostics" in data["pipelines"]

    def test_post_transpile(self, client):
        payload = {
            "source_code": "int start() { double rsi = iRSI(NULL, 0, 14, 0, 0); }",
            "target_language": "mql5",
            "strategy_name": "ApiTestStrategy",
        }
        resp = client.post("/api/strategy/transpile", json=payload)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["target_language"] == "mql5"
        assert "CTrade trade;" in data["target_code"]

    def test_post_transpile_empty_reject(self, client):
        resp = client.post("/api/strategy/transpile", json={"source_code": "   "})
        assert resp.status_code == 400

    def test_post_generate_signal_bridge(self, client):
        payload = {
            "indicator_name": "SuperArrows",
            "bridge_type": "buffer",
            "lot_size": 0.05,
            "magic_number": 88776,
        }
        resp = client.post("/api/strategy/signal-bridge/generate", json=payload)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "SuperArrows" in data["mql5_code"]
        assert "SpaceTradeSignalConsumer" in data["python_consumer_code"]

    def test_post_inspect_binary(self, client):
        mock_data = b"EX5_FILE\x00InpStopLoss\x00" + b"A" * 100
        b64 = base64.b64encode(mock_data).decode("ascii")

        resp = client.post("/api/strategy/diagnostics/inspect", json={"file_base64": b64, "filename": "test.ex5"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["file_type"] == "ex5"
        assert data["architecture"] == "64-bit"
        assert "InpStopLoss" in data["extracted_parameters"]


# =============================================================================
# Strict Naming Rule Enforcement
# =============================================================================
def test_strict_naming_rule_no_banned_phrase():
    """Verify ZERO occurrences of banned phrase anywhere in the codebase."""
    banned_token = "EA " + "Converter"  # Constructed to prevent self-matching in string grep
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    violations = []
    for root, dirs, files in os.walk(repo_root):
        # Skip virtualenvs, git directory, and cache
        if any(ignored in root for ignored in (".git", ".venv", "__pycache__", ".pytest_cache")):
            continue
        for file in files:
            if file.endswith((".py", ".md", ".json", ".mq4", ".mq5")):
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                        text = f.read()
                        if banned_token.lower() in text.lower():
                            violations.append(filepath)
                except Exception:
                    pass

    assert violations == [], f"Found banned naming rule violation in files: {violations}"
