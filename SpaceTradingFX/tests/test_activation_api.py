import pytest
from flask_dashboard import create_app
from flask_dashboard.extensions import db
from flask_dashboard.license_manager import create_user_license
from flask_dashboard.models import User


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
            db.drop_all()
            db.create_all()
        yield client
        with app.app_context():
            db.session.remove()
            db.drop_all()


def login(client, email="activation_tester@example.com"):
    with client.application.app_context():
        user = User.query.filter_by(email=email).first()
        if not user:
            user = User(id=f"test-{email}", email=email, first_name="Test")
            user.set_password("a-secure-test-password")
            db.session.add(user)
            db.session.commit()
    return client.post("/login", data={"email": email, "password": "a-secure-test-password"})


def test_license_activation_and_status_flow(client):
    # Login creates user
    rv = login(client)
    assert rv.status_code == 302

    with client.application.app_context():
        user = User.query.filter_by(email="activation_tester@example.com").first()
        assert user is not None
        # Create license
        lic = create_user_license(user.id, "basic")
        license_key = lic.license_key

    # Activate license
    payload = {
        "license_key": license_key,
        "account_number": "123456",
        "server": "Real-Server",
        "machine_fingerprint": "fp-abc",
    }
    rv = client.post("/api/license/activate", json=payload)
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["ok"] is True
    assert data["created"] is True

    # Second activation with same account should not create new record
    rv2 = client.post("/api/license/activate", json=payload)
    assert rv2.status_code == 200
    data2 = rv2.get_json()
    assert data2["ok"] is True
    assert data2["created"] is False

    # Status endpoint
    rv3 = client.get(f"/api/license/status?license_key={license_key}")
    assert rv3.status_code == 200
    status_data = rv3.get_json()
    assert status_data["ok"] is True
    assert len(status_data["activations"]) == 1
    assert status_data["activations"][0]["account_number"] == "123456"


def test_revoke_endpoint(client):
    # Login & create user
    rv = login(client)
    assert rv.status_code == 302
    with client.application.app_context():
        user = User.query.filter_by(email="activation_tester@example.com").first()
        # ensure user is admin for revoke test
        user.is_admin = True
        db.session.commit()
        lic = create_user_license(user.id, "basic")
        license_key = lic.license_key

    # Revoke license
    rv = client.post("/api/license/revoke", json={"license_key": license_key})
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["ok"] is True
    assert data["status"] == "revoked"

    # Status should reflect revoked
    rv2 = client.get(f"/api/license/status?license_key={license_key}")
    # status may still show ok:true but with status revoked; validate
    status_data = rv2.get_json()
    assert status_data["ok"] is False
    assert status_data["error"] == "License is revoked"


def test_license_status_authorization_enforcement(client):
    # Create owner and license
    login(client, email="owner@example.com")
    with client.application.app_context():
        owner = User.query.filter_by(email="owner@example.com").first()
        lic = create_user_license(owner.id, "basic")
        license_key = lic.license_key

    # Owner can view status
    rv = client.get(f"/api/license/status?license_key={license_key}")
    assert rv.status_code == 200
    assert rv.get_json()["ok"] is True

    # Another non-admin user cannot view status -> 403
    login(client, email="other@example.com")
    rv_other = client.get(f"/api/license/status?license_key={license_key}")
    assert rv_other.status_code == 403
    assert rv_other.get_json()["error"] == "forbidden"

    # Admin can view status -> 200
    with client.application.app_context():
        admin = User(id="test-admin", email="admin@example.com", first_name="Admin", is_admin=True)
        admin.set_password("a-secure-test-password")
        db.session.add(admin)
        db.session.commit()
    login(client, email="admin@example.com")
    rv_admin = client.get(f"/api/license/status?license_key={license_key}")
    assert rv_admin.status_code == 200
    assert rv_admin.get_json()["ok"] is True

    # Non-existent license -> 404
    rv_404 = client.get("/api/license/status?license_key=NONEXISTENT")
    assert rv_404.status_code == 404

    # Missing license parameter -> 400
    rv_400 = client.get("/api/license/status")
    assert rv_400.status_code == 400
