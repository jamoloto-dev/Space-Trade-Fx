"""
Mentor/Referral System for SpaceTradingFX
Handles mentor registration, referral tracking, and commissions
"""
import os
import random
import string
from datetime import datetime
import logging

from app import db
from models import User, License, Referral
from notifications import notify_new_referral, notify_commission_earned

logger = logging.getLogger(__name__)

# Commission rate (percentage of license price)
COMMISSION_RATE = float(os.environ.get('MENTOR_COMMISSION_RATE', '0.10'))  # 10% default

# License prices for commission calculation
LICENSE_PRICES = {
    'basic': 29.99,
    'premium': 99.99,
    'professional': 199.99
}


def generate_mentor_id() -> str:
    """Generate a unique 3-digit mentor ID"""
    while True:
        mentor_id = ''.join(random.choices(string.digits, k=3))
        # Ensure it doesn't exist already
        existing = User.query.filter_by(mentor_id=mentor_id).first()
        if not existing:
            return mentor_id


def register_as_mentor(user_id: str) -> str:
    """Register a user as a mentor and generate their mentor ID"""
    user = User.query.get(user_id)
    if not user:
        raise ValueError("User not found")
    
    if user.mentor_id:
        return user.mentor_id  # Already a mentor
    
    mentor_id = generate_mentor_id()
    user.mentor_id = mentor_id
    user.is_mentor = True
    db.session.commit()
    
    logger.info(f"User {user_id} registered as mentor with ID {mentor_id}")
    return mentor_id


def get_mentor_by_id(mentor_id: str) -> "User | None":
    """Get mentor user by their mentor ID"""
    return User.query.filter_by(mentor_id=mentor_id, is_mentor=True).first()


def track_referral(referred_user_id: str, mentor_id: str) -> bool:
    """Track a referral when a user signs up with a mentor ID"""
    mentor = get_mentor_by_id(mentor_id)
    if not mentor:
        logger.warning(f"Mentor ID {mentor_id} not found")
        return False
    
    referred_user = User.query.get(referred_user_id)
    if not referred_user:
        return False
    
    # Store the mentor ID on the referred user
    referred_user.referred_by_mentor_id = mentor_id
    
    # Increment mentor's referral count
    mentor.total_referrals = (mentor.total_referrals or 0) + 1
    
    db.session.commit()
    
    # Notify mentor
    notify_new_referral(mentor.id, referred_user.email or 'New User')
    
    logger.info(f"Referral tracked: {referred_user_id} referred by mentor {mentor_id}")
    return True


def process_referral_commission(license_obj: License) -> float:
    """Process commission for a license purchase if there's a referral"""
    user = User.query.get(license_obj.user_id)
    if not user or not user.referred_by_mentor_id:
        return 0.0
    
    mentor = get_mentor_by_id(user.referred_by_mentor_id)
    if not mentor:
        return 0.0
    
    # Calculate commission
    license_price = LICENSE_PRICES.get(license_obj.license_type, 29.99)
    commission = license_price * COMMISSION_RATE
    
    # Create referral record (SQLAlchemy models accept column names as kwargs)
    referral = Referral()  # type: ignore
    referral.mentor_id = mentor.mentor_id
    referral.referred_user_id = user.id
    referral.license_id = license_obj.id
    referral.commission_amount = commission
    referral.commission_paid = False
    referral.created_at = datetime.now()
    db.session.add(referral)
    
    # Update mentor's total commission
    mentor.total_commission = (mentor.total_commission or 0) + commission
    
    db.session.commit()
    
    # Notify mentor
    notify_commission_earned(mentor.id, commission, user.email or 'User')
    
    logger.info(f"Commission of ${commission:.2f} processed for mentor {mentor.mentor_id}")
    return commission


def get_mentor_stats(user_id: str) -> "dict | None":
    """Get statistics for a mentor"""
    user = User.query.get(user_id)
    if not user or not user.is_mentor:
        return None
    
    referrals = Referral.query.filter_by(mentor_id=user.mentor_id).all()
    
    total_referrals = user.total_referrals or 0
    total_commission = user.total_commission or 0
    paid_commission = sum(r.commission_amount for r in referrals if r.commission_paid)
    pending_commission = total_commission - paid_commission
    
    # Get referred users
    referred_users = User.query.filter_by(referred_by_mentor_id=user.mentor_id).all()
    
    return {
        'mentor_id': user.mentor_id,
        'total_referrals': total_referrals,
        'total_commission': total_commission,
        'paid_commission': paid_commission,
        'pending_commission': pending_commission,
        'commission_rate': COMMISSION_RATE * 100,
        'referred_users': [{
            'email': u.email,
            'created_at': u.created_at.isoformat() if u.created_at else None
        } for u in referred_users]
    }


def get_pending_commissions(mentor_id: str) -> list:
    """Get list of pending commissions for a mentor"""
    return Referral.query.filter_by(
        mentor_id=mentor_id, 
        commission_paid=False
    ).all()


def mark_commission_paid(referral_id: int) -> bool:
    """Mark a commission as paid"""
    referral = Referral.query.get(referral_id)
    if referral:
        referral.commission_paid = True
        referral.paid_at = datetime.now()
        db.session.commit()
        return True
    return False
