import sys
from pathlib import Path
import json
import pytest

# Ensure SpaceTradingFX path importable
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "SpaceTradingFX"))

from flask_dashboard.app import app, db  # noqa: E402
from flask_dashboard.license_manager import create_user_license  # noqa: E402
from flask_dashboard.models import User, License  # noqa: E402

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        with app.app_context():
            db.drop_all()
            db.create_all()
        yield client
        with app.app_context():
            db.session.remove()
            db.drop_all()


def login(client, email='activation_tester@example.com'):
    return client.post('/login', data={'email': email}, follow_redirects=True)


def test_license_activation_and_status_flow(client):
    # Login creates user
    rv = login(client)
    assert rv.status_code == 200

    with app.app_context():
        user = User.query.filter_by(email='activation_tester@example.com').first()
        assert user is not None
        # Create license
        lic = create_user_license(user.id, 'basic')
        license_key = lic.license_key

    # Activate license
    payload = {
        'license_key': license_key,
        'account_number': '123456',
        'server': 'Demo-Server',
        'machine_fingerprint': 'fp-abc'
    }
    rv = client.post('/api/license/activate', json=payload)
    assert rv.status_code == 200
    data = rv.get_json()
    assert data['ok'] is True
    assert data['created'] is True

    # Second activation with same account should not create new record
    rv2 = client.post('/api/license/activate', json=payload)
    assert rv2.status_code == 200
    data2 = rv2.get_json()
    assert data2['ok'] is True
    assert data2['created'] is False

    # Status endpoint
    rv3 = client.get(f'/api/license/status?license_key={license_key}')
    assert rv3.status_code == 200
    status_data = rv3.get_json()
    assert status_data['ok'] is True
    assert len(status_data['activations']) == 1
    assert status_data['activations'][0]['account_number'] == '123456'


def test_revoke_endpoint(client):
    # Login & create user
    rv = login(client)
    assert rv.status_code == 200
    with app.app_context():
        user = User.query.filter_by(email='activation_tester@example.com').first()
        # ensure user is admin for revoke test
        user.is_admin = True
        db.session.commit()
        lic = create_user_license(user.id, 'basic')
        license_key = lic.license_key

    # Revoke license
    rv = client.post('/api/license/revoke', json={'license_key': license_key})
    assert rv.status_code == 200
    data = rv.get_json()
    assert data['ok'] is True
    assert data['status'] == 'revoked'

    # Status should reflect revoked
    rv2 = client.get(f'/api/license/status?license_key={license_key}')
    # status may still show ok:true but with status revoked; validate
    status_data = rv2.get_json()
    assert status_data.get('status') == 'revoked'
