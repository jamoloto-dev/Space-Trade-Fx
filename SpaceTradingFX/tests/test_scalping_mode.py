"""Tests for Ultra-Fast Scalping Mode (M1/M5 Timeframes & Tight SL/TP)."""

import pytest
from flask_dashboard import create_app
from flask_dashboard.extensions import db
from flask_dashboard.forex_data import LiveMarketScanner, MockForexDataProvider
from flask_dashboard.models import TradingPreference, User


@pytest.fixture
def app_and_client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

    with app.app_context():
        db.create_all()
        user = User(
            id="test-scalper-user",
            email="scalper@spacetradingfx.com",
            first_name="Scalper",
            last_name="Pro",
            password_hash="argon2-hash",
        )
        db.session.add(user)
        db.session.commit()

        client = app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(user.id)

        yield app, client, user

        db.session.remove()
        db.drop_all()


def test_mock_provider_scalping_vs_swing_sl_tp():
    """Verify MockForexDataProvider scales SL to 1.0x ATR and TP to 1.5x ATR for scalping."""
    provider = MockForexDataProvider()

    # Swing mode (1H)
    swing_sig = provider.analyze_signal("EURUSD", timeframe="1H")
    assert swing_sig["trading_mode"] == "swing"
    entry = swing_sig["entry_price"]
    swing_atr = swing_sig["indicators"]["atr"]
    # Swing: SL = entry - 1.5 * atr, TP = entry + 2.5 * atr
    assert round(swing_sig["stop_loss"], 5) == round(entry - 1.5 * swing_atr, 5)
    assert round(swing_sig["take_profit"], 5) == round(entry + 2.5 * swing_atr, 5)

    # Scalping mode (5M)
    scalp_sig = provider.analyze_signal("EURUSD", timeframe="5M")
    assert scalp_sig["trading_mode"] == "scalping"
    scalp_atr = scalp_sig["indicators"]["atr"]
    # Scalping: SL = entry - 1.0 * atr, TP = entry + 1.5 * atr
    assert round(scalp_sig["stop_loss"], 5) == round(entry - 1.0 * scalp_atr, 5)
    assert round(scalp_sig["take_profit"], 5) == round(entry + 1.5 * scalp_atr, 5)
    assert "rsi7" in scalp_sig["indicators"]
    assert "ema5" in scalp_sig["indicators"]
    assert "ema13" in scalp_sig["indicators"]
    assert "atr5" in scalp_sig["indicators"]


def test_live_scanner_fallback_scalping():
    """Verify LiveMarketScanner fallback computes tight scalping SL/TP."""
    scanner = LiveMarketScanner(cache_ttl_seconds=0)

    # Force fallback by passing invalid ticker
    scalp_res = scanner.analyze_signal("USDZAR", timeframe="5M", direction_preference="BUY")
    assert scalp_res["trading_mode"] == "scalping"
    atr = scalp_res["indicators"]["atr"]
    price = scalp_res["price"]
    # BUY: SL = price - 1.0 * atr, TP = price + 1.5 * atr
    assert scalp_res["stop_loss"] == round(price - 1.0 * atr, 4)
    assert scalp_res["take_profit"] == round(price + 1.5 * atr, 4)
    assert scalp_res["indicators"]["rsi7"] is not None
    assert scalp_res["indicators"]["ema5"] is not None
    assert scalp_res["indicators"]["ema13"] is not None


def test_live_scanner_fallback_when_yfinance_uninstalled(monkeypatch):
    """Verify LiveMarketScanner gracefully handles ModuleNotFoundError for yfinance without UnboundLocalError."""
    import builtins

    orig_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "yfinance":
            raise ModuleNotFoundError("No module named 'yfinance'")
        return orig_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)

    scanner = LiveMarketScanner(cache_ttl_seconds=0)
    res_swing = scanner.analyze_signal("EURUSD", timeframe="1H")
    assert res_swing["trading_mode"] == "swing"
    assert res_swing["data_mode"] == "live_fallback"

    res_scalp = scanner.analyze_signal("EURUSD", timeframe="5M")
    assert res_scalp["trading_mode"] == "scalping"
    assert res_scalp["data_mode"] == "live_fallback"


def test_toggle_trading_mode_api(app_and_client):
    """Verify POST /api/trading/toggle-mode toggles mode and updates timeframe."""
    app, client, user = app_and_client

    # 1. Switch to scalping
    res = client.post("/api/trading/toggle-mode", json={"mode": "scalping"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["mode"] == "scalping"
    assert data["timeframe"] == "5M"

    with app.app_context():
        pref = TradingPreference.query.filter_by(user_id=user.id).first()
        assert pref is not None
        assert pref.timeframe == "5M"
        assert (pref.strategy_settings or {}).get("trading_mode") == "scalping"

    # 2. Switch back to swing
    res = client.post("/api/trading/toggle-mode", json={"mode": "swing"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["mode"] == "swing"
    assert data["timeframe"] == "1H"

    with app.app_context():
        pref = TradingPreference.query.filter_by(user_id=user.id).first()
        assert pref.timeframe == "1H"
        assert (pref.strategy_settings or {}).get("trading_mode") == "swing"

    # 3. Invalid mode rejection
    res_bad = client.post("/api/trading/toggle-mode", json={"mode": "arbitrage"})
    assert res_bad.status_code == 400
    assert "Invalid trading mode" in res_bad.get_json()["error"]


def test_ui_renders_scalping_switch_and_instant_execute(app_and_client):
    """Verify /m/quotes and /m/history render strategy switcher and scalping cards."""
    app, client, user = app_and_client

    with app.app_context():
        pref = TradingPreference(
            user_id=user.id,
            timeframe="5M",
            strategy_settings={"trading_mode": "scalping", "lot_sizes": {"EURUSD": "0.02"}},
        )
        db.session.add(pref)
        db.session.commit()

    # Check /m/quotes
    res_quotes = client.get("/m/quotes")
    assert res_quotes.status_code == 200
    html_quotes = res_quotes.get_data(as_text=True)
    assert "STRATEGY EXECUTION ENGINE" in html_quotes
    assert "Ultra Scalping (M1/M5)" in html_quotes
    assert "switchTradingMode" in html_quotes

    # Check /m/history?tab=analysing
    res_hist = client.get("/m/history?tab=analysing")
    assert res_hist.status_code == 200
    html_hist = res_hist.get_data(as_text=True)
    assert "EXECUTION TIMEFRAME" in html_hist
    assert "M1/M5 SCALPING" in html_hist
    assert "switchTradingModeHistory" in html_hist
