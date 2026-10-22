"""Order Flow & Microstructure Analytics Engine.

Captures real-time tick data, computes bid/ask imbalances, volume deltas,
VWAP (Volume Weighted Average Price), and multi-timeframe order flow signals.
"""

from __future__ import annotations

from collections import deque
from typing import Any


class OrderFlowEngine:
    """Sliding-window Order Flow & Microstructure Engine."""

    def __init__(self, window_size: int = 100):
        self.window_size = window_size
        self.tick_buffer: deque[dict[str, Any]] = deque(maxlen=window_size)
        self.bid_volume_total: float = 0.0
        self.ask_volume_total: float = 0.0

    def update_tick(self, bid: float, ask: float, volume: float = 1.0, flag: str = "BUY") -> None:
        """Ingests raw tick data and updates rolling order flow metrics."""
        vol = max(0.0001, float(volume))
        flag_upper = str(flag).upper()
        self.tick_buffer.append({"bid": float(bid), "ask": float(ask), "volume": vol, "flag": flag_upper})
        if flag_upper == "BUY":
            self.ask_volume_total += vol
        else:
            self.bid_volume_total += vol

    def ingest_metaapi_price(self, price_data: dict[str, Any]) -> None:
        """Ingests a real-time price tick or quote dictionary directly from MetaApi."""
        bid = float(price_data.get("bid", 0.0))
        ask = float(price_data.get("ask", bid))
        vol = float(price_data.get("tickVolume") or price_data.get("volume") or 1.0)
        # Infer trade side based on previous midpoint if flag not present
        if self.tick_buffer:
            prev_mid = (self.tick_buffer[-1]["bid"] + self.tick_buffer[-1]["ask"]) / 2.0
            curr_mid = (bid + ask) / 2.0
            flag = "BUY" if curr_mid >= prev_mid else "SELL"
        else:
            flag = "BUY"
        self.update_tick(bid=bid, ask=ask, volume=vol, flag=flag)

    def calculate_imbalance(self) -> float:
        """Calculates current order book / tick volume imbalance (-1.0 to 1.0)."""
        total = self.ask_volume_total + self.bid_volume_total
        if total == 0:
            return 0.0
        return (self.ask_volume_total - self.bid_volume_total) / total

    def calculate_vwap(self) -> float:
        """Calculates Volume Weighted Average Price (VWAP) across the buffered ticks."""
        if not self.tick_buffer:
            return 0.0
        cum_pv = 0.0
        cum_vol = 0.0
        for tick in self.tick_buffer:
            typical_price = (tick["bid"] + tick["ask"]) / 2.0
            cum_pv += typical_price * tick["volume"]
            cum_vol += tick["volume"]
        return (cum_pv / cum_vol) if cum_vol > 0 else 0.0

    def calculate_tick_momentum(self) -> float:
        """Calculates short-term price velocity across the sliding window (-1.0 to 1.0)."""
        if len(self.tick_buffer) < 2:
            return 0.0
        first_mid = (self.tick_buffer[0]["bid"] + self.tick_buffer[0]["ask"]) / 2.0
        last_mid = (self.tick_buffer[-1]["bid"] + self.tick_buffer[-1]["ask"]) / 2.0
        diff = last_mid - first_mid
        return float(diff / first_mid * 1000.0) if first_mid > 0 else 0.0

    def get_market_pulse(self) -> dict[str, Any]:
        """Returns structured order flow telemetry and dominant pressure."""
        imbalance = self.calculate_imbalance()
        vwap = self.calculate_vwap()
        momentum = self.calculate_tick_momentum()
        dominant = "BULLISH" if imbalance > 0.05 else ("BEARISH" if imbalance < -0.05 else "NEUTRAL")

        return {
            "imbalance": round(imbalance, 4),
            "vwap": round(vwap, 5),
            "momentum": round(momentum, 4),
            "buffered_ticks": len(self.tick_buffer),
            "dominant_pressure": dominant,
            "ask_volume_total": round(self.ask_volume_total, 2),
            "bid_volume_total": round(self.bid_volume_total, 2),
        }
