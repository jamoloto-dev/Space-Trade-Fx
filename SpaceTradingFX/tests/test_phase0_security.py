from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from flask_dashboard import create_app
from flask_dashboard.extensions import db
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
