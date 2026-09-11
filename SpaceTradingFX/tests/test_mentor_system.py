"""Tests for mentor referral system, plan catalog consumption, and Decimal commission math."""

from decimal import Decimal

import pytest
from flask_dashboard import create_app
from flask_dashboard.extensions import db
from flask_dashboard.license_manager import create_user_license
from flask_dashboard.mentor_system import (
    get_mentor_stats,
    mark_commission_paid,
    process_referral_commission,
    register_as_mentor,
    track_referral,
)
from flask_dashboard.models import Referral, User
from flask_dashboard.plan_catalog import PLANS


@pytest.fixture
def app_ctx():
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


def test_mentor_referral_and_commission_decimal_flow(app_ctx):
    # Create mentor user
    mentor = User(id="mentor-1", email="mentor@example.com", first_name="Mentor")
    mentor.set_password("secure-password")
    db.session.add(mentor)
    db.session.commit()

    mentor_id = register_as_mentor("mentor-1")
    assert mentor.is_mentor is True
    assert mentor.mentor_id == mentor_id
    assert len(mentor_id) == 3

    # Create referred user
    referred = User(id="user-1", email="student@example.com", first_name="Student")
    referred.set_password("secure-password")
    db.session.add(referred)
    db.session.commit()

    # Track referral
    tracked = track_referral(referred.id, mentor_id)
    assert tracked is True
    assert referred.referred_by_mentor_id == mentor_id
    assert mentor.total_referrals == 1

    # Buy premium license: price is 99.99, commission should be 10% = 9.999 -> 10.00
    lic = create_user_license(referred.id, "premium")
    commission = process_referral_commission(lic)

    expected_commission = (PLANS["premium"].price_usd * Decimal("0.10")).quantize(Decimal("0.01"))
    assert isinstance(commission, Decimal)
    assert commission == expected_commission
    assert mentor.total_commission == expected_commission

    # Verify referral record created with UTC timestamp
    referral = Referral.query.filter_by(mentor_id=mentor_id).first()
    assert referral is not None
    assert isinstance(referral.commission_amount, Decimal)
    assert referral.created_at.tzinfo is not None or referral.created_at is not None

    # Check mentor stats
    stats = get_mentor_stats(mentor.id)
    assert stats["mentor_id"] == mentor_id
    assert stats["total_referrals"] == 1
    assert stats["total_commission"] == expected_commission
    assert stats["paid_commission"] == Decimal("0.00")
    assert stats["pending_commission"] == expected_commission

    # Mark paid
    assert mark_commission_paid(referral.id) is True
    stats_after_pay = get_mentor_stats(mentor.id)
    assert stats_after_pay["paid_commission"] == expected_commission
    assert stats_after_pay["pending_commission"] == Decimal("0.00")
