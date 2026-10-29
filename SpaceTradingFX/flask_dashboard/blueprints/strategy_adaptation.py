"""
Space-Trade-Fx Strategy Adaptation, Signal Interception & Diagnostics Blueprint
API endpoints for source-to-source transpilation, universal signal bridge generation,
and compiled binary static inspection.
"""

from __future__ import annotations

import base64
import logging
from typing import cast

from flask import Blueprint, jsonify, request

from ..services.binary_inspector import SpaceTradeBinaryInspector
from ..services.signal_bridge import SignalBridgeConfig, SpaceTradeSignalBridge
from ..services.strategy_transpiler import SpaceTradeStrategyEngine

logger = logging.getLogger("space_trading_fx.strategy_blueprint")

strategy_bp = Blueprint("strategy", __name__, url_prefix="/api/strategy")

strategy_engine = SpaceTradeStrategyEngine()
binary_inspector = SpaceTradeBinaryInspector()


@strategy_bp.get("/status")
def get_engine_status():
    """Return status and feature flags of the Space-Trade-Fx Strategy Adaptation Engine."""
    return jsonify(
        {
            "status": "active",
            "engine": "Space-Trade-Fx Strategy Adaptation, Signal Interception & File Diagnostics Engine",
            "pipelines": {
                "transpilation": {
                    "source_languages": ["mq4", "pine"],
                    "target_languages": ["mql5", "python"],
                },
                "signal_bridge": {
                    "modes": ["buffer", "object_scanner"],
                    "features": ["iCustom", "CopyBuffer", "CTrade", "ATR_Trailing_Stop", "Webhook_Dispatch"],
                },
                "binary_diagnostics": {
                    "supported_formats": [".ex4", ".ex5"],
                    "features": ["header_analysis", "shannon_entropy", "string_extraction", "parameter_recovery"],
                },
            },
        }
    )


@strategy_bp.post("/transpile")
def transpile_strategy():
    """
    Transpile .mq4 or Pine Script strategy into MQL5 or Space-Trade-Fx Python.
    """
    data = request.get_json(silent=True) or {}
    source_code = data.get("source_code", "")
    if not source_code or not source_code.strip():
        return jsonify({"error": "source_code is required"}), 400

    target_language = data.get("target_language", "mql5")
    source_language = data.get("source_language")
    strategy_name = data.get("strategy_name", "SpaceTradeAdaptedStrategy")

    result = strategy_engine.transpile(
        source_code=source_code,
        target_language=target_language,
        source_language=source_language,
        strategy_name=strategy_name,
    )

    return jsonify(
        {
            "success": result.success,
            "source_language": result.source_language,
            "target_language": result.target_language,
            "target_code": result.target_code,
            "indicators_detected": result.indicators_detected,
            "order_functions_mapped": result.order_functions_mapped,
            "inputs_extracted": result.inputs_extracted,
            "syntax_warnings": result.syntax_warnings,
            "ast_summary": result.ast_summary,
        }
    )


@strategy_bp.post("/signal-bridge/generate")
def generate_signal_bridge():
    """
    Generate production-ready MQL5 Signal Bridge and Python consumer code.
    """
    data = request.get_json(silent=True) or {}
    config = SignalBridgeConfig(
        indicator_name=data.get("indicator_name", "SpaceTradeCustomIndicator"),
        bridge_type=data.get("bridge_type", "buffer"),
        magic_number=int(data.get("magic_number", 88300)),
        lot_size=float(data.get("lot_size", 0.01)),
        slippage_points=int(data.get("slippage_points", 10)),
        stop_loss_pips=float(data.get("stop_loss_pips", 30.0)),
        take_profit_pips=float(data.get("take_profit_pips", 60.0)),
        use_atr_trailing_stop=bool(data.get("use_atr_trailing_stop", True)),
        atr_period=int(data.get("atr_period", 14)),
        atr_multiplier=float(data.get("atr_multiplier", 1.5)),
        buffer_buy_index=int(data.get("buffer_buy_index", 0)),
        buffer_sell_index=int(data.get("buffer_sell_index", 1)),
        buffer_mode=data.get("buffer_mode", "arrow_nonzero"),
        object_name_prefix=data.get("object_name_prefix", "Arrow"),
        buy_color_name=data.get("buy_color_name", "clrGreen"),
        sell_color_name=data.get("sell_color_name", "clrRed"),
        scan_lookback_bars=int(data.get("scan_lookback_bars", 2)),
        enable_webhook_dispatch=bool(data.get("enable_webhook_dispatch", False)),
        webhook_url=data.get("webhook_url", "http://127.0.0.1:5000/api/broker/execute-signal"),
    )

    bridge = SpaceTradeSignalBridge(config)
    mql5_code = bridge.generate_mql5_code()
    python_code = bridge.generate_python_bridge()

    return jsonify(
        {
            "success": True,
            "indicator_name": config.indicator_name,
            "bridge_type": config.bridge_type,
            "mql5_code": mql5_code,
            "python_consumer_code": python_code,
        }
    )


@strategy_bp.post("/diagnostics/inspect")
def inspect_binary():
    """
    Perform static header inspection, entropy calculation, and string parameter
    extraction on an uploaded .ex4 or .ex5 file.
    """
    file_bytes: bytes = b""
    filename: str = "binary.bin"

    if "file" in request.files:
        uploaded_file = request.files["file"]
        filename = uploaded_file.filename or "binary.bin"
        file_bytes = uploaded_file.read()
    else:
        json_data = request.get_json(silent=True) or {}
        if "file_base64" in json_data:
            file_bytes = base64.b64decode(cast(str, json_data["file_base64"]))
            filename = json_data.get("filename", "binary.bin")
        elif "content" in json_data:
            content_val = cast(str, json_data["content"])
            file_bytes = content_val.encode("utf-8")
            filename = json_data.get("filename", "binary.bin")
        else:
            return jsonify({"error": "No file uploaded or file_base64 provided"}), 400

    if not file_bytes:
        return jsonify({"error": "Uploaded binary file is empty"}), 400

    report = binary_inspector.inspect_file(file_bytes, filename=filename)
    return jsonify(report.to_dict())
