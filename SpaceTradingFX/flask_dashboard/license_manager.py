import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

import rsa
from sqlalchemy.exc import IntegrityError

from .audit import record_audit_event
from .extensions import db
from .models import Activation, License
from .plan_catalog import PLANS, get_plan

logger = logging.getLogger(__name__)


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
            return (rsa.PublicKey.load_pkcs1(pub_pem.encode()), rsa.PrivateKey.load_pkcs1(priv_pem.encode()))
        except Exception:
            pass
    # Fallback: generate ephemeral keys (log warning)
    logging.getLogger(__name__).warning(
        "Using generated ephemeral RSA keys for licensing; set LICENSE_PUBLIC_KEY_PEM & LICENSE_PRIVATE_KEY_PEM for persistence."
    )
    return generate_keys()


PUBLIC_KEY, PRIVATE_KEY = _load_keys_from_env()

# Max activations per license (overridable via env var)
MAX_ACTIVATIONS = int(os.environ.get("LICENSE_MAX_ACTIVATIONS", "3"))


LICENSE_TYPES = {
    code: {
        "price": float(plan.price_usd),
        "duration_days": plan.duration_days,
        "max_trades": plan.max_active_trades,
        "features": list(plan.features),
    }
    for code, plan in PLANS.items()
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    """SQLite may round-trip timezone-aware columns as naive values."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def generate_license_key(user_id, license_type="basic"):
    """Generate a simple 13-character license key"""

    plan = get_plan(license_type)

    # Generate a simple 13-character alphanumeric key (e.g., STFX-XXXX-XXXX)
    import string

    chars = string.ascii_uppercase + string.digits
    part1 = "".join(secrets.choice(chars) for _ in range(4))
    part2 = "".join(secrets.choice(chars) for _ in range(4))
    part3 = "".join(secrets.choice(chars) for _ in range(4))
    license_key = f"{part1}-{part2}-{part3}"  # Format: XXXX-XXXX-XXXX (14 chars with dashes, 12 without)

    # Ensure uniqueness in database
    from .models import License as LicenseModel

    while LicenseModel.query.filter_by(license_key=license_key).first():
        part1 = "".join(secrets.choice(chars) for _ in range(4))
        part2 = "".join(secrets.choice(chars) for _ in range(4))
        part3 = "".join(secrets.choice(chars) for _ in range(4))
        license_key = f"{part1}-{part2}-{part3}"

    # Calculate expiry date
    duration = plan.duration_days
    issued_at = utcnow()
    expires_at = issued_at + timedelta(days=duration)

    # Create license data (stored in database, not in key)
    license_data = {
        "id": license_key,
        "user_id": user_id,
        "license_type": license_type,
        "issued": issued_at.isoformat(),
        "expires": expires_at.isoformat(),
        "features": list(plan.features),
        "max_trades": plan.max_active_trades,
    }

    return license_key, license_data


def validate_license_key(license_key):
    """Validate a license key by checking the database"""
    try:
        from .models import License as LicenseModel

        # Look up license in database
        license_record = LicenseModel.query.filter_by(license_key=license_key).first()

        if not license_record:
            return False, "License key not found"

        if license_record.status != "active":
            return False, f"License is {license_record.status}"

        # Check expiry
        if license_record.expires_at and utcnow() > _as_utc(license_record.expires_at):
            return False, "License expired"

        # Build license data from database record
        license_data = {
            "id": license_record.license_key,
            "user_id": license_record.user_id,
            "license_type": license_record.license_type,
            "issued": license_record.issued_at.isoformat() if license_record.issued_at else None,
            "expires": license_record.expires_at.isoformat() if license_record.expires_at else None,
            "features": license_record.features or [],
            "max_trades": license_record.max_active_trades,
        }

        return True, license_data

    except Exception:
        logger.exception("License validation error")
        return False, "License validation failed"


def provision_license(
    user_id: str,
    license_type: str,
    *,
    stripe_payment_id: str | None = None,
    source: str,
    actor_id: str | None = None,
) -> License:
    """Stage an active license from an approved provisioning authority only."""
    if source not in {"stripe_webhook", "admin", "test"}:
        raise ValueError("Unapproved license provisioning source")
    if source == "stripe_webhook" and not stripe_payment_id:
        raise ValueError("Stripe provisioning requires a payment id")
    plan = get_plan(license_type)
    if stripe_payment_id:
        existing = License.query.filter_by(stripe_payment_id=stripe_payment_id).first()
        if existing:
            return existing
    license_key, _ = generate_license_key(user_id, license_type)
    issued_at = utcnow()
    new_license = License(
        user_id=user_id,
        license_key=license_key,
        license_type=plan.code,
        status="active",
        issued_at=issued_at,
        expires_at=issued_at + timedelta(days=plan.duration_days),
        stripe_payment_id=stripe_payment_id,
        max_active_trades=plan.max_active_trades,
        features={"features": list(plan.features), "provisioning_source": source},
    )
    db.session.add(new_license)
    db.session.flush()
    record_audit_event(
        "license.provisioned",
        actor_id=actor_id or user_id,
        target_type="license",
        target_id=str(new_license.id),
        metadata={"source": source, "plan": plan.code},
    )
    return new_license


def create_user_license(user_id, license_type, stripe_payment_id=None):
    """Legacy test helper; production code must use ``provision_license``.

    Keeping this callable solely in Flask testing contexts avoids silently
    reintroducing a free-license path through an old integration.
    """
    from flask import current_app

    if not current_app.config.get("TESTING"):
        raise RuntimeError("Active licenses require a verified Stripe webhook or audited admin action")
    license_obj = provision_license(user_id, license_type, stripe_payment_id=stripe_payment_id, source="test")
    db.session.commit()
    return license_obj


def record_activation(license_obj: License, account_number: str, server: str | None, machine_fingerprint: str | None):
    """Record a new activation if within limits."""
    existing = Activation.query.filter_by(license_id=license_obj.id, account_number=account_number).first()
    if existing:
        # Update last check
        existing.last_check_at = utcnow()
        return existing, False
    count = Activation.query.filter_by(license_id=license_obj.id).count()
    if count >= MAX_ACTIVATIONS:
        raise ValueError("Activation limit reached")
    act = Activation(
        license_id=license_obj.id,
        account_number=account_number,
        server=server,
        machine_fingerprint=machine_fingerprint,
        status="active",
    )
    try:
        # The database uniqueness constraint is the concurrency authority.
        # A savepoint lets a duplicate concurrent request become idempotent
        # without discarding the enclosing request/audit transaction.
        with db.session.begin_nested():
            db.session.add(act)
            db.session.flush()
    except IntegrityError:
        existing = Activation.query.filter_by(license_id=license_obj.id, account_number=account_number).first()
        if existing is not None:
            existing.last_check_at = utcnow()
            return existing, False
        raise
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
                "status": a.status,
            }
            for a in acts
        ],
        "activation_limit": MAX_ACTIVATIONS,
    }


def get_active_license(user_id):
    """Get the active license for a user"""
    license = License.query.filter_by(user_id=user_id, status="active").order_by(License.expires_at.desc()).first()

    # Update expired licenses
    if license and license.expires_at and _as_utc(license.expires_at) <= utcnow():
        license.status = "expired"
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
        license.status = "revoked"
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
            flash("Please log in to access this feature", "warning")
            return redirect(url_for("auth.login"))

        is_valid, result = check_license_valid(current_user.id)
        if not is_valid:
            flash(f"Valid license required: {result}", "error")
            return redirect(url_for("auth.buy_license"))

        return f(*args, **kwargs)

    return decorated_function
