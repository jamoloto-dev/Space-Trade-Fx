from __future__ import annotations

from decimal import Decimal

import pytest
from flask_dashboard import create_app
from flask_dashboard.extensions import db
from flask_dashboard.models import BrokerAccount, PaperOrderEvent, Trade, User
from flask_dashboard.services.broker_bridge import encrypt_broker_password
from flask_dashboard.trading_engine import PaperTradeValidationError, TradingEngine


class DeterministicMarketData:
    def get_forex_intraday(self, *_args):
        return {
            "success": True,
            "data": [{"time": "2024-01-02T00:00:00Z", "close": "1.10000"}],
            "data_mode": "simulation",
            "provider": "test_fixture",
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
        db.session.add(User(id="ledger-user", email="ledger@example.com"))
        db.session.add(
            BrokerAccount(
                user_id="ledger-user",
                server="IFXBrokers-Demo",
                platform="MT5",
                account_login="10001",
                encrypted_password=encrypt_broker_password("dummy-password"),
                is_connected=True,
            )
        )
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


def _engine() -> TradingEngine:
    engine = TradingEngine("ledger-user")
    engine.preferences.trading_enabled = True
    engine.forex_provider = DeterministicMarketData()
    db.session.commit()
    return engine


def test_paper_order_has_immutable_lifecycle_and_idempotency(app):
    with app.app_context():
        engine = _engine()
        trade = engine.execute_trade("EURUSD", "BUY", {"source": "test"}, idempotency_key="order-key-1")
        duplicate = engine.execute_trade("EURUSD", "BUY", {"source": "test"}, idempotency_key="order-key-1")

        assert duplicate.id == trade.id
        assert trade.execution_mode == "broker"
        assert trade.status == "open"
        assert [
            event.event_type
            for event in PaperOrderEvent.query.filter_by(trade_id=trade.id).order_by(PaperOrderEvent.sequence)
        ] == ["intent_recorded", "risk_validated", "opened"]

        run = engine.reconcile_paper_ledger()
        assert run.checked_count == 1
        assert run.exception_count == 0
        assert db.session.get(Trade, trade.id).reconciliation_state == "reconciled"

        engine._close_trade(trade, Decimal("1.10200"))
        engine.reconcile_paper_ledger()
        assert trade.status == "closed"
        assert trade.profit_loss == Decimal("2.00")


def test_paper_kill_switch_rejects_new_orders(app):
    with app.app_context():
        app.config["PAPER_TRADING_KILL_SWITCH"] = True
        with pytest.raises(PaperTradeValidationError, match="kill switch"):
            _engine().execute_trade("EURUSD", "BUY")
