import rsa
import secrets
import json
import base64
import os
from datetime import datetime, timedelta
from app import db, app
from models import License, Activation


# Generate RSA keys (run once and store securely)
# In production, load these from environment variables or secure storage
def generate_keys():
    """Generate RSA key pair for license signing"""
    (pubkey, privkey) = rsa.newkeys(2048)
    return pubkey, privkey


def _load_keys_from_env():
    pub_pem = os.environ.get("LICENSE_PUBLIC_KEY_PEM")
    priv_pem = os.environ.get("LICENSE_PRIVATE_KEY_PEM")
    if pub_pem and priv_pem:
        try:
            return (
                rsa.PublicKey.load_pkcs1(pub_pem.encode()),
                rsa.PrivateKey.load_pkcs1(priv_pem.encode())
            )
        except Exception:
            pass
    # Fallback: generate ephemeral keys (log warning)
    app.logger.warning("Using generated ephemeral RSA keys for licensing; set LICENSE_PUBLIC_KEY_PEM & LICENSE_PRIVATE_KEY_PEM for persistence.")
    return generate_keys()

PUBLIC_KEY, PRIVATE_KEY = _load_keys_from_env()

# Max activations per license (overridable via env var)
MAX_ACTIVATIONS = int(os.environ.get("LICENSE_MAX_ACTIVATIONS", "3"))


LICENSE_TYPES = {
    'basic': {
        'price': 29.99,
        'duration_days': 30,
        'max_trades': 3,
        'features': ['basic_signals', 'manual_trading']
    },
    'premium': {
        'price': 79.99,
        'duration_days': 30,
        'max_trades': 10,
        'features': ['advanced_signals', 'auto_trading', 'email_alerts']
    },
    'professional': {
        'price': 199.99,
        'duration_days': 30,
        'max_trades': 50,
        'features': ['advanced_signals', 'auto_trading', 'email_alerts', 'priority_support', 'custom_strategies']
    }
}


def generate_license_key(user_id, license_type='basic'):
    """Generate a simple 13-character license key"""
    
    if license_type not in LICENSE_TYPES:
        raise ValueError(f"Invalid license type: {license_type}")
    
    # Generate a simple 13-character alphanumeric key (e.g., STFX-XXXX-XXXX)
    import string
    chars = string.ascii_uppercase + string.digits
    part1 = ''.join(secrets.choice(chars) for _ in range(4))
    part2 = ''.join(secrets.choice(chars) for _ in range(4))
    part3 = ''.join(secrets.choice(chars) for _ in range(4))
    license_key = f"{part1}-{part2}-{part3}"  # Format: XXXX-XXXX-XXXX (14 chars with dashes, 12 without)
    
    # Ensure uniqueness in database
    from models import License as LicenseModel
    while LicenseModel.query.filter_by(license_key=license_key).first():
        part1 = ''.join(secrets.choice(chars) for _ in range(4))
        part2 = ''.join(secrets.choice(chars) for _ in range(4))
        part3 = ''.join(secrets.choice(chars) for _ in range(4))
        license_key = f"{part1}-{part2}-{part3}"
    
    # Calculate expiry date
    duration = LICENSE_TYPES[license_type]['duration_days']
    issued_at = datetime.now()
    expires_at = issued_at + timedelta(days=duration)
    
    # Create license data (stored in database, not in key)
    license_data = {
        "id": license_key,
        "user_id": user_id,
        "license_type": license_type,
        "issued": issued_at.isoformat(),
        "expires": expires_at.isoformat(),
        "features": LICENSE_TYPES[license_type]['features'],
        "max_trades": LICENSE_TYPES[license_type]['max_trades']
    }
    
    return license_key, license_data


def validate_license_key(license_key):
    """Validate a license key by checking the database"""
    try:
        from models import License as LicenseModel
        
        # Look up license in database
        license_record = LicenseModel.query.filter_by(license_key=license_key).first()
        
        if not license_record:
            return False, "License key not found"
        
        if license_record.status != 'active':
            return False, f"License is {license_record.status}"
        
        # Check expiry
        if license_record.expires_at and datetime.now() > license_record.expires_at:
            return False, "License expired"
        
        # Build license data from database record
        license_data = {
            "id": license_record.license_key,
            "user_id": license_record.user_id,
            "license_type": license_record.license_type,
            "issued": license_record.issued_at.isoformat() if license_record.issued_at else None,
            "expires": license_record.expires_at.isoformat() if license_record.expires_at else None,
            "features": license_record.features or [],
            "max_trades": license_record.max_active_trades
        }
        
        return True, license_data
    
    except Exception as e:
        return False, f"License validation error: {str(e)}"


def create_user_license(user_id, license_type, stripe_payment_id=None):
    """Create a new license for a user after payment"""
    
    # Generate license key
    license_key, license_data = generate_license_key(user_id, license_type)
    
    # Create license record
    new_license = License(
        user_id=user_id,
        license_key=license_key,
        license_type=license_type,
        status='active',
        issued_at=datetime.fromisoformat(license_data['issued']),
        expires_at=datetime.fromisoformat(license_data['expires']),
        stripe_payment_id=stripe_payment_id,
        max_active_trades=license_data['max_trades'],
        features=license_data['features']
    )
    
    db.session.add(new_license)
    db.session.commit()
    
    return new_license


def record_activation(license_obj: License, account_number: str, server: str | None, machine_fingerprint: str | None):
    """Record a new activation if within limits."""
    existing = Activation.query.filter_by(license_id=license_obj.id, account_number=account_number).first()
    if existing:
        # Update last check
        existing.last_check_at = datetime.now()
        db.session.commit()
        return existing, False
    count = Activation.query.filter_by(license_id=license_obj.id).count()
    if count >= MAX_ACTIVATIONS:
        raise ValueError("Activation limit reached")
    act = Activation(
        license_id=license_obj.id,
        account_number=account_number,
        server=server,
        machine_fingerprint=machine_fingerprint,
        status='active'
    )
    db.session.add(act)
    db.session.commit()
    return act, True


def license_status(license_key: str):
    """Return status details including activations."""
    lic = License.query.filter_by(license_key=license_key).first()
    if not lic:
        return {"ok": False, "error": "not_found"}
    is_valid, data = validate_license_key(lic.license_key)
    if not is_valid:
        return {"ok": False, "error": data}
    acts = Activation.query.filter_by(license_id=lic.id).all()
    return {
        "ok": True,
        "license_type": lic.license_type,
        "expires_at": lic.expires_at.isoformat() if lic.expires_at else None,
        "status": lic.status,
        "activations": [
            {
                "account_number": a.account_number,
                "server": a.server,
                "machine_fingerprint": a.machine_fingerprint,
                "created_at": a.created_at.isoformat(),
                "last_check_at": a.last_check_at.isoformat(),
                "status": a.status
            } for a in acts
        ],
        "activation_limit": MAX_ACTIVATIONS,
    }


def get_active_license(user_id):
    """Get the active license for a user"""
    license = License.query.filter_by(
        user_id=user_id,
        status='active'
    ).filter(
        License.expires_at > datetime.now()
    ).first()
    
    # Update expired licenses
    if license and license.expires_at < datetime.now():
        license.status = 'expired'
        db.session.commit()
        return None
    
    return license


def check_license_valid(user_id):
    """Check if user has a valid active license"""
    license = get_active_license(user_id)
    if not license:
        return False, "No active license found"
    
    # Validate the license key
    is_valid, result = validate_license_key(license.license_key)
    
    if not is_valid:
        license.status = 'revoked'
        db.session.commit()
        return False, result
    
    return True, license


def require_license(f):
    """Decorator to require a valid license for a route"""
    from functools import wraps
    from flask import flash, redirect, url_for
    from flask_login import current_user
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please log in to access this feature', 'warning')
            return redirect(url_for('login'))
        
        is_valid, result = check_license_valid(current_user.id)
        if not is_valid:
            flash(f'Valid license required: {result}', 'error')
            return redirect(url_for('buy_license'))
        
        return f(*args, **kwargs)
    
    return decorated_function
