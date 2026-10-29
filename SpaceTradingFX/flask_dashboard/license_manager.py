import base64
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

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


class PemString(str):
    """String subclass that tracks key provenance source."""

    source: str = "unknown"


def sanitize_key_pem(key_str: str | None) -> str | None:
    """Sanitize and normalize PEM key strings:
    - Strip leading/trailing whitespace and wrapping quotes (' or ").
    - Support base64-encoded PEM strings if not starting with '-----BEGIN'.
    - Replace literal escaped newline sequences (\\n, \\r\\n).
    - Reconstruct valid 64-char wrapped PEM formatting if collapsed onto a single line.
    """
    if not key_str or not isinstance(key_str, str):
        return None

    cleaned = key_str.strip()

    # Strip surrounding single or double quotes
    while len(cleaned) >= 2 and (
        (cleaned.startswith('"') and cleaned.endswith('"')) or (cleaned.startswith("'") and cleaned.endswith("'"))
    ):
        cleaned = cleaned[1:-1].strip()

    # Fallback for base64-encoded PEM strings if not starting with -----BEGIN
    if not cleaned.startswith("-----BEGIN"):
        try:
            b64_candidate = re.sub(r"\s+", "", cleaned)
            decoded_bytes = base64.b64decode(b64_candidate, validate=True)
            decoded_str = decoded_bytes.decode("utf-8")
            if "-----BEGIN" in decoded_str:
                cleaned = decoded_str.strip()
                while len(cleaned) >= 2 and (
                    (cleaned.startswith('"') and cleaned.endswith('"'))
                    or (cleaned.startswith("'") and cleaned.endswith("'"))
                ):
                    cleaned = cleaned[1:-1].strip()
        except Exception:
            pass

    # Replace escaped literal newline sequences and normalize CRLF
    cleaned = cleaned.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\r\n", "\n").strip()

    # Reconstruct PEM formatting if collapsed onto a single line with spaces
    pem_match = re.search(r"-----BEGIN ([^-]+)-----\s*(.+?)\s*-----END ([^-]+)-----", cleaned, re.DOTALL)
    if pem_match:
        header_type = pem_match.group(1).strip()
        body = pem_match.group(2)
        footer_type = pem_match.group(3).strip()

        body_clean = re.sub(r"\s+", "", body)
        chunked = [body_clean[i : i + 64] for i in range(0, len(body_clean), 64)]
        cleaned = f"-----BEGIN {header_type}-----\n" + "\n".join(chunked) + f"\n-----END {footer_type}-----"

    return cleaned if cleaned else None


def _parse_rsa_key(pem_raw: str, is_private: bool = False):
    """Sanitize and parse a single RSA public or private key, raising on error."""
    clean = sanitize_key_pem(pem_raw)
    if not clean:
        raise ValueError("Sanitized PEM string is empty")

    data = clean.encode("utf-8")
    if is_private:
        try:
            return rsa.PrivateKey.load_pkcs1(data)
        except Exception as e_pkcs1:
            try:
                from cryptography.hazmat.primitives import serialization

                crypto_priv = serialization.load_pem_private_key(data, password=None)
                pkcs1_pem = crypto_priv.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption(),
                )
                return rsa.PrivateKey.load_pkcs1(pkcs1_pem)
            except Exception as e_crypto:
                raise ValueError(
                    f"Invalid private key format (PKCS#1 error: {e_pkcs1}; cryptography fallback error: {e_crypto})"
                ) from e_crypto
    else:
        try:
            return rsa.PublicKey.load_pkcs1(data)
        except Exception as e_pkcs1:
            try:
                return rsa.PublicKey.load_pkcs1_openssl_pem(data)
            except Exception as e_openssl:
                try:
                    from cryptography.hazmat.primitives import serialization

                    crypto_pub = serialization.load_pem_public_key(data)
                    pkcs1_pem = crypto_pub.public_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PublicFormat.PKCS1,
                    )
                    return rsa.PublicKey.load_pkcs1(pkcs1_pem)
                except Exception as e_crypto:
                    raise ValueError(
                        f"Invalid public key format (PKCS#1 error: {e_pkcs1}; OpenSSL error: {e_openssl}; cryptography fallback error: {e_crypto})"
                    ) from e_crypto


def _parse_rsa_keys(pub_pem_raw: str, priv_pem_raw: str) -> tuple[rsa.PublicKey, rsa.PrivateKey] | None:
    """Sanitize and parse public and private RSA keys; returns None on failure."""
    try:
        pub = _parse_rsa_key(pub_pem_raw, is_private=False)
        priv = _parse_rsa_key(priv_pem_raw, is_private=True)
        return pub, priv
    except Exception as exc:
        logger.debug("Failed parsing RSA keys: %s", exc)
        return None


def _load_pem_key(
    env_var_name: str,
    secret_filename: str,
) -> str | None:
    """Resolve a PEM key string across candidate file paths and environment variables.

    Priority order:
    1. File path environment variable if set (LICENSE_PRIVATE_KEY_PATH / LICENSE_PUBLIC_KEY_PATH)
    2. Render Secret Files & local paths:
       - /etc/secrets/{secret_filename}
       - ./{secret_filename}
       - /app/{secret_filename}
       - {app_root}/{secret_filename}
    3. Environment variable os.environ.get(env_var_name)
    """
    # 1. Optional file path environment variable
    path_env_var = (
        "LICENSE_PRIVATE_KEY_PATH"
        if "PRIVATE" in env_var_name
        else "LICENSE_PUBLIC_KEY_PATH"
        if "PUBLIC" in env_var_name
        else env_var_name.replace("_PEM", "_PATH")
    )
    custom_path_str = os.environ.get(path_env_var)
    if custom_path_str:
        try:
            custom_path = Path(custom_path_str).resolve()
            if custom_path.is_file() and custom_path.stat().st_size > 0:
                content = custom_path.read_text(encoding="utf-8")
                res = PemString(content)
                res.source = "secret_file"
                return res
        except Exception as exc:
            logger.debug("Failed reading %s at %s: %s", path_env_var, custom_path_str, exc)

    # 2. Check candidate file paths
    app_root = Path(__file__).resolve().parents[2]
    candidate_paths = [
        Path(f"/etc/secrets/{secret_filename}"),
        Path(f"./{secret_filename}"),
        Path(f"/app/{secret_filename}"),
        app_root / secret_filename,
    ]

    for p in candidate_paths:
        try:
            if p.is_file() and p.stat().st_size > 0:
                content = p.read_text(encoding="utf-8")
                res = PemString(content)
                res.source = "secret_file"
                return res
        except Exception as exc:
            logger.debug("Failed reading candidate file %s: %s", p, exc)

    # 3. Check environment variable
    env_val = os.environ.get(env_var_name)
    if env_val and env_val.strip():
        res = PemString(env_val)
        res.source = "env_var"
        return res

    return None


def _load_keys_from_secret_files(
    candidate_pairs: list[tuple[Path | str, Path | str]] | None = None,
) -> tuple[rsa.PublicKey, rsa.PrivateKey] | None:
    """Attempt loading RSA keys from Render Secret Files or app root files."""
    app_root = Path(__file__).resolve().parents[2]
    if candidate_pairs is None:
        candidate_pairs = [
            (Path("/etc/secrets/license_private_key.pem"), Path("/etc/secrets/license_public_key.pem")),
            (Path("./license_private_key.pem"), Path("./license_public_key.pem")),
            (Path("/app/license_private_key.pem"), Path("/app/license_public_key.pem")),
            (app_root / "license_private_key.pem", app_root / "license_public_key.pem"),
        ]

    for priv_item, pub_item in candidate_pairs:
        try:
            priv_path = Path(priv_item)
            pub_path = Path(pub_item)
            if (
                priv_path.is_file()
                and pub_path.is_file()
                and priv_path.stat().st_size > 0
                and pub_path.stat().st_size > 0
            ):
                priv_pem = priv_path.read_text(encoding="utf-8")
                pub_pem = pub_path.read_text(encoding="utf-8")
                keys = _parse_rsa_keys(pub_pem, priv_pem)
                if keys:
                    logger.info("Loaded RSA licensing keys from Render Secret Files")
                    return keys
        except Exception as exc:
            logger.debug("Failed reading secret file pair (%s, %s): %s", priv_item, pub_item, exc)

    return None


def _load_keys_from_env_vars() -> tuple[rsa.PublicKey, rsa.PrivateKey] | None:
    """Attempt loading RSA keys from environment variables."""
    pub_pem = os.environ.get("LICENSE_PUBLIC_KEY_PEM")
    priv_pem = os.environ.get("LICENSE_PRIVATE_KEY_PEM")
    if pub_pem and priv_pem:
        keys = _parse_rsa_keys(pub_pem, priv_pem)
        if keys:
            logger.info("Loaded RSA licensing keys from environment variables")
            return keys
        logger.warning(
            "LICENSE_PUBLIC_KEY_PEM and LICENSE_PRIVATE_KEY_PEM found in environment, but could not be parsed as valid RSA keys."
        )
    return None


def load_keys(
    secret_file_pairs: list[tuple[Path | str, Path | str]] | None = None,
) -> tuple[rsa.PublicKey, rsa.PrivateKey]:
    """Load RSA key pair for license signing and validation.

    Checks sources in order:
    1. Explicit secret_file_pairs if provided (e.g. for testing)
    2. Render Secret Files & file paths (/etc/secrets/..., ./..., /app/...)
    3. Environment variables (LICENSE_PRIVATE_KEY_PEM & LICENSE_PUBLIC_KEY_PEM)
    4. Ephemeral key generation fallback if both sources are missing or invalid
    """
    if secret_file_pairs is not None:
        for priv_item, pub_item in secret_file_pairs:
            try:
                priv_path = Path(priv_item)
                pub_path = Path(pub_item)
                if (
                    priv_path.is_file()
                    and pub_path.is_file()
                    and priv_path.stat().st_size > 0
                    and pub_path.stat().st_size > 0
                ):
                    priv_raw = priv_path.read_text(encoding="utf-8")
                    pub_raw = pub_path.read_text(encoding="utf-8")
                    try:
                        privkey = _parse_rsa_key(priv_raw, is_private=True)
                        pubkey = _parse_rsa_key(pub_raw, is_private=False)
                        logger.info("Loaded RSA licensing keys from Render Secret Files")
                        return pubkey, privkey
                    except Exception as parse_err:
                        logger.warning(
                            "Failed to parse RSA licensing keys from secret files (%s, %s): %s",
                            priv_path,
                            pub_path,
                            parse_err,
                        )
            except Exception as exc:
                logger.debug("Failed reading secret file pair (%s, %s): %s", priv_item, pub_item, exc)

    priv_pem = _load_pem_key("LICENSE_PRIVATE_KEY_PEM", "license_private_key.pem")
    pub_pem = _load_pem_key("LICENSE_PUBLIC_KEY_PEM", "license_public_key.pem")

    if priv_pem and pub_pem:
        try:
            privkey = _parse_rsa_key(priv_pem, is_private=True)
            pubkey = _parse_rsa_key(pub_pem, is_private=False)
            source_priv = getattr(priv_pem, "source", "")
            source_pub = getattr(pub_pem, "source", "")
            if source_priv == "secret_file" or source_pub == "secret_file":
                logger.info("Loaded RSA licensing keys from Render Secret Files")
            else:
                logger.info("Loaded RSA licensing keys from environment variables")
            return pubkey, privkey
        except Exception as parse_err:
            logger.warning("Failed to parse provided RSA licensing keys: %s", parse_err)
    elif priv_pem or pub_pem:
        missing = "LICENSE_PUBLIC_KEY_PEM" if not pub_pem else "LICENSE_PRIVATE_KEY_PEM"
        logger.warning("Partial RSA licensing key configuration found; %s is missing or empty.", missing)

    logger.warning(
        "Using generated ephemeral RSA keys for licensing; set LICENSE_PUBLIC_KEY_PEM & LICENSE_PRIVATE_KEY_PEM for persistence."
    )
    return generate_keys()


# Backward compatibility alias
_load_keys_from_env = load_keys

PUBLIC_KEY, PRIVATE_KEY = load_keys()

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
