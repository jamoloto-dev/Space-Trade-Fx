from decimal import Decimal

import pytest
from flask_dashboard import create_app
from flask_dashboard.extensions import db
from flask_dashboard.license_manager import create_user_license
from flask_dashboard.models import TradingPreference, User


@pytest.fixture
def client():
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
            "RATELIMIT_ENABLED": False,
        }
    )
    with app.test_client() as client:
        with app.app_context():
            # create tables
            db.create_all()
        yield client
        # teardown
        with app.app_context():
            db.session.remove()
            db.drop_all()


def login(client, email="test@example.com"):
    with client.application.app_context():
        user = User.query.filter_by(email=email).first()
        if not user:
            user = User(id=f"test-{email}", email=email, first_name="Test")
            user.set_password("a-secure-test-password")
            db.session.add(user)
            db.session.commit()

    return client.post("/login", data={"email": email, "password": "a-secure-test-password"})


def test_preferences_save_direction_preferences(client):
    # Log in (the login route will create the user)
    rv = login(client)
    assert rv.status_code == 302

    with client.application.app_context():
        user = User.query.filter_by(email="test@example.com").first()
        create_user_license(user.id, "basic")

    # Access preferences page
    rv = client.get("/preferences")
    assert rv.status_code == 200

    # Post updated preferences including direction per pair
    data = {
        "currency_pairs": ["EURUSD", "GBPUSD"],
        "timeframe": "1H",
        "risk_percentage": "1.5",
        "max_concurrent_trades": "2",
        "trading_enabled": "on",
        "direction_EURUSD": "BUY",
        "direction_GBPUSD": "SELL",
    }

    rv = client.post("/preferences", data=data)
    assert rv.status_code == 302

    # Verify preferences persisted
    with client.application.app_context():
        user = User.query.filter_by(email="test@example.com").first()
        pref = TradingPreference.query.filter_by(user_id=user.id).first()
        assert pref is not None
        assert set(pref.currency_pairs) == set(["EURUSD", "GBPUSD"])
        assert pref.timeframe == "1H"
        assert pref.risk_percentage == Decimal("1.50")
        assert pref.max_concurrent_trades == 2
        assert pref.trading_enabled is True
        assert pref.direction_preferences.get("EURUSD") == "BUY"
        assert pref.direction_preferences.get("GBPUSD") == "SELL"
