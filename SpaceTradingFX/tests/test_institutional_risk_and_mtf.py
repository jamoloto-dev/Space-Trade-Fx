"""Test Institutional Risk Management, Multi-Timeframe Confluence, and Quote Config Enforcements."""

from decimal import Decimal

import pytest
from flask_dashboard import create_app
from flask_dashboard.extensions import db
from flask_dashboard.forex_data import LiveMarketScanner, is_high_liquidity_session, is_rollover_window
from flask_dashboard.models import BrokerAccount, Trade, TradingPreference, User
from flask_dashboard.services.autonomous_scanner import run_autonomous_cycle
from flask_dashboard.trading_engine import TradingEngine


@pytest.fixture
def app():
    test_app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
            "RATELIMIT_ENABLED": False,
            "BROKER_ENCRYPTION_KEY": "test-institutional-broker-encryption-key-for-unit-tests",
        }
    )
    with test_app.app_context():
        db.create_all()
        yield test_app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def risk_user(app):
    with app.app_context():
        user = User(
            id="test-risk-user",
            email="risk-user@institutional.fx",
            first_name="Risk",
            last_name="Officer",
            password_hash="argon2-hash",
        )
        db.session.add(user)

        prefs = TradingPreference(
            user_id="test-risk-user",
            currency_pairs=["EURUSD", "XAUUSD", "USDZAR"],
            direction_preferences={"XAUUSD": "BUY", "USDZAR": "SELL"},
            strategy_settings={
                "lot_sizes": {"XAUUSD": "0.02", "USDZAR": "0.05"},
                "auto_pilot": True,
                "max_daily_loss_pct": "5.0",
            },
            trading_enabled=True,
        )
        db.session.add(prefs)

        account = BrokerAccount(
            user_id="test-risk-user",
            platform="MT5",
            server="IFXBrokers-Real",
            account_login="2160203",
            encrypted_password="enc",
            currency="ZAR",
            balance=Decimal("3000.00"),
            equity=Decimal("3000.00"),
            free_margin=Decimal("3000.00"),
            is_connected=True,
        )
        db.session.add(account)
        db.session.commit()
        yield user


def test_quotes_update_config_api(client, risk_user):
    with client.session_transaction() as sess:
        sess["_user_id"] = "test-risk-user"

    # Test updating lot size and direction
    resp = client.post(
        "/api/quotes/update-config",
        json={"pair": "XAUUSD", "lot_size": "0.03", "direction": "BUY"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["pair"] == "XAUUSD"
    assert data["direction"] == "BUY"
    assert data["lot_size"] == "0.0300"

    # Test rejecting unsupported pair
    resp_bad = client.post(
        "/api/quotes/update-config",
        json={"pair": "AAPL", "lot_size": "10"},
    )
    assert resp_bad.status_code == 400


def test_auto_break_even_protection(app, risk_user):
    with app.app_context():
        # Create an open BUY trade: Entry 2000.00, TP 2100.00 (dist 100), SL 1950.00
        # 50% TP distance is 2050.00
        trade = Trade(
            user_id="test-risk-user",
            currency_pair="XAUUSD",
            trade_type="BUY",
            entry_price=Decimal("2000.00"),
            take_profit=Decimal("2100.00"),
            stop_loss=Decimal("1950.00"),
            lot_size=Decimal("0.02"),
            status="open",
            execution_mode="broker",
        )
        db.session.add(trade)
        db.session.commit()

        engine = TradingEngine("test-risk-user")

        # Mock current price reaching 2060.00 (>= 2050.00)
        engine._get_current_price = lambda pair: Decimal("2060.00")
        engine._check_exit_conditions = lambda t, p: False

        engine.update_open_trades()

        refreshed = Trade.query.get(trade.id)
        # Stop loss must be moved to entry price 2000.00 (Break-Even)
        assert refreshed.stop_loss == Decimal("2000.00")


def test_daily_loss_circuit_breaker(app, risk_user):
    with app.app_context():
        # Account balance is R3,000.00; 5% max loss limit is R150.00
        # Create a trade closed today with realized loss of -R250.00
        from flask_dashboard.models import utcnow

        trade = Trade(
            user_id="test-risk-user",
            currency_pair="USDZAR",
            trade_type="SELL",
            entry_price=Decimal("18.0000"),
            exit_price=Decimal("18.5000"),
            take_profit=Decimal("17.0000"),
            stop_loss=Decimal("18.5000"),
            lot_size=Decimal("0.05"),
            profit_loss=Decimal("-250.00"),
            status="closed",
            closed_at=utcnow(),
            execution_mode="broker",
        )
        db.session.add(trade)
        db.session.commit()

        # Run autonomous cycle
        report = run_autonomous_cycle(app, force_scan=True)
        assert report["users_processed"] >= 1

        prefs = TradingPreference.query.filter_by(user_id="test-risk-user").first()
        strat = prefs.strategy_settings or {}
        # Circuit breaker must be tripped and auto-pilot paused!
        assert strat.get("circuit_breaker_tripped") is True
        assert prefs.trading_enabled is False

        # Reset circuit breaker
        from datetime import datetime, timezone
        strat = dict(prefs.strategy_settings or {})
        strat["circuit_breaker_tripped"] = False
        strat["circuit_breaker_date"] = None
        strat["circuit_breaker_pnl"] = "0.00"
        strat["circuit_breaker_reset_at"] = datetime.now(timezone.utc).isoformat()
        prefs.strategy_settings = strat
        prefs.trading_enabled = True
        db.session.commit()

        # Run autonomous cycle again: should NOT re-trip because calc_start filters out prior closed trades
        report2 = run_autonomous_cycle(app, force_scan=True)
        assert report2["users_processed"] >= 1
        prefs2 = TradingPreference.query.filter_by(user_id="test-risk-user").first()
        strat2 = prefs2.strategy_settings or {}
        assert strat2.get("circuit_breaker_tripped") is False
        assert prefs2.trading_enabled is True


def test_multi_timeframe_confluence_and_rollover(app):
    with app.app_context():
        scanner = LiveMarketScanner()
        res = scanner.analyze_signal("EURUSD")
        assert "indicators" in res
        assert "mtf_confluence" in res["indicators"]
        assert "mtf_badge" in res["indicators"]
        assert "M15" in res["indicators"]["mtf_confluence"]
        assert "H1" in res["indicators"]["mtf_confluence"]
        assert "H4" in res["indicators"]["mtf_confluence"]

        # Verify rollover function executes without error
        assert isinstance(is_rollover_window(), bool)
        assert isinstance(is_high_liquidity_session(), bool)


def test_alerts_feed_view(client, risk_user):
    with client.session_transaction() as sess:
        sess["_user_id"] = "test-risk-user"

    resp = client.get("/m/alerts")
    assert resp.status_code == 200
    assert b"ALERTS FEED" in resp.data


def test_market_candles_api(client, risk_user):
    with client.session_transaction() as sess:
        sess["_user_id"] = "test-risk-user"

    # 1. 1h interval
    resp = client.get("/api/market/candles/EURUSD?interval=1h")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["symbol"] == "EURUSD"
    assert data["interval"] == "1h"
    assert isinstance(data["candles"], list)
    assert len(data["candles"]) > 0
    candle = data["candles"][0]
    assert "time" in candle
    assert "open" in candle
    assert "high" in candle
    assert "low" in candle
    assert "close" in candle

    # 2. 15m interval via mobile proxy
    resp15 = client.get("/m/api/market/candles/USDJPY?interval=15m")
    assert resp15.status_code == 200
    data15 = resp15.get_json()
    assert data15["success"] is True
    assert data15["symbol"] == "USDJPY"
    assert len(data15["candles"]) > 0

    # 3. 4h interval
    resp4 = client.get("/api/market/candles/XAUUSD?interval=4h")
    assert resp4.status_code == 200
    data4 = resp4.get_json()
    assert data4["success"] is True
    assert len(data4["candles"]) > 0


def test_chart_modal_rendered_in_history_template(app, client, risk_user):
    with app.app_context():
        open_trade = Trade(
            user_id="test-risk-user",
            currency_pair="EURUSD",
            trade_type="BUY",
            lot_size=Decimal("0.02"),
            entry_price=Decimal("1.12000"),
            stop_loss=Decimal("1.11500"),
            take_profit=Decimal("1.13000"),
            status="open",
            execution_mode="broker",
        )
        db.session.add(open_trade)
        db.session.commit()

    with client.session_transaction() as sess:
        sess["_user_id"] = "test-risk-user"

    resp = client.get("/m/history?filter=open")
    assert resp.status_code == 200
    assert b"chart-modal-overlay" in resp.data
    assert b"VIEW CHART" in resp.data
    assert b"lightweight-charts" in resp.data
    assert b"openChartModal" in resp.data


def test_rate_limiter_localhost_and_authenticated_exemption():
    rate_app = create_app(
        {
            "TESTING": False,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
            "RATELIMIT_ENABLED": True,
            "SECRET_KEY": "test-secret-key-institutional-12345",
            "BROKER_ENCRYPTION_KEY": "test-institutional-broker-encryption-key-for-unit-tests",
        }
    )
    with rate_app.app_context():
        db.create_all()
        user = User(
            id="test-rate-user",
            email="rate-user@institutional.fx",
            first_name="Rate",
            last_name="Tester",
            password_hash="argon2-hash",
        )
        db.session.add(user)
        db.session.commit()

        test_client = rate_app.test_client()
        with test_client.session_transaction() as sess:
            sess["_user_id"] = "test-rate-user"

        # Fire 60 rapid requests from localhost to /m/history
        for _ in range(60):
            res = test_client.get("/m/history", environ_base={"REMOTE_ADDR": "127.0.0.1"})
            # Must NOT return 429
            assert res.status_code != 429, f"Received unexpected HTTP 429: {res.data}"

        db.session.remove()
        db.drop_all()
