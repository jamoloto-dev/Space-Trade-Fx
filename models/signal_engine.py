"""Machine Learning & Signal Confidence Scoring Engine.

Combines order flow imbalances, multi-timeframe technical indicator scores,
and macroeconomic sentiment into a calibrated confidence percentage.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger("SignalEngine")


class SignalEngine:
    """Predictive scoring engine weighting multi-factor trading signals."""

    def __init__(self, confidence_threshold: float = 0.80):
        self.confidence_threshold = confidence_threshold
        self.prediction_history: list[dict[str, Any]] = []

    def evaluate_signal(
        self,
        order_flow_imbalance: float,
        technical_score: float,
        macro_sentiment: float,
        symbol: str | None = None,
        direction: str = "BUY",
    ) -> dict[str, Any]:
        """Weights order flow, technical indicators, and macro sentiment

        to produce a final confidence probability.
        """
        # Clamp inputs to standard [-1.0, 1.0] domain
        ofi = float(np.clip(order_flow_imbalance, -1.0, 1.0))
        # If technical_score is 0-100 (e.g. strength 75), scale to [-1.0, 1.0]
        if abs(technical_score) > 1.0:
            tech = float(np.clip((technical_score - 50.0) / 50.0, -1.0, 1.0))
        else:
            tech = float(np.clip(technical_score, -1.0, 1.0))
        macro = float(np.clip(macro_sentiment, -1.0, 1.0))

        # Adjust polarity if evaluating a SELL order
        polarity = 1.0 if str(direction).upper() == "BUY" else -1.0
        weighted_ofi = (ofi * polarity) * 0.3
        weighted_tech = (tech * polarity) * 0.4
        weighted_macro = (macro * polarity) * 0.3

        # Weighted composite score
        composite_score = weighted_ofi + weighted_tech + weighted_macro

        # Sigmoid activation to calibrate to [0.0, 1.0] probability
        confidence = float(1.0 / (1.0 + np.exp(-composite_score * 5.0)))
        execute = confidence >= self.confidence_threshold

        result = {
            "symbol": symbol or "UNKNOWN",
            "direction": str(direction).upper(),
            "composite_score": round(composite_score, 4),
            "confidence": round(confidence * 100.0, 2),
            "confidence_ratio": round(confidence, 4),
            "execute": execute,
            "threshold": round(self.confidence_threshold * 100.0, 2),
            "factors": {
                "order_flow_imbalance": round(ofi, 4),
                "technical_score": round(tech, 4),
                "macro_sentiment": round(macro, 4),
            },
        }

        self.prediction_history.append(result)
        logger.info(
            "🧠 Signal Engine Eval [%s %s]: Confidence %.1f%% (Threshold: %.1f%%) => Execute: %s",
            result["symbol"],
            result["direction"],
            result["confidence"],
            result["threshold"],
            result["execute"],
        )
        return result

    def log_trade_outcome(
        self,
        symbol: str,
        actual_profit: float,
        confidence: float,
        ticket: str | None = None,
    ) -> dict[str, Any]:
        """Integrates logging for model predictions vs actual trade outcomes

        to dynamically evaluate win-rate probabilities.
        """
        outcome = "WIN" if actual_profit > 0 else ("LOSS" if actual_profit < 0 else "BREAKEVEN")
        record = {
            "symbol": symbol,
            "ticket": ticket,
            "confidence": confidence,
            "actual_profit": round(actual_profit, 2),
            "outcome": outcome,
        }
        logger.info(
            "📈 Trade Outcome Audit [%s | Ticket: %s]: Predicted Confidence %.1f%% => Outcome: %s ($%.2f)",
            symbol,
            ticket or "N/A",
            confidence,
            outcome,
            actual_profit,
        )
        return record
