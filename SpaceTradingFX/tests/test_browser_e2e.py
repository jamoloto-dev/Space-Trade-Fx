"""Browser-level End-to-End (E2E) test suite for SpaceTradingFX web interface."""

import pytest
from flask_dashboard import create_app
from flask_dashboard.extensions import db
from flask_dashboard.license_manager import create_user_license
from flask_dashboard.models import TradingPreference, User
from flask_dashboard.notifications import create_notification


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
        db.drop_all()
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def test_browser_e2e_full_journey(client, app):
    # 1. Landing Page Visit
    landing_res = client.get("/")
    assert landing_res.status_code == 200
    assert b"SpaceTradingFX" in landing_res.data

    # 2. Register & Login
    with app.app_context():
        user = User(id="browser-e2e-user", email="e2e_user@example.com", first_name="E2E", last_name="Tester")
        user.set_password("SecurePassword123!")
        db.session.add(user)
        db.session.commit()
        create_user_license(user.id, "premium")

    login_res = client.post(
        "/login",
        data={
            "email": "e2e_user@example.com",
            "password": "SecurePassword123!",
        },
        follow_redirects=True,
    )
    assert login_res.status_code == 200
    assert b"Dashboard" in login_res.data or b"SpaceTradingFX" in login_res.data

    # 3. Preferences Configuration via Web Form
    pref_page = client.get("/preferences")
    assert pref_page.status_code == 200

    pref_post = client.post(
        "/preferences",
        data={
            "currency_pairs": ["EURUSD", "GBPUSD"],
            "timeframe": "1H",
            "risk_percentage": "1.5",
            "max_concurrent_trades": "5",
            "trading_enabled": "on",
            "direction_EURUSD": "BUY",
            "direction_GBPUSD": "BOTH",
        },
        follow_redirects=True,
    )
    assert pref_post.status_code == 200

    with app.app_context():
        pref = TradingPreference.query.filter_by(user_id="browser-e2e-user").first()
        assert pref is not None
        assert "EURUSD" in pref.currency_pairs
        assert pref.direction_preferences.get("EURUSD") == "BUY"

    # 4. In-App Notifications Browser Flow
    with app.app_context():
        create_notification(
            user_id="browser-e2e-user",
            title="E2E Alert",
            message="System is healthy and paper trading is active",
            notification_type="system",
        )

    count_res = client.get("/api/notifications/count")
    assert count_res.status_code == 200
    assert count_res.get_json()["count"] >= 1

    # 5. Mobile Web Experience
    m_home = client.get("/m/home")
    assert m_home.status_code == 200
    assert b"Quotes" in m_home.data or b"Home" in m_home.data

    m_quotes = client.get("/m/quotes")
    assert m_quotes.status_code == 200

    m_quotes_post = client.post(
        "/m/quotes",
        data={
            "enabled_pairs": ["EURUSD"],
            "direction_EURUSD": "BUY",
            "lot_EURUSD": "0.02",
            "trading_enabled": "on",
        },
        follow_redirects=True,
    )
    assert m_quotes_post.status_code == 200

    m_history = client.get("/m/history")
    assert m_history.status_code == 200

    m_profile = client.get("/m/profile")
    assert m_profile.status_code == 200

    # 6. Session Logout
    logout_res = client.get("/logout", follow_redirects=True)
    assert logout_res.status_code == 200

    # Accessing protected page after logout redirects to login
    protected_res = client.get("/preferences")
    assert protected_res.status_code in {302, 401}
