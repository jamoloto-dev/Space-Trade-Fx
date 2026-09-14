"""Deterministic tests for the separately managed paper lifecycle."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from flask_dashboard import create_app
from flask_dashboard.extensions import db
from flask_dashboard.models import PaperOrderEvent, Trade, User
from flask_dashboard.paper_worker import PaperLifecycleWorker
from flask_dashboard.trading_engine import MarketDataUnavailable, PaperTradeValidationError, TradingEngine


class FixedProvider:
    def __init__(self, price: str = "1.10000", signal: str = "BUY", timestamp: str = "2024-01-02T00:00:00Z"):
        self.price, self.signal, self.timestamp = price, signal, timestamp

    def get_forex_intraday(self, *_args):
        return {
            "success": True,
            "data": [{"time": self.timestamp, "close": self.price}],
            "data_mode": "simulation",
            "provider": "test_fixture",
        }

    def analyze_signal(self, symbol, timeframe="1H"):
        return {
            "currency_pair": symbol,
            "timestamp": self.timestamp,
            "signal": self.signal,
            "strength": 70,
            "indicators": {},
        }


@pytest.fixture
def app():
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
            "RATELIMIT_ENABLED": False,
        }
    )
    with app.app_context():
        db.create_all()
        user = User(id="automation-user", email="automation@example.com")
        user.set_password("a-secure-test-password")
        db.session.add(user)
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


def engine(provider: FixedProvider | None = None) -> TradingEngine:
    value = TradingEngine("automation-user")
    value.preferences.trading_enabled = True
    value.preferences.currency_pairs = ["EURUSD"]
    value.preferences.timeframe = "1H"
    value.preferences.strategy_settings = {
        "lot_sizes": {"EURUSD": "0.01"},
        "risk_controls": {"max_lot_size": "0.10", "max_total_lots": "0.10", "max_daily_loss": "50"},
    }
    value.forex_provider = provider or FixedProvider()
    db.session.commit()
    return value


def test_manual_and_automated_modes_are_separate(app):
    with app.app_context():
        value = engine()
        manual = value.execute_trade("EURUSD", "SELL", {"source": "manual"}, idempotency_key="manual-1")
        assert manual.signal_data["submission_mode"] == "manual"
        with pytest.raises(PaperTradeValidationError, match="Automated"):
            value.execute_trade("EURUSD", "BUY", idempotency_key="auto-1", submission_mode="automated")

        # A fresh account/configuration demonstrates automatic signal routing.
        manual.status = "closed"
        value.preferences.strategy_settings = {**value.preferences.strategy_settings, "automated_paper_trading": True}
        db.session.commit()
        assert value.run_automated_cycle() == 1
        assert value.run_automated_cycle() == 0  # same bar/idempotency key
        auto = Trade.query.filter_by(user_id="automation-user", status="open").one()
        assert auto.signal_data["submission_mode"] == "automated"


def test_risk_pause_and_stale_quote_rejections(app):
    with app.app_context():
        value = engine()
        value.preferences.trading_enabled = False
        db.session.commit()
        with pytest.raises(PaperTradeValidationError, match="paused"):
            value.execute_trade("EURUSD", "BUY")

        value.preferences.trading_enabled = True
        value.forex_provider = FixedProvider(timestamp="")
        db.session.commit()
        with pytest.raises(MarketDataUnavailable, match="timestamp"):
            value.execute_trade("EURUSD", "BUY")

        value.forex_provider = FixedProvider()
        value.preferences.strategy_settings = {
            **value.preferences.strategy_settings,
            "risk_controls": {**value.preferences.strategy_settings["risk_controls"], "max_lot_size": "0.005"},
        }
        db.session.commit()
        with pytest.raises(PaperTradeValidationError, match="lot size"):
            value.execute_trade("EURUSD", "BUY")

        value.preferences.strategy_settings = {
            **value.preferences.strategy_settings,
            "risk_controls": {
                **value.preferences.strategy_settings["risk_controls"],
                "max_lot_size": "0.10",
                "account_equity": "1.00",
            },
        }
        db.session.commit()
        with pytest.raises(PaperTradeValidationError, match="stop-loss exposure"):
            value.execute_trade("EURUSD", "BUY")

        class StaleExternalProvider(FixedProvider):
            def get_forex_intraday(self, *_args):
                return {
                    "success": True,
                    "data": [{"time": "2024-01-02T00:00:00Z", "close": "1.10000"}],
                    "data_mode": "external",
                    "provider": "test_external",
                }

        value.preferences.strategy_settings = {
            **value.preferences.strategy_settings,
            "risk_controls": {**value.preferences.strategy_settings["risk_controls"], "max_lot_size": "0.10"},
        }
        value.forex_provider = StaleExternalProvider()
        with pytest.raises(MarketDataUnavailable, match="stale"):
            value.execute_trade("EURUSD", "BUY")


def test_close_claim_is_idempotent_and_restart_recovery_closes(app):
    with app.app_context():
        value = engine()
        trade = value.execute_trade("EURUSD", "BUY", idempotency_key="close-1")
        # A new engine represents recovery after a worker restart.
        recovered = TradingEngine("automation-user")
        recovered.forex_provider = FixedProvider(price="1.10400")
        assert recovered.update_open_trades() == 1
        assert recovered.update_open_trades() == 0
        assert trade.status == "closed"
        assert [
            event.event_type
            for event in PaperOrderEvent.query.filter_by(trade_id=trade.id).order_by(PaperOrderEvent.sequence)
        ] == ["intent_recorded", "risk_validated", "opened", "close_requested", "closed"]
        assert recovered.reconcile_paper_ledger().exception_count == 0


def test_worker_lease_prevents_duplicate_processing(app):
    with app.app_context():
        first, second = PaperLifecycleWorker(owner_id="one"), PaperLifecycleWorker(owner_id="two")
        assert first.acquire_lease() is True
        assert second.acquire_lease() is False
        first.release_lease()
        assert second.acquire_lease() is True


def test_worker_runs_deterministic_automation_once(app, monkeypatch):
    with app.app_context():
        value = engine()
        value.preferences.strategy_settings = {**value.preferences.strategy_settings, "automated_paper_trading": True}
        db.session.commit()

        def configured_engine(_user_id):
            rebuilt = TradingEngine("automation-user")
            rebuilt.forex_provider = FixedProvider()
            return rebuilt

        monkeypatch.setattr("flask_dashboard.paper_worker.TradingEngine", configured_engine)
        result = PaperLifecycleWorker(owner_id="cycle").run_once()
        assert result["status"] == "ok"
        assert result["opened"] == 1
        assert Trade.query.filter_by(status="open").count() == 1
        health = app.test_client().get("/health/paper-worker")
        assert health.status_code == 200
        assert health.get_json()["status"] == "running"
        assert health.get_json()["last_success_at"]


def test_pausing_new_orders_keeps_existing_positions_managed(app, monkeypatch):
    with app.app_context():
        value = engine()
        trade = value.execute_trade("EURUSD", "BUY", idempotency_key="paused-open")
        value.preferences.trading_enabled = False
        db.session.commit()

        def recovered_engine(_user_id):
            rebuilt = TradingEngine("automation-user")
            rebuilt.forex_provider = FixedProvider(price="1.10400")
            return rebuilt

        monkeypatch.setattr("flask_dashboard.paper_worker.TradingEngine", recovered_engine)
        result = PaperLifecycleWorker(owner_id="paused-cycle").run_once()
        assert result["closed"] == 1
        assert db.session.get(Trade, trade.id).status == "closed"


def test_concurrent_duplicate_submission_returns_the_one_persisted_trade(tmp_path):
    database_path = tmp_path / "concurrent-paper.db"
    concurrent_app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
            "WTF_CSRF_ENABLED": False,
            "RATELIMIT_ENABLED": False,
        }
    )
    barrier = Barrier(2)

    class ConcurrentProvider(FixedProvider):
        def get_forex_intraday(self, *_args):
            barrier.wait(timeout=5)
            return super().get_forex_intraday()

    with concurrent_app.app_context():
        db.create_all()
        db.session.add(User(id="concurrent-user", email="concurrent@example.com"))
        db.session.commit()
        configured = TradingEngine("concurrent-user")
        configured.preferences.trading_enabled = True
        db.session.commit()

    def submit() -> int:
        with concurrent_app.app_context():
            value = TradingEngine("concurrent-user")
            value.forex_provider = ConcurrentProvider()
            return value.execute_trade("EURUSD", "BUY", idempotency_key="same-request").id

    with ThreadPoolExecutor(max_workers=2) as executor:
        trade_ids = list(executor.map(lambda _unused: submit(), range(2)))

    with concurrent_app.app_context():
        assert trade_ids[0] == trade_ids[1]
        assert Trade.query.filter_by(user_id="concurrent-user", idempotency_key="same-request").count() == 1
        db.session.remove()
        db.drop_all()
