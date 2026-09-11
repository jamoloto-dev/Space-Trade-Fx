import logging
import os
from datetime import datetime, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)


def _parse_timestamp(ts_str: str) -> datetime | None:
    """Safely parse provider timestamp strings to UTC datetime."""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(ts_str, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


class ForexDataProvider:
    """Fetches forex data and technical indicators with caching and staleness enforcement."""

    def __init__(
        self,
        api_key: str | None = None,
        cache_ttl_seconds: int = 60,
        max_staleness_seconds: int = 86400,
        base_url: str = "https://www.alphavantage.co/query",
    ):
        self.api_key = api_key or os.environ.get("ALPHA_VANTAGE_API_KEY", "")
        self.base_url = base_url
        self.cache_ttl_seconds = cache_ttl_seconds
        self.max_staleness_seconds = max_staleness_seconds
        self._cache: dict[tuple, tuple[dict[str, Any], datetime]] = {}

    def clear_cache(self) -> None:
        """Clear the in-memory cache."""
        self._cache.clear()

    def _get_from_cache(self, key: tuple) -> dict[str, Any] | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        data, cached_at = entry
        now = datetime.now(timezone.utc)
        if (now - cached_at).total_seconds() < self.cache_ttl_seconds:
            return data
        return None

    def _set_in_cache(self, key: tuple, data: dict[str, Any]) -> None:
        self._cache[key] = (data, datetime.now(timezone.utc))

    def _check_staleness(self, latest_timestamp_str: str) -> bool:
        """Return True if timestamp is within max_staleness_seconds, False if stale."""
        dt = _parse_timestamp(latest_timestamp_str)
        if dt is None:
            return True
        age = (datetime.now(timezone.utc) - dt).total_seconds()
        return age <= self.max_staleness_seconds

    def get_forex_intraday(
        self, from_currency: str = "EUR", to_currency: str = "USD", interval: str = "5min"
    ) -> dict[str, Any]:
        """Get intraday forex data with caching and staleness enforcement."""
        cache_key = ("intraday", from_currency, to_currency, interval)
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        interval_map = {
            "1M": "1min",
            "5M": "5min",
            "15M": "15min",
            "30M": "30min",
            "1H": "60min",
            "4H": "60min",
            "D": "60min",
        }
        api_interval = interval_map.get(interval, interval if "min" in interval else "5min")

        try:
            params = {
                "function": "FX_INTRADAY",
                "from_symbol": from_currency,
                "to_symbol": to_currency,
                "interval": api_interval,
                "apikey": self.api_key,
                "outputsize": "compact",
            }

            response = requests.get(self.base_url, params=params, timeout=10)
            data = response.json()

            if "Note" in data or "Information" in data:
                logger.warning("Alpha Vantage rate limit reached for %s%s", from_currency, to_currency)
                return {"success": False, "error": "Provider rate limit reached"}

            if "Error Message" in data:
                logger.warning("Alpha Vantage returned error message for %s%s", from_currency, to_currency)
                return {"success": False, "error": "Invalid request to market data provider"}

            time_series_key = None
            for key in data.keys():
                if "Time Series FX" in key:
                    time_series_key = key
                    break

            if time_series_key and data[time_series_key]:
                time_series = data[time_series_key]
                latest_ts = next(iter(time_series.keys()))

                if not self._check_staleness(latest_ts):
                    logger.warning("Market data for %s%s is stale (latest: %s)", from_currency, to_currency, latest_ts)
                    return {"success": False, "error": "Market data is stale", "stale": True}

                candlesticks = []
                for timestamp, values in time_series.items():
                    candlesticks.append(
                        {
                            "time": timestamp,
                            "open": float(values.get("1. open", 0.0)),
                            "high": float(values.get("2. high", 0.0)),
                            "low": float(values.get("3. low", 0.0)),
                            "close": float(values.get("4. close", 0.0)),
                        }
                    )

                result = {"success": True, "data": candlesticks}
                self._set_in_cache(cache_key, result)
                return result
            else:
                logger.warning("Invalid response structure from Alpha Vantage for %s%s", from_currency, to_currency)
                return {"success": False, "error": "Invalid response from market data provider"}

        except Exception:
            logger.exception("Failed to fetch forex intraday data for %s%s", from_currency, to_currency)
            return {"success": False, "error": "Market data provider request failed"}

    def get_rsi(
        self, from_currency: str = "EUR", to_currency: str = "USD", interval: str = "daily", time_period: int = 14
    ) -> dict[str, Any]:
        """Get RSI indicator with caching and staleness enforcement."""
        cache_key = ("rsi", from_currency, to_currency, interval, time_period)
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        try:
            params: dict[str, Any] = {
                "function": "RSI",
                "symbol": f"{from_currency}{to_currency}",
                "interval": interval,
                "time_period": str(time_period),
                "series_type": "close",
                "apikey": self.api_key,
            }

            response = requests.get(self.base_url, params=params, timeout=10)

            data = response.json()

            if "Note" in data or "Information" in data:
                logger.warning("Alpha Vantage rate limit reached for RSI %s%s", from_currency, to_currency)
                return {"success": False, "error": "Provider rate limit reached"}

            if "Technical Analysis: RSI" in data:
                rsi_data = data["Technical Analysis: RSI"]
                latest_timestamp = next(iter(rsi_data.keys()))

                if not self._check_staleness(latest_timestamp):
                    logger.warning("RSI data for %s%s is stale (%s)", from_currency, to_currency, latest_timestamp)
                    return {"success": False, "error": "Market data is stale", "stale": True}

                latest_rsi = float(rsi_data[latest_timestamp]["RSI"])
                result = {"success": True, "rsi": latest_rsi, "timestamp": latest_timestamp}
                self._set_in_cache(cache_key, result)
                return result
            else:
                return {"success": False, "error": "Could not fetch RSI data"}

        except Exception:
            logger.exception("Failed to fetch RSI data for %s%s", from_currency, to_currency)
            return {"success": False, "error": "Market data provider request failed"}

    def get_macd(self, from_currency: str = "EUR", to_currency: str = "USD", interval: str = "daily") -> dict[str, Any]:
        """Get MACD indicator with caching and staleness enforcement."""
        cache_key = ("macd", from_currency, to_currency, interval)
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        try:
            params = {
                "function": "MACD",
                "symbol": f"{from_currency}{to_currency}",
                "interval": interval,
                "series_type": "close",
                "apikey": self.api_key,
            }

            response = requests.get(self.base_url, params=params, timeout=10)
            data = response.json()

            if "Note" in data or "Information" in data:
                logger.warning("Alpha Vantage rate limit reached for MACD %s%s", from_currency, to_currency)
                return {"success": False, "error": "Provider rate limit reached"}

            if "Technical Analysis: MACD" in data:
                macd_data = data["Technical Analysis: MACD"]
                latest_timestamp = next(iter(macd_data.keys()))

                if not self._check_staleness(latest_timestamp):
                    logger.warning("MACD data for %s%s is stale (%s)", from_currency, to_currency, latest_timestamp)
                    return {"success": False, "error": "Market data is stale", "stale": True}

                latest_macd = {
                    "macd": float(macd_data[latest_timestamp]["MACD"]),
                    "signal": float(macd_data[latest_timestamp]["MACD_Signal"]),
                    "hist": float(macd_data[latest_timestamp]["MACD_Hist"]),
                    "timestamp": latest_timestamp,
                }
                result = {"success": True, "data": latest_macd}
                self._set_in_cache(cache_key, result)
                return result
            else:
                return {"success": False, "error": "Could not fetch MACD data"}

        except Exception:
            logger.exception("Failed to fetch MACD data for %s%s", from_currency, to_currency)
            return {"success": False, "error": "Market data provider request failed"}

    def analyze_signal(self, currency_pair: str) -> dict[str, Any]:
        """Analyze multiple indicators to generate trading signal"""
        from_curr, to_curr = currency_pair[:3], currency_pair[3:]

        # Get indicators
        rsi_result = self.get_rsi(from_curr, to_curr)
        macd_result = self.get_macd(from_curr, to_curr)

        signal: dict[str, Any] = {
            "currency_pair": currency_pair,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "indicators": {},
            "signal": "NEUTRAL",
            "strength": 0,
        }

        if rsi_result.get("success"):
            rsi = rsi_result["rsi"]
            signal["indicators"]["rsi"] = rsi

            # RSI signals
            if rsi < 30:
                signal["signal"] = "BUY"
                signal["strength"] += 30
            elif rsi > 70:
                signal["signal"] = "SELL"
                signal["strength"] += 30

        if macd_result.get("success"):
            macd_data = macd_result["data"]
            signal["indicators"]["macd"] = macd_data

            # MACD crossover signals
            if macd_data["macd"] > macd_data["signal"] and macd_data["hist"] > 0:
                if signal["signal"] in ("BUY", "NEUTRAL"):
                    signal["signal"] = "BUY"
                    signal["strength"] += 20
            elif macd_data["macd"] < macd_data["signal"] and macd_data["hist"] < 0:
                if signal["signal"] in ("SELL", "NEUTRAL"):
                    signal["signal"] = "SELL"
                    signal["strength"] += 20

        signal["strength"] = min(100, signal["strength"])
        return signal


# Mock data provider for development/testing
class MockForexDataProvider:
    """Deterministic development provider; it never generates random prices."""

    def get_forex_intraday(self, from_currency="EUR", to_currency="USD", interval="5min"):
        """Return mock forex data"""
        prices = {
            "EURUSD": "1.08500",
            "GBPUSD": "1.27000",
            "USDJPY": "150.000",
            "AUDUSD": "0.65500",
            "USDCAD": "1.35000",
            "USDCHF": "0.90000",
            "NZDUSD": "0.61000",
        }
        symbol, price = f"{from_currency}{to_currency}", prices.get(f"{from_currency}{to_currency}")
        if price is None:
            return {"success": False, "error": f"No deterministic paper price for {symbol}"}
        timestamp = datetime.now(timezone.utc).isoformat()
        return {
            "success": True,
            "data": [{"time": timestamp, "open": price, "high": price, "low": price, "close": price}],
        }

    def analyze_signal(self, currency_pair):
        """Return an intentionally neutral deterministic development signal."""
        return {
            "currency_pair": currency_pair,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "indicators": {"rsi": 50, "macd": {"macd": 0, "signal": 0, "hist": 0}},
            "signal": "NEUTRAL",
            "strength": 0,
        }


# Use real or mock provider based on API key availability
def get_forex_provider():
    """Select a market-data mode explicitly.

    Simulation is the safe default. External data is opt-in via
    ``MARKET_DATA_PROVIDER=alphavantage`` and a non-demo API key; an API key
    alone can never silently change the product mode.
    """
    mode = os.environ.get("MARKET_DATA_PROVIDER", "simulation").strip().lower()
    if mode in {"simulation", "paper", "mock"}:
        return MockForexDataProvider()
    if mode in {"alphavantage", "alpha_vantage", "external"}:
        api_key = os.environ.get("ALPHA_VANTAGE_API_KEY", "").strip()
        if not api_key or api_key.lower() == "demo":
            raise RuntimeError(
                f"Explicit market data mode '{mode}' requires ALPHA_VANTAGE_API_KEY to be configured with a valid key"
            )
        cache_ttl = int(os.environ.get("MARKET_DATA_CACHE_TTL", "60"))
        max_staleness = int(os.environ.get("MARKET_DATA_MAX_STALENESS", "86400"))
        return ForexDataProvider(api_key=api_key, cache_ttl_seconds=cache_ttl, max_staleness_seconds=max_staleness)
    raise RuntimeError(f"Unsupported market-data provider mode: {mode}")
