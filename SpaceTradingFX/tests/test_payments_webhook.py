"""Webhook verification and idempotency tests use a deterministic Stripe fake."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from flask_dashboard import create_app, payments
from flask_dashboard.extensions import db
from flask_dashboard.models import License, ProcessedStripeEvent, User


@pytest.fixture
def app(monkeypatch):
    event = {
        "id": "evt-paper-paid",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs-paper-paid",
                "payment_status": "paid",
                "metadata": {"user_id": "buyer-1", "license_type": "basic"},
            }
        },
    }

    class Webhook:
        @staticmethod
        def construct_event(payload, signature, secret):
            if payload == b"invalid":
                raise ValueError("invalid JSON")
            if signature != "valid-signature" or secret != "whsec-test":
                raise RuntimeError("bad signature")
            return event

    monkeypatch.setattr(payments, "stripe_lib", SimpleNamespace(StripeClient=lambda key: object(), Webhook=Webhook))
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
            "RATELIMIT_ENABLED": False,
            "STRIPE_SECRET_KEY": "sk-test",
            "STRIPE_WEBHOOK_SECRET": "whsec-test",
        }
    )
    with app.app_context():
        db.create_all()
        db.session.add(User(id="buyer-1", email="buyer@example.com"))
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


def test_verified_webhook_provisions_once_even_when_delivered_twice(app):
    client = app.test_client()
    first = client.post("/payments/webhook", data=b"{}", headers={"Stripe-Signature": "valid-signature"})
    duplicate = client.post("/payments/webhook", data=b"{}", headers={"Stripe-Signature": "valid-signature"})

    assert first.status_code == duplicate.status_code == 200
    with app.app_context():
        assert License.query.filter_by(stripe_payment_id="cs-paper-paid").count() == 1
        assert ProcessedStripeEvent.query.filter_by(stripe_event_id="evt-paper-paid").count() == 1


def test_webhook_rejects_invalid_payload_without_writing(app):
    response = app.test_client().post(
        "/payments/webhook", data=b"invalid", headers={"Stripe-Signature": "valid-signature"}
    )
    assert response.status_code == 400
    with app.app_context():
        assert ProcessedStripeEvent.query.count() == 0
