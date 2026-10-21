from __future__ import annotations

import pytest
from flask_dashboard import create_app
from flask_dashboard.extensions import db
from flask_dashboard.license_manager import create_user_license
from flask_dashboard.models import User


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
        yield app
        db.session.remove()
        db.drop_all()


def test_factory_registers_expected_routes_once(app):
    rules = [rule.rule for rule in app.url_map.iter_rules()]
    assert rules.count("/payments/webhook") == 1
    assert "/api/license/activate" in rules
    assert "/admin/ui" in rules
    assert "/health/live" in rules
    assert "/health/ready" in rules


def test_startup_creates_no_user_or_administrator(app):
    with app.app_context():
        assert User.query.count() == 0


def test_passwordless_login_is_rejected_and_password_login_succeeds(app):
    client = app.test_client()
    with app.app_context():
        user = User(id="user-1", email="member@example.com", first_name="Member")
        user.set_password("a-secure-test-password")
        db.session.add(user)
        db.session.commit()

    rejected = client.post("/login", data={"email": "member@example.com"})
    assert rejected.status_code == 200
    assert b"Invalid email or password" in rejected.data

    accepted = client.post(
        "/login",
        data={"email": "member@example.com", "password": "a-secure-test-password"},
    )
    assert accepted.status_code == 302


def test_admin_ui_requires_administrator(app):
    client = app.test_client()
    assert client.get("/admin/ui").status_code in {302, 401}

    with app.app_context():
        admin = User(id="admin-1", email="admin@example.com", is_admin=True)
        admin.set_password("a-secure-test-password")
        db.session.add(admin)
        db.session.commit()

    client.post("/login", data={"email": "admin@example.com", "password": "a-secure-test-password"})
    assert client.get("/admin/ui").status_code == 200


def test_all_mt5_http_operations_fail_closed_without_connected_broker(app):
    client = app.test_client()
    with app.app_context():
        user = User(id="broker-test-user", email="brokeruser@example.com")
        user.set_password("a-secure-test-password")
        db.session.add(user)
        db.session.commit()
        create_user_license(user.id, "basic")

    client.post("/login", data={"email": "brokeruser@example.com", "password": "a-secure-test-password"})
    for method, path in (
        (client.post, "/api/mt5/connect"),
        (client.get, "/api/mt5/positions"),
        (client.post, "/api/mt5/trade"),
    ):
        response = method(path)
        assert response.status_code == 400
        assert response.get_json()["success"] is False


def test_quarantined_mt5_connector_cannot_connect_or_submit_orders():
    from flask_dashboard.mt5_connector import LiveBrokerDisabledError, get_mt5_connector

    connector = get_mt5_connector()
    with pytest.raises(LiveBrokerDisabledError):
        connector.connect()
    with pytest.raises(LiveBrokerDisabledError):
        connector.open_position("EURUSD", "BUY", 0.01)


def test_notifications_test_endpoint_restricted(app):
    client = app.test_client()
    with app.app_context():
        user = User(id="regular-user", email="regular@example.com")
        user.set_password("a-secure-test-password")
        admin = User(id="admin-user", email="admin2@example.com", is_admin=True)
        admin.set_password("a-secure-test-password")
        db.session.add_all([user, admin])
        db.session.commit()

    # Unauthenticated -> redirected / 401
    assert client.post("/api/notifications/test").status_code in {302, 401}

    # When not in DEBUG or TESTING (e.g. production simulation), non-admin is forbidden (403)
    app.config["TESTING"] = False
    app.config["DEBUG"] = False
    try:
        client.post("/login", data={"email": "regular@example.com", "password": "a-secure-test-password"})
        rv_forbidden = client.post("/api/notifications/test")
        assert rv_forbidden.status_code == 403
        assert rv_forbidden.get_json()["error"] == "forbidden"

        # Admin can call test notification
        client.post("/login", data={"email": "admin2@example.com", "password": "a-secure-test-password"})
        rv_admin = client.post("/api/notifications/test")
        assert rv_admin.status_code == 200
        assert rv_admin.get_json()["success"] is True
    finally:
        app.config["TESTING"] = True


def test_user_loader_graceful_handling(app):
    from unittest.mock import patch

    from flask_dashboard.extensions import login_manager

    with app.app_context():
        user = User(id="user-loader-1", email="loader@example.com")
        db.session.add(user)
        db.session.commit()

        loader = login_manager._user_callback
        assert loader is not None

        # Existing user returns instance
        loaded = loader("user-loader-1")
        assert loaded is not None
        assert loaded.email == "loader@example.com"

        # None or empty user_id returns None safely
        assert loader(None) is None
        assert loader("") is None

        # Non-existent user returns None safely
        assert loader("non-existent-user-id") is None

        # Database/conversion exceptions caught, logged, and return None safely
        with patch.object(db.session, "get", side_effect=RuntimeError("Simulated DB connection error")):
            assert loader("user-loader-1") is None

