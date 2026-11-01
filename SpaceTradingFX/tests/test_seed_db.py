"""Unit tests for automatic database startup seeder."""

import pytest
from flask_dashboard import create_app
from flask_dashboard.extensions import db
from flask_dashboard.models import BrokerAccount, License, TradingPreference, User
from flask_dashboard.seed_db import seed_database


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def test_seed_database_creates_user_and_licenses(app, monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", "testadmin@spacetradingfx.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "TestPass12345%!")
    monkeypatch.setenv("ADMIN_LICENSE_KEY", "TEST-LIC1-KEY1")
    monkeypatch.setenv("ADMIN_SECONDARY_LICENSE_KEY", "TEST-LIC2-KEY2")
    monkeypatch.setenv("MT5_ACCOUNT_LOGIN", "999888")
    monkeypatch.setenv("MT5_SERVER", "TestServer-Live")
    monkeypatch.setenv("MT5_PASSWORD", "secret123")

    with app.app_context():
        seed_database(app=app)

        user = User.query.filter_by(email="testadmin@spacetradingfx.com").first()
        assert user is not None
        assert user.is_admin is True
        assert user.has_unlimited_premium is True
        assert user.check_password("TestPass12345%!") is True

        lic1 = License.query.filter_by(license_key="TEST-LIC1-KEY1").first()
        assert lic1 is not None
        assert lic1.user_id == user.id
        assert lic1.license_type == "professional"
        assert lic1.status == "active"

        lic2 = License.query.filter_by(license_key="TEST-LIC2-KEY2").first()
        assert lic2 is not None
        assert lic2.user_id == user.id
        assert lic2.status == "active"

        broker = BrokerAccount.query.filter_by(user_id=user.id).first()
        assert broker is not None
        assert broker.account_login == "999888"
        assert broker.server == "TestServer-Live"
        assert broker.is_connected is True

        prefs = TradingPreference.query.filter_by(user_id=user.id).first()
        assert prefs is not None
        assert "EURUSD" in prefs.currency_pairs


def test_seed_database_is_idempotent(app, monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", "idempotent@spacetradingfx.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "InitialPass123!")
    monkeypatch.setenv("ADMIN_LICENSE_KEY", "IDEM-LIC1-KEY1")

    with app.app_context():
        seed_database(app=app)
        user1 = User.query.filter_by(email="idempotent@spacetradingfx.com").first()
        user1_id = user1.id

        # Change password and run again
        monkeypatch.setenv("ADMIN_PASSWORD", "UpdatedPass456!")
        seed_database(app=app)
        db.session.expire_all()

        user2 = User.query.filter_by(email="idempotent@spacetradingfx.com").first()
        assert user2.id == user1_id
        assert user2.check_password("UpdatedPass456!") is True
        assert user2.check_password("InitialPass123!") is False

        # Licenses should still exist and not duplicate
        licenses = License.query.filter_by(user_id=user2.id).all()
        assert len([lic for lic in licenses if lic.license_key == "IDEM-LIC1-KEY1"]) == 1
