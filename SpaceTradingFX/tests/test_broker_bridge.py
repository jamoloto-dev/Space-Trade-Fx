"""Comprehensive tests for MT4/MT5 Broker Execution Bridge and Credential Vault."""

from __future__ import annotations

from decimal import Decimal

import pytest
from flask_dashboard import create_app
from flask_dashboard.extensions import db
from flask_dashboard.license_manager import create_user_license
from flask_dashboard.models import BrokerAccount, User
from flask_dashboard.services.broker_bridge import (
    ORDER_FILLING_FOK,
    ORDER_FILLING_IOC,
    BrokerConnectionError,
    BrokerValidationError,
    decrypt_broker_password,
    encrypt_broker_password,
    execute_robot_trade,
    normalize_volume,
    resolve_filling_mode,
    verify_and_connect,
)
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
    return test_app_client(app)


def test_app_client(app):
    return app.test_client()


def test_symmetric_credential_encryption_and_decryption(app):
    with app.app_context():
        raw_password = "InstitutionalTraderPassword99#!"
        encrypted = encrypt_broker_password(raw_password)

        assert encrypted != raw_password
        assert not encrypted.startswith(raw_password)
        assert len(encrypted) > 40

        decrypted = decrypt_broker_password(encrypted)
        assert decrypted == raw_password


def test_encryption_rejects_empty_inputs(app):
    with app.app_context():
        with pytest.raises(BrokerValidationError):
            encrypt_broker_password("")
        with pytest.raises(BrokerValidationError):
            decrypt_broker_password("")


def test_verify_and_connect_success(app):
    with app.app_context():
        res_mt5 = verify_and_connect("MT5", "IFXBrokersHoldings-Real", "906777242", "SecretPass123")
        assert res_mt5["success"] is True
        assert res_mt5["platform"] == "MT5"
        assert res_mt5["server"] == "IFXBrokersHoldings-Real"
        assert res_mt5["login"] == "906777242"
        assert res_mt5["currency"] == "USD"

        res_mt4 = verify_and_connect("MT4", "IFXBrokers-Live", 12345678, "SecretPass123")
        assert res_mt4["success"] is True
        assert res_mt4["platform"] == "MT4"


def test_verify_and_connect_validations(app):
    with app.app_context():
        with pytest.raises(BrokerValidationError, match="Unsupported trading platform"):
            verify_and_connect("cTrader", "IFXBrokersHoldings-Real", "12345", "pass")

        with pytest.raises(BrokerValidationError, match="Invalid broker server name"):
            verify_and_connect("MT5", "ab", "12345", "pass")

        with pytest.raises(BrokerValidationError, match="Invalid account login ID"):
            verify_and_connect("MT5", "IFXBrokersHoldings-Real", "not-a-number", "pass")

        with pytest.raises(BrokerValidationError, match="Invalid broker password"):
            verify_and_connect("MT5", "IFXBrokersHoldings-Real", "12345", "12")


def test_broker_account_model_and_persistence(app):
    with app.app_context():
        user = User(id="user-broker-1", email="broker_trader@example.com")
        user.set_password("SecurePassword123!")
        db.session.add(user)
        db.session.commit()

        encrypted = encrypt_broker_password("RealMT5Password99")
        account = BrokerAccount(
            user_id=user.id,
            platform="MT5",
            server="IFXBrokersHoldings-Real",
            account_login="906777242",
            encrypted_password=encrypted,
            is_connected=True,
        )
        db.session.add(account)
        db.session.commit()

        queried = BrokerAccount.query.filter_by(user_id=user.id).first()
        assert queried is not None
        assert queried.platform == "MT5"
        assert queried.server == "IFXBrokersHoldings-Real"
        assert queried.account_login == "906777242"
        assert queried.encrypted_password != "RealMT5Password99"
        assert decrypt_broker_password(queried.encrypted_password) == "RealMT5Password99"
        assert queried.is_connected is True


def test_connect_broker_view_and_disconnect_flow(app):
    client = app.test_client()

    with app.app_context():
        user = User(id="ui-trader-1", email="uitrader@example.com")
        user.set_password("SecureTraderPass1!")
        db.session.add(user)
        db.session.commit()
        create_user_license(user.id, "premium")

    # 1. Unauthenticated gets redirected
    res_unauth = client.get("/m/connect-broker")
    assert res_unauth.status_code == 302

    # 2. Login
    client.post("/login", data={"email": "uitrader@example.com", "password": "SecureTraderPass1!"})

    # 3. View connect broker page
    res_page = client.get("/m/connect-broker")
    assert res_page.status_code == 200
    assert b"Enter Your Broker Details" in res_page.data
    assert b"Authorization allows Space-Trade-Fx access to the trading account" in res_page.data
    assert b"Trading Platform" in res_page.data
    assert b"Continue" in res_page.data

    # 4. Route alias /connect-broker redirects to mobile view
    alias_res = client.get("/connect-broker")
    assert alias_res.status_code == 302
    assert "/m/connect-broker" in alias_res.headers["Location"]

    # 5. Profile page shows Disconnected status
    prof_before = client.get("/m/profile")
    assert prof_before.status_code == 200
    assert b"Disconnected" in prof_before.data
    assert b"Connect Your Account" in prof_before.data

    # 6. Submit broker credentials
    post_res = client.post(
        "/m/connect-broker",
        data={
            "platform": "MT5",
            "server": "IFXBrokersHoldings-Real",
            "login": "906777242",
            "password": "MySuperSecretBrokerPassword",
        },
        follow_redirects=True,
    )
    assert post_res.status_code == 200
    assert b"Successfully connected to IFXBrokersHoldings-Real (MT5)!" in post_res.data

    # 7. Check database record
    with app.app_context():
        saved = BrokerAccount.query.filter_by(user_id="ui-trader-1").first()
        assert saved is not None
        assert saved.is_connected is True
        assert saved.server == "IFXBrokersHoldings-Real"
        assert saved.account_login == "906777242"
        assert decrypt_broker_password(saved.encrypted_password) == "MySuperSecretBrokerPassword"

    # 8. Profile page now displays Connected status badge
    prof_after = client.get("/m/profile")
    assert prof_after.status_code == 200
    assert b"Connected" in prof_after.data
    assert b"IFXBrokersHoldings-Real" in prof_after.data

    # 9. Disconnect action
    disc_res = client.post(
        "/m/connect-broker",
        data={"action": "disconnect"},
        follow_redirects=True,
    )
    assert disc_res.status_code == 200
    assert b"Broker account disconnected successfully." in disc_res.data

    with app.app_context():
        saved = BrokerAccount.query.filter_by(user_id="ui-trader-1").first()
        assert saved.is_connected is False


def test_execute_robot_trade_with_connected_account(app):
    with app.app_context():
        user = User(id="robot-user-1", email="robot@example.com")
        user.set_password("SecureRobot123!")
        db.session.add(user)
        db.session.commit()
        create_user_license(user.id, "professional")

        account = BrokerAccount(
            user_id=user.id,
            platform="MT5",
            server="IFXBrokersHoldings-Real",
            account_login="906777242",
            encrypted_password=encrypt_broker_password("LiveTraderPass#1"),
            is_connected=True,
        )
        db.session.add(account)
        db.session.commit()

        # Valid BUY execution
        report = execute_robot_trade(
            user_id=user.id,
            symbol="EURUSD",
            order_type="BUY",
            volume=Decimal("0.10"),
            sl=Decimal("1.07500"),
            tp=Decimal("1.09500"),
            current_price=Decimal("1.08500"),
        )
        assert report["success"] is True
        assert report["symbol"] == "EURUSD"
        assert report["order_type"] == "BUY"
        assert report["volume"] == 0.10
        assert report["ticket"] is not None
        assert report["status"] == "FILLED"

        # Check account last_synced_at was updated
        db.session.refresh(account)
        assert account.last_synced_at is not None

        # Risk validation rejection (BUY with SL >= TP)
        with pytest.raises(BrokerValidationError, match="Stop-loss .* must be strictly below Take-profit"):
            execute_robot_trade(
                user_id=user.id,
                symbol="EURUSD",
                order_type="BUY",
                volume=Decimal("0.10"),
                sl=Decimal("1.09500"),
                tp=Decimal("1.07500"),
            )


def test_execute_robot_trade_rejects_disconnected_account(app):
    with app.app_context():
        user = User(id="robot-disc-1", email="robotdisc@example.com")
        user.set_password("SecureRobot123!")
        db.session.add(user)
        db.session.commit()

        account = BrokerAccount(
            user_id=user.id,
            platform="MT4",
            server="ICMarkets-Live",
            account_login="888888",
            encrypted_password=encrypt_broker_password("Pass123"),
            is_connected=False,
        )
        db.session.add(account)
        db.session.commit()

        with pytest.raises(BrokerConnectionError, match="No active, connected MT4/MT5 broker account"):
            execute_robot_trade(user_id=user.id, symbol="EURUSD", order_type="BUY", volume=0.01)


def test_trading_engine_robot_signal_dispatches_to_connected_broker(app):
    with app.app_context():
        user = User(id="engine-trader-1", email="enginetrader@example.com")
        user.set_password("SecureEngine123!")
        db.session.add(user)
        db.session.commit()
        create_user_license(user.id, "professional")

        account = BrokerAccount(
            user_id=user.id,
            platform="MT5",
            server="Pepperstone-MT5Live",
            account_login="777666",
            encrypted_password=encrypt_broker_password("LivePass123"),
            is_connected=True,
        )
        db.session.add(account)
        db.session.commit()

        engine = TradingEngine(user_id=user.id)
        engine.preferences.trading_enabled = True
        db.session.commit()
        trade = engine.execute_trade(currency_pair="EURUSD", signal_type="BUY")

        assert trade is not None
        assert trade.mt5_ticket is not None
        assert trade.broker_order_id == trade.mt5_ticket
        assert trade.broker_response is not None
        assert trade.broker_response["status"] == "FILLED"
        assert trade.signal_data.get("broker_execution") is not None


def test_normalize_volume_deriv_and_ifx():
    # Deriv Volatility 75 Index: min 0.001, step 0.001
    assert normalize_volume("Volatility 75 Index", 0.0001) == Decimal("0.001")
    assert normalize_volume("Volatility 75 Index", 0.0034) == Decimal("0.003")
    assert normalize_volume("Volatility 75 Index", 0.0036) == Decimal("0.004")

    # Deriv Boom 1000 Index: min 0.20, step 0.01
    assert normalize_volume("Boom 1000 Index", 0.01) == Decimal("0.20")
    assert normalize_volume("Boom 1000 Index", 0.25) == Decimal("0.25")

    # Deriv Volatility 100 Index: min 0.50, step 0.01
    assert normalize_volume("Volatility 100 Index", 0.10) == Decimal("0.50")
    assert normalize_volume("Volatility 100 Index", 1.256) == Decimal("1.26")

    # IFX Brokers standard Forex: min 0.01, step 0.01
    assert normalize_volume("EURUSD", 0.005) == Decimal("0.01")
    assert normalize_volume("EURUSD", 0.01) == Decimal("0.01")
    assert normalize_volume("EURUSD", 0.024) == Decimal("0.02")

    # Clamping maximum
    assert normalize_volume("EURUSD", 500) == Decimal("100.00")

    # Rejection of invalid volume
    with pytest.raises(BrokerValidationError, match="Volume must be strictly positive"):
        normalize_volume("EURUSD", 0)


def test_resolve_filling_mode_deriv_and_ifx():
    # Deriv synthetic indices require FOK
    assert resolve_filling_mode(server="Deriv-Server") == ORDER_FILLING_FOK
    assert resolve_filling_mode(server="Deriv-Demo") == ORDER_FILLING_FOK
    assert resolve_filling_mode(server="Deriv-Server-02") == ORDER_FILLING_FOK

    # Deriv Volatility symbol spec
    deriv_spec = {"filling_mode": "FOK"}
    assert resolve_filling_mode(symbol_spec=deriv_spec) == ORDER_FILLING_FOK

    # IFX Brokers requires IOC
    assert resolve_filling_mode(server="IFXBrokers-Live") == ORDER_FILLING_IOC
    assert resolve_filling_mode(server="IFXBrokers-Demo") == ORDER_FILLING_IOC
    ifx_spec = {"filling_mode": "IOC"}
    assert resolve_filling_mode(symbol_spec=ifx_spec) == ORDER_FILLING_IOC


def test_api_broker_test_trade_endpoint_deriv(app):
    client = app.test_client()
    with app.app_context():
        user = User(id="deriv-trader-1", email="deriv@example.com")
        user.set_password("DerivPass123!")
        db.session.add(user)
        db.session.commit()
        create_user_license(user.id, "professional")

        account = BrokerAccount(
            user_id=user.id,
            platform="MT5",
            server="Deriv-Server",
            account_login="10293847",
            encrypted_password=encrypt_broker_password("DerivPassword#1"),
            is_connected=True,
        )
        db.session.add(account)
        db.session.commit()

    # Login
    client.post("/login", data={"email": "deriv@example.com", "password": "DerivPass123!"})

    # Trigger test ping trade
    res = client.post("/api/broker/test-trade")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["symbol"] == "Volatility 75 Index"
    assert data["volume"] == 0.001
    assert data["ticket_id"] is not None
    assert data["server"] == "Deriv-Server"
    assert "filled successfully" in data["message"]


def test_api_broker_test_trade_endpoint_ifx(app):
    client = app.test_client()
    with app.app_context():
        user = User(id="ifx-trader-1", email="ifx@example.com")
        user.set_password("IFXPass123!")
        db.session.add(user)
        db.session.commit()
        create_user_license(user.id, "premium")

        account = BrokerAccount(
            user_id=user.id,
            platform="MT5",
            server="IFXBrokers-Live",
            account_login="55544433",
            encrypted_password=encrypt_broker_password("IFXPassword#1"),
            is_connected=True,
        )
        db.session.add(account)
        db.session.commit()

    # Login
    client.post("/login", data={"email": "ifx@example.com", "password": "IFXPass123!"})

    # Trigger test ping trade via mobile prefix route
    res = client.post("/m/api/broker/test-trade")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["symbol"] == "EURUSD"
    assert data["volume"] == 0.01
    assert data["ticket_id"] is not None
    assert data["server"] == "IFXBrokers-Live"


def test_api_broker_test_trade_without_account(app):
    client = app.test_client()
    with app.app_context():
        user = User(id="no-broker-user", email="nobroker@example.com")
        user.set_password("NoBrokerPass1!")
        db.session.add(user)
        db.session.commit()
        create_user_license(user.id, "basic")

    client.post("/login", data={"email": "nobroker@example.com", "password": "NoBrokerPass1!"})
    res = client.post("/api/broker/test-trade")
    assert res.status_code == 400
    data = res.get_json()
    assert data["success"] is False
    assert "No active, connected broker account found" in data["error"]


def test_api_broker_execute_signal_endpoint(app):
    client = app.test_client()
    with app.app_context():
        user = User(id="signal-user-1", email="siguser@example.com")
        user.set_password("SigPass123!")
        db.session.add(user)
        db.session.commit()
        create_user_license(user.id, "basic")
        account = BrokerAccount(
            user_id=user.id,
            platform="MT5",
            server="IFXBrokers-Real",
            account_login="2160203",
            encrypted_password=encrypt_broker_password("realPassword123"),
            is_connected=True,
        )
        db.session.add(account)
        db.session.commit()

    client.post("/login", data={"email": "siguser@example.com", "password": "SigPass123!"})
    res = client.post(
        "/api/broker/execute-signal",
        json={
            "symbol": "USDZAR",
            "order_type": "BUY",
            "lot_size": 0.05,
            "price": 18.2500,
            "stop_loss": 18.1500,
            "take_profit": 18.5000,
        },
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["symbol"] == "USDZAR"
    assert data["order_type"] == "BUY"
    assert data["ticket"] is not None

    with app.app_context():
        from flask_dashboard.models import Trade

        saved_trade = Trade.query.filter_by(user_id="signal-user-1", currency_pair="USDZAR").first()
        assert saved_trade is not None
        assert saved_trade.status == "open"
        assert saved_trade.trade_type == "BUY"


def test_api_trading_toggle_auto_pilot_endpoint(app):
    client = app.test_client()
    with app.app_context():
        user = User(id="ap-user-1", email="apuser@example.com")
        user.set_password("ApPass123!")
        db.session.add(user)
        db.session.commit()

    client.post("/login", data={"email": "apuser@example.com", "password": "ApPass123!"})
    # Toggle ON
    res_on = client.post("/api/trading/toggle-auto-pilot", json={"enabled": True})
    assert res_on.status_code == 200
    assert res_on.get_json()["enabled"] is True

    with app.app_context():
        from flask_dashboard.models import TradingPreference

        pref = TradingPreference.query.filter_by(user_id="ap-user-1").first()
        assert pref.trading_enabled is True
        assert pref.strategy_settings.get("auto_pilot") is True

    # Toggle OFF
    res_off = client.post("/api/trading/toggle-auto-pilot", json={"enabled": False})
    assert res_off.status_code == 200
    assert res_off.get_json()["enabled"] is False


def test_dynamic_currency_telemetry(app):
    with app.app_context():
        from flask_dashboard.services.broker_bridge import (
            get_account_currency,
            get_broker_telemetry,
        )

        zar_code, zar_sym = get_account_currency("IFXBrokers-Real")
        assert zar_code == "ZAR"
        assert zar_sym == "R"

        usd_code, usd_sym = get_account_currency("Deriv-Demo")
        assert usd_code == "USD"
        assert usd_sym == "$"

        user = User(id="telemetry-user", email="tele@example.com")
        user.set_password("TelePass123!")
        db.session.add(user)
        db.session.commit()

        account = BrokerAccount(
            user_id=user.id,
            platform="MT5",
            server="IFXBrokers-Real",
            account_login="2160203",
            encrypted_password=encrypt_broker_password("pass"),
            is_connected=True,
        )
        db.session.add(account)
        db.session.commit()

        telemetry = get_broker_telemetry("telemetry-user")
        assert telemetry["connected"] is True
        assert telemetry["currency"] == "ZAR"
        assert telemetry["currency_symbol"] == "R"
        assert telemetry["balance"] == Decimal("3000.00")


def test_autonomous_scanner_cycle(app):
    with app.app_context():
        from flask_dashboard.services.autonomous_scanner import run_autonomous_cycle

        report = run_autonomous_cycle(app, force_scan=True)
        assert "timestamp" in report
        assert "users_processed" in report


def test_resolve_metaapi_client_base_url_removes_duplicate_suffix(monkeypatch):
    from flask_dashboard.services.broker_bridge import resolve_metaapi_client_base_url

    # 1. Custom URL with duplicated agiliumtrade.agiliumtrade.ai
    monkeypatch.setenv("METAAPI_CLIENT_HOST", "mt-client-api-v1.agiliumtrade.agiliumtrade.ai")
    url = resolve_metaapi_client_base_url()
    assert url == "https://mt-client-api-v1.agiliumtrade.ai"
    assert "agiliumtrade.agiliumtrade.ai" not in url

    # 2. Configured region
    monkeypatch.delenv("METAAPI_CLIENT_HOST", raising=False)
    monkeypatch.setenv("METAAPI_REGION", "london")
    assert resolve_metaapi_client_base_url() == "https://mt-client-api-v1.london.agiliumtrade.ai"

    monkeypatch.setenv("METAAPI_REGION", "vint-hill")
    assert resolve_metaapi_client_base_url() == "https://mt-client-api-v1.vint-hill.agiliumtrade.ai"


def test_metaapi_cloud_trade_dispatch_uses_clean_url(app, monkeypatch):
    from unittest.mock import MagicMock, patch

    monkeypatch.setenv("METAAPI_TOKEN", "mock_metaapi_token_123")
    monkeypatch.setenv("METAAPI_ACCOUNT_ID", "mock_acc_999")
    monkeypatch.setenv("METAAPI_REGION", "london")

    with app.app_context():
        user = User(id="metaapi-test-trader", email="metaapi@example.com")
        user.set_password("MetaPass123!")
        db.session.add(user)
        db.session.commit()
        create_user_license(user.id, "professional")

        account = BrokerAccount(
            user_id=user.id,
            platform="MT5",
            server="IFXBrokers-Real",
            account_login="1861949",
            encrypted_password=encrypt_broker_password("Pass123"),
            is_connected=True,
        )
        db.session.add(account)
        db.session.commit()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "orderId": "metaapi-ticket-777",
            "openPrice": 1.08500,
        }

        app.config["TESTING"] = False
        try:
            with patch("requests.post", return_value=mock_resp) as mock_post:
                result = execute_robot_trade(
                    user_id=user.id,
                    symbol="EURUSD",
                    order_type="BUY",
                    volume=Decimal("0.01"),
                    sl=Decimal("1.07500"),
                    tp=Decimal("1.09500"),
                    current_price=Decimal("1.08500"),
                )

                assert result["success"] is True
                assert result["ticket"] == "metaapi-ticket-777"
                assert result["mode"] == "metaapi_cloud"

                # Verify the URL posted to has no duplicated domain suffix
                mock_post.assert_called_once()
                called_url = mock_post.call_args[0][0]
                assert (
                    called_url
                    == "https://mt-client-api-v1.london.agiliumtrade.ai/users/current/accounts/mock_acc_999/trade"
                )
                assert "agiliumtrade.agiliumtrade.ai" not in called_url
        finally:
            app.config["TESTING"] = True


def test_api_broker_telemetry_endpoint(app, client):
    with app.app_context():
        user = User(id="telem-user-1", email="telem@example.com")
        user.set_password("SecurePassword123!")
        db.session.add(user)

        account = BrokerAccount(
            user_id="telem-user-1",
            platform="MT5",
            server="IFXBrokers-Real",
            account_login="1861949",
            encrypted_password=encrypt_broker_password("Pass123"),
            is_connected=True,
            balance=Decimal("6.03"),
            currency="USD",
        )
        db.session.add(account)
        db.session.commit()

        with client.session_transaction() as sess:
            sess["_user_id"] = "telem-user-1"

        resp = client.get("/api/broker/telemetry")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["connected"] is True
        assert data["currency"] == "USD"
        assert data["currency_symbol"] == "$"
        assert float(data["balance"]) == 6.03
