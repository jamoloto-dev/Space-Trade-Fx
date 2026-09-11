"""Tests for market data provider selection, caching, and staleness enforcement."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from flask_dashboard.forex_data import (
    ForexDataProvider,
    MockForexDataProvider,
    get_forex_provider,
)


def test_provider_mode_defaults_to_simulation_even_with_api_key(monkeypatch):
    monkeypatch.delenv("MARKET_DATA_PROVIDER", raising=False)
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "real-api-key-12345")

    provider = get_forex_provider()
    assert isinstance(provider, MockForexDataProvider)


def test_provider_mode_explicit_alpha_vantage_without_key_fails(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "alphavantage")
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="requires ALPHA_VANTAGE_API_KEY"):
        get_forex_provider()

    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "demo")
    with pytest.raises(RuntimeError, match="requires ALPHA_VANTAGE_API_KEY"):
        get_forex_provider()


def test_provider_mode_explicit_alpha_vantage_with_key_succeeds(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "alphavantage")
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "my-secret-key")

    provider = get_forex_provider()
    assert isinstance(provider, ForexDataProvider)
    assert provider.api_key == "my-secret-key"


def test_forex_data_provider_caching():
    provider = ForexDataProvider(api_key="test-key", cache_ttl_seconds=60)
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "Time Series FX (5min)": {
            now_str: {
                "1. open": "1.0850",
                "2. high": "1.0860",
                "3. low": "1.0840",
                "4. close": "1.0855",
            }
        }
    }

    with patch("requests.get", return_value=mock_response) as mock_get:
        # First call hits external provider
        res1 = provider.get_forex_intraday("EUR", "USD", "5min")
        assert res1["success"] is True
        assert len(res1["data"]) == 1
        assert mock_get.call_count == 1

        # Second call within TTL hits cache
        res2 = provider.get_forex_intraday("EUR", "USD", "5min")
        assert res2["success"] is True
        assert mock_get.call_count == 1

        # After cache clear, hits external provider again
        provider.clear_cache()
        res3 = provider.get_forex_intraday("EUR", "USD", "5min")
        assert res3["success"] is True
        assert mock_get.call_count == 2


def test_forex_data_provider_staleness_enforcement():
    # Set max staleness to 300 seconds (5 minutes)
    provider = ForexDataProvider(api_key="test-key", cache_ttl_seconds=60, max_staleness_seconds=300)

    # 1 hour old data
    stale_time = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "Time Series FX (5min)": {
            stale_time: {
                "1. open": "1.0850",
                "2. high": "1.0860",
                "3. low": "1.0840",
                "4. close": "1.0855",
            }
        }
    }

    with patch("requests.get", return_value=mock_response):
        res = provider.get_forex_intraday("EUR", "USD", "5min")
        assert res["success"] is False
        assert res.get("stale") is True
        assert "stale" in res.get("error", "").lower()
