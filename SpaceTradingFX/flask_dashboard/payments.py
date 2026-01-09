"""
Complete Stripe Payment Flow for SpaceTradingFX
Handles checkout sessions, webhooks, and license creation
"""
import os
import secrets
import string
from datetime import datetime, timedelta
from typing import Optional, Any
from flask import Blueprint, request, jsonify, current_app, url_for, redirect
from flask_login import current_user, login_required

# Stripe import with type annotation
stripe: Any = None  # type: ignore
STRIPE_AVAILABLE = False
try:
    import stripe as stripe_lib  # type: ignore
    stripe = stripe_lib
    STRIPE_AVAILABLE = True
except ImportError:
    pass

from app import db, app
from models import License, User

bp = Blueprint('payments', __name__, url_prefix='/payments')

# Stripe configuration
if STRIPE_AVAILABLE and stripe is not None:
    stripe.api_key = os.environ.get('STRIPE_SECRET_KEY', '')

STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY', '')
STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', '')

# License pricing configuration
LICENSE_PRICES = {
    'basic': {
        'price': 29.99,
        'duration_days': 30,
        'max_trades': 10,
        'stripe_price_id': os.environ.get('STRIPE_PRICE_BASIC', ''),
        'features': ['basic_signals', 'manual_trading']
    },
    'premium': {
        'price': 99.99,
        'duration_days': 30,
        'max_trades': 25,
        'stripe_price_id': os.environ.get('STRIPE_PRICE_PREMIUM', ''),
        'features': ['advanced_signals', 'auto_trading', 'email_alerts']
    },
    'professional': {
        'price': 199.99,
        'duration_days': 30,
        'max_trades': 50,
        'stripe_price_id': os.environ.get('STRIPE_PRICE_PROFESSIONAL', ''),
        'features': ['advanced_signals', 'auto_trading', 'email_alerts', 'priority_support', 'custom_strategies']
    }
}


def generate_license_key():
    """Generate a short license key in format XXXX-XXXX-XXXX"""
    chars = string.ascii_uppercase + string.digits
    part1 = ''.join(secrets.choice(chars) for _ in range(4))
    part2 = ''.join(secrets.choice(chars) for _ in range(4))
    part3 = ''.join(secrets.choice(chars) for _ in range(4))
    return f"{part1}-{part2}-{part3}"


@bp.route('/config')
def get_config():
    """Get Stripe publishable key and pricing"""
    return jsonify({
        'publishable_key': STRIPE_PUBLISHABLE_KEY,
        'prices': {
            license_type: {
                'price': info['price'],
                'duration_days': info['duration_days'],
                'max_trades': info['max_trades'],
                'features': info['features']
            }
            for license_type, info in LICENSE_PRICES.items()
        }
    })


@bp.route('/create-checkout-session', methods=['POST'])
@login_required
def create_checkout_session():
    """Create Stripe checkout session for license purchase"""
    if not STRIPE_AVAILABLE or not stripe or not stripe.api_key:
        return jsonify({'error': 'Payment system not configured'}), 503
    
    data = request.get_json() or request.form
    license_type = data.get('license_type', 'basic')
    
    if license_type not in LICENSE_PRICES:
        return jsonify({'error': 'Invalid license type'}), 400
    
    license_info = LICENSE_PRICES[license_type]
    price_id = license_info.get('stripe_price_id')
    
    # Get URLs
    base_url = request.url_root.rstrip('/')
    success_url = data.get('success_url') or f"{base_url}/payments/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = data.get('cancel_url') or f"{base_url}/payments/cancel"
    
    try:
        # Create checkout session
        if price_id:
            # Use pre-configured Stripe Price ID
            session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{'price': price_id, 'quantity': 1}],
                mode='payment',
                success_url=success_url,
                cancel_url=cancel_url,
                customer_email=current_user.email,
                metadata={
                    'user_id': current_user.id,
                    'license_type': license_type
                }
            )
        else:
            # Create price on-the-fly (for testing without pre-configured prices)
            session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'usd',
                        'unit_amount': int(license_info['price'] * 100),  # cents
                        'product_data': {
                            'name': f'SpaceTradingFX {license_type.title()} License',
                            'description': f"{license_info['duration_days']} days, up to {license_info['max_trades']} trades"
                        }
                    },
                    'quantity': 1
                }],
                mode='payment',
                success_url=success_url,
                cancel_url=cancel_url,
                customer_email=current_user.email,
                metadata={
                    'user_id': current_user.id,
                    'license_type': license_type
                }
            )
        
        return jsonify({
            'id': session.id,
            'url': session.url
        })
        
    except stripe.error.StripeError as e:
        current_app.logger.error(f"Stripe error: {e}")
        return jsonify({'error': str(e)}), 400


@bp.route('/success')
@login_required
def payment_success():
    """Handle successful payment redirect"""
    session_id = request.args.get('session_id')
    
    if session_id and STRIPE_AVAILABLE and stripe.api_key:
        try:
            # Verify the session
            session = stripe.checkout.Session.retrieve(session_id)
            
            if session.payment_status == 'paid':
                # Check if license already created (idempotency)
                existing = License.query.filter_by(stripe_payment_id=session_id).first()
                if not existing:
                    # Create license
                    license_type = session.metadata.get('license_type', 'basic')
                    user_id = session.metadata.get('user_id', current_user.id)
                    
                    create_license_for_user(user_id, license_type, session_id)
                
                return redirect(url_for('activate_license'))
                
        except Exception as e:
            current_app.logger.error(f"Error processing payment success: {e}")
    
    return redirect(url_for('activate_license'))


@bp.route('/cancel')
@login_required
def payment_cancel():
    """Handle cancelled payment"""
    return redirect(url_for('buy_license'))


@bp.route('/webhook', methods=['POST'])
def webhook():
    """Handle Stripe webhooks"""
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')
    
    if not STRIPE_AVAILABLE:
        return jsonify({'error': 'Stripe not available'}), 503
    
    try:
        if STRIPE_WEBHOOK_SECRET:
            event = stripe.Webhook.construct_event(
                payload, sig_header, STRIPE_WEBHOOK_SECRET
            )
        else:
            # For testing without webhook secret
            event = stripe.Event.construct_from(
                request.json, stripe.api_key
            )
    except ValueError as e:
        current_app.logger.error(f"Invalid payload: {e}")
        return jsonify({'error': 'Invalid payload'}), 400
    except Exception as e:
        current_app.logger.error(f"Webhook error: {e}")
        return jsonify({'error': 'Webhook error'}), 400
    
    # Handle the event
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        handle_successful_payment(session)
    
    elif event['type'] == 'payment_intent.succeeded':
        payment_intent = event['data']['object']
        current_app.logger.info(f"Payment succeeded: {payment_intent['id']}")
    
    elif event['type'] == 'payment_intent.payment_failed':
        payment_intent = event['data']['object']
        current_app.logger.warning(f"Payment failed: {payment_intent['id']}")
    
    return jsonify({'status': 'received'})


def handle_successful_payment(session):
    """Process successful payment from webhook"""
    session_id = session.get('id')
    customer_email = session.get('customer_email')
    
    # Check if already processed
    existing = License.query.filter_by(stripe_payment_id=session_id).first()
    if existing:
        current_app.logger.info(f"License already exists for session {session_id}")
        return
    
    # Get metadata
    metadata = session.get('metadata', {})
    user_id = metadata.get('user_id')
    license_type = metadata.get('license_type', 'basic')
    
    # Find user
    user = None
    if user_id:
        user = User.query.get(user_id)
    if not user and customer_email:
        user = User.query.filter_by(email=customer_email).first()
    
    if user:
        create_license_for_user(user.id, license_type, session_id)
        current_app.logger.info(f"License created for user {user.id} from webhook")
    else:
        current_app.logger.error(f"Could not find user for payment session {session_id}")


def create_license_for_user(user_id: str, license_type: str, stripe_payment_id: Optional[str] = None):
    """Create a new license for a user"""
    license_info = LICENSE_PRICES.get(license_type, LICENSE_PRICES['basic'])
    
    license_key = generate_license_key()
    
    # Ensure unique key
    while License.query.filter_by(license_key=license_key).first():
        license_key = generate_license_key()
    
    # Create license (SQLAlchemy models accept column names as kwargs)
    new_license = License()  # type: ignore
    new_license.user_id = user_id
    new_license.license_key = license_key
    new_license.license_type = license_type
    new_license.status = 'active'
    new_license.issued_at = datetime.now()
    new_license.expires_at = datetime.now() + timedelta(days=license_info['duration_days'])
    new_license.stripe_payment_id = stripe_payment_id
    new_license.max_active_trades = license_info['max_trades']
    new_license.features = {'features': license_info['features']}
    
    db.session.add(new_license)
    db.session.commit()
    
    # Process referral commission if applicable
    try:
        from mentor_system import process_referral_commission
        process_referral_commission(new_license)
    except Exception as e:
        current_app.logger.warning(f"Could not process referral commission: {e}")
    
    # Send notification
    try:
        from notifications import create_notification
        create_notification(
            user_id=user_id,
            title="🎉 License Activated!",
            message=f"Your {license_type.title()} license has been activated. Key: {license_key}",
            notification_type='license',
            data={'license_key': license_key, 'license_type': license_type}
        )
    except Exception as e:
        current_app.logger.warning(f"Could not send notification: {e}")
    
    return new_license


@bp.route('/licenses')
@login_required
def user_licenses():
    """Get user's licenses"""
    licenses = License.query.filter_by(user_id=current_user.id).order_by(License.created_at.desc()).all()
    
    return jsonify({
        'licenses': [{
            'id': lic.id,
            'license_key': lic.license_key,
            'license_type': lic.license_type,
            'status': lic.status,
            'issued_at': lic.issued_at.isoformat() if lic.issued_at else None,
            'expires_at': lic.expires_at.isoformat() if lic.expires_at else None,
            'max_active_trades': lic.max_active_trades,
            'features': lic.features
        } for lic in licenses]
    })


def register_payments_blueprint():
    app.register_blueprint(bp)


register_payments_blueprint()
