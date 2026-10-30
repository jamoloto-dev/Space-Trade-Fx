"""
Unit and integration tests for dynamic MetaApi account synchronization,
ZAR currency formatting, IFX symbol suffix resolution, and in-process daemon.
"""

from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import patch

import pytest
from flask_dashboard import create_app
from flask_dashboard.extensions import db
from flask_dashboard.license_manager import create_user_license
from flask_dashboard.models import BrokerAccount, User
from flask_dashboard.services.broker_bridge import (
    clean_broker_symbol,
    get_account_currency,
    get_active_metaapi_account_id,
    get_broker_telemetry,
    get_currency_symbol,
    get_symbol_spec,
    match_metaapi_account,
    resolve_broker_symbol,
)
from flask_dashboard.services.execution_broker import (
    LiveMetaApiBroker,
    PaperExecutionBroker,
    Position,
)
from flask_dashboard.services.trade_worker import (
    SpaceTradeWorker,
    start_space_trade_worker_daemon,
    stop_space_trade_worker_daemon,
)


@pytest.fixture
def app():
    test_app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
            "SECRET_KEY": "test-sync-key",
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
    with app.test_client() as c:
        with app.app_context():
            user = User(id="sync-test-user-1", email="synctest@example.com")
            user.set_password("SyncPass123!")
            db.session.add(user)
            db.session.commit()
            create_user_license(user.id, "professional")

        # Log in user
        with c.session_transaction() as sess:
            sess["_user_id"] = "sync-test-user-1"
            sess["_fresh"] = True
        return c


MOCK_PROVISIONED_ACCOUNTS = [
    {
        "id": "bace56c1-5847-4977-9ca6-53818e11a2f6",
        "login": "2160203",
        "server": "IFXBrokers-Real",
        "name": "IFX Demo 2160203",
        "type": "cloud",
        "state": "DEPLOYED",
    },
    {
        "id": "f911e0d0-5bdd-400b-9b10-521c304d9d84",
        "login": "1861949",
        "server": "IFXBrokers-Real",
        "name": "IFX Real 1861949",
        "type": "cloud",
        "state": "DEPLOYED",
    },
]


class TestDynamicMetaApiAccountMatching:
    def test_match_metaapi_account_demo_vs_real(self):
        # Match demo login 2160203
        demo_match = match_metaapi_account(MOCK_PROVISIONED_ACCOUNTS, "2160203", "IFXBrokers-Real")
        assert demo_match is not None
        assert demo_match["id"] == "bace56c1-5847-4977-9ca6-53818e11a2f6"
        assert demo_match["login"] == "2160203"

        # Match real login 1861949
        real_match = match_metaapi_account(MOCK_PROVISIONED_ACCOUNTS, 1861949, "IFXBrokers-Real")
        assert real_match is not None
        assert real_match["id"] == "f911e0d0-5bdd-400b-9b10-521c304d9d84"
        assert real_match["login"] == "1861949"

        # Non-existent login returns None
        none_match = match_metaapi_account(MOCK_PROVISIONED_ACCOUNTS, "9999999", "IFXBrokers-Real")
        assert none_match is None

    def test_resolve_metaapi_account_id_persists_to_db(self, app, monkeypatch):
        monkeypatch.setenv("METAAPI_TOKEN", "mock-token-abc")
        monkeypatch.setattr(
            "flask_dashboard.services.broker_bridge.fetch_metaapi_accounts",
            lambda *args, **kwargs: MOCK_PROVISIONED_ACCOUNTS,
        )

        with app.app_context():
            user = User(id="user-auto-sync", email="autosync@example.com")
            user.set_password("Pass123!")
            db.session.add(user)

            account = BrokerAccount(
                user_id="user-auto-sync",
                platform="MT5",
                server="IFXBrokers-Real",
                account_login="2160203",
                encrypted_password="enc",
                is_connected=True,
            )
            db.session.add(account)
            db.session.commit()

            # Dynamic resolution
            resolved_id = get_active_metaapi_account_id("user-auto-sync", account)
            assert resolved_id == "bace56c1-5847-4977-9ca6-53818e11a2f6"

            # Check that account in DB was updated with the resolved UUID
            db_acct = BrokerAccount.query.filter_by(user_id="user-auto-sync").first()
            assert db_acct.metaapi_account_id == "bace56c1-5847-4977-9ca6-53818e11a2f6"

    def test_explicit_metaapi_account_id_override_takes_precedence(self, app):
        with app.app_context():
            user = User(id="user-override", email="override@example.com")
            user.set_password("Pass123!")
            db.session.add(user)

            account = BrokerAccount(
                user_id="user-override",
                platform="MT5",
                server="IFXBrokers-Real",
                account_login="2160203",
                encrypted_password="enc",
                metaapi_account_id="custom-explicit-uuid-777",
                is_connected=True,
            )
            db.session.add(account)
            db.session.commit()

            active_id = get_active_metaapi_account_id("user-override", account)
            assert active_id == "custom-explicit-uuid-777"


class TestZARCurrencyAndFormatting:
    def test_get_currency_symbol(self):
        assert get_currency_symbol("ZAR") == "R"
        assert get_currency_symbol("USD") == "$"
        assert get_currency_symbol("EUR") == "€"
        assert get_currency_symbol("GBP") == "£"
        assert get_currency_symbol("JPY") == "¥"
        assert get_currency_symbol(None) == "$"

    def test_ifx_account_defaults_to_zar(self):
        curr, sym = get_account_currency("IFXBrokers-Real")
        assert curr == "ZAR"
        assert sym == "R"

        curr_deriv, sym_deriv = get_account_currency("Deriv-Server")
        assert curr_deriv == "USD"
        assert sym_deriv == "$"

    def test_metaapi_account_info_reads_zar_currency(self, app, monkeypatch):
        mock_info = {
            "balance": 2908.51,
            "credit": 0.0,
            "equity": 2908.51,
            "margin": 0.0,
            "freeMargin": 2908.51,
            "currency": "ZAR",
        }

        monkeypatch.setenv("METAAPI_TOKEN", "mock-token-123")
        monkeypatch.setattr(
            "flask_dashboard.services.broker_bridge.fetch_metaapi_account_info",
            lambda *args, **kwargs: mock_info,
        )

        with app.app_context():
            user = User(id="zar-trader", email="zar@example.com")
            user.set_password("Pass123!")
            db.session.add(user)

            account = BrokerAccount(
                user_id="zar-trader",
                platform="MT5",
                server="IFXBrokers-Real",
                account_login="2160203",
                encrypted_password="enc",
                metaapi_account_id="bace56c1-5847-4977-9ca6-53818e11a2f6",
                is_connected=True,
            )
            db.session.add(account)
            db.session.commit()

            app.config["TESTING"] = False
            try:
                tele = get_broker_telemetry("zar-trader")
                assert tele["currency"] == "ZAR"
                assert tele["currency_symbol"] == "R"
                assert tele["balance"] == Decimal("2908.51")
                assert tele["equity"] == Decimal("2908.51")
                assert tele["free_margin"] == Decimal("2908.51")

                # Verify database account is updated
                db_acct = BrokerAccount.query.filter_by(user_id="zar-trader").first()
                assert db_acct.currency == "ZAR"
                assert db_acct.balance == Decimal("2908.51")
            finally:
                app.config["TESTING"] = True


class TestIFXSymbolSuffixMapping:
    def test_resolve_and_clean_broker_symbol(self):
        # IFX server appends .ifx
        assert resolve_broker_symbol("USDJPY", "IFXBrokers-Real") == "USDJPY.ifx"
        assert resolve_broker_symbol("EURUSD", "IFXBrokers-Demo") == "EURUSD.ifx"
        assert resolve_broker_symbol("XAUUSD.ifx", "IFXBrokers-Real") == "XAUUSD.ifx"

        # Non-IFX server leaves symbol unchanged
        assert resolve_broker_symbol("USDJPY", "Deriv-Server") == "USDJPY"
        assert resolve_broker_symbol("EURUSD", "") == "EURUSD"

        # Clean symbol removes .ifx
        assert clean_broker_symbol("USDJPY.ifx") == "USDJPY"
        assert clean_broker_symbol("EURUSD") == "EURUSD"

    def test_get_symbol_spec_supports_ifx_suffix(self):
        spec_standard = get_symbol_spec("EURUSD")
        spec_ifx = get_symbol_spec("EURUSD.ifx")

        assert spec_ifx["volume_min"] == spec_standard["volume_min"]
        assert spec_ifx["volume_max"] == spec_standard["volume_max"]
        assert spec_ifx["digits"] == spec_standard["digits"]

    def test_space_trade_worker_prevents_duplicate_ifx_positions(self):
        broker = PaperExecutionBroker(initial_balance=10000.0)
        # Manually add an open position with symbol "EURUSD.ifx"
        broker._positions["pos-1"] = Position(
            ticket="pos-1",
            symbol="EURUSD.ifx",
            trade_type="BUY",
            lot_size=0.01,
            entry_price=1.0850,
            current_price=1.0855,
        )

        worker = SpaceTradeWorker(broker=broker, symbols=["EURUSD", "USDJPY"])
        worker.risk_manager.check_news_blackout = lambda *a, **kw: False

        with patch("trading_state.load_execution_state", return_value=True):
            with patch.object(
                worker,
                "_evaluate_market_signal",
                side_effect=lambda s: {"action": "BUY", "confidence": 85.0},
            ):
                res = worker.run_cycle()
                # EURUSD should be skipped because EURUSD.ifx is already open
                # Only USDJPY should execute
                assert res["status"] == "completed"
                assert res["trades_executed"] == 1
                open_syms = [p.symbol for p in broker.get_positions()]
                assert "EURUSD.ifx" in open_syms
                assert any("USDJPY" in s for s in open_syms)

    def test_live_metaapi_broker_resolves_ifx_symbol(self, app):
        with app.app_context():
            user = User(id="user-ifx-live", email="ifxlive@example.com")
            user.set_password("Pass123!")
            db.session.add(user)

            account = BrokerAccount(
                user_id="user-ifx-live",
                platform="MT5",
                server="IFXBrokers-Real",
                account_login="2160203",
                encrypted_password="enc",
                is_connected=True,
            )
            db.session.add(account)
            db.session.commit()

            broker = LiveMetaApiBroker(user_id="user-ifx-live")
            assert broker.resolve_symbol("USDJPY") == "USDJPY.ifx"
            assert broker.resolve_symbol("EURUSD.ifx") == "EURUSD.ifx"


class TestAPIEndpointsAndSwitching:
    def test_switch_account_api(self, client, app):
        res = client.post(
            "/api/broker/switch-account",
            json={
                "metaapi_account_id": "bace56c1-5847-4977-9ca6-53818e11a2f6",
                "login": "2160203",
                "server": "IFXBrokers-Real",
            },
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        assert data["active_account_id"] == "bace56c1-5847-4977-9ca6-53818e11a2f6"

        with app.app_context():
            acct = BrokerAccount.query.filter_by(user_id="sync-test-user-1").first()
            assert acct.metaapi_account_id == "bace56c1-5847-4977-9ca6-53818e11a2f6"
            assert acct.account_login == "2160203"

    def test_api_broker_accounts_discovery(self, client, monkeypatch):
        monkeypatch.setenv("METAAPI_TOKEN", "mock-token-abc")
        monkeypatch.setattr(
            "flask_dashboard.services.broker_bridge.fetch_metaapi_accounts",
            lambda *args, **kwargs: MOCK_PROVISIONED_ACCOUNTS,
        )

        res = client.get("/api/broker/accounts")
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        assert len(data["accounts"]) == 2
        logins = [a["login"] for a in data["accounts"]]
        assert "2160203" in logins
        assert "1861949" in logins

    def test_stream_telemetry_includes_currency_and_symbol(self, client):
        res = client.get("/api/stream/telemetry")
        assert res.status_code == 200
        assert "text/event-stream" in res.content_type
        # Extract first telemetry event data
        lines = res.data.decode("utf-8").split("\n")
        data_lines = [line[6:] for line in lines if line.startswith("data: ")]
        assert len(data_lines) > 0
        payload = json.loads(data_lines[0])
        assert "currency" in payload
        assert "currency_symbol" in payload
        assert "balance" in payload
        assert "equity" in payload


class TestSpaceTradeWorkerDaemon:
    def test_daemon_thread_lifecycle(self):
        worker = SpaceTradeWorker()
        thread = start_space_trade_worker_daemon(worker=worker, interval_seconds=1)
        assert thread is not None
        assert thread.is_alive()

        # Stop daemon
        stop_space_trade_worker_daemon()
        thread.join(timeout=3.0)
        assert not thread.is_alive()
