from functools import wraps

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required, login_user, logout_user

from .audit import record_audit_event
from .extensions import db, limiter
from .license_manager import provision_license
from .models import License, User
from .plan_catalog import PLANS

bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({"error": "authentication required"}), 401
        if not getattr(current_user, "is_admin", False):
            return jsonify({"error": "admin privileges required"}), 403
        return f(*args, **kwargs)

    wrapper.__name__ = f.__name__
    return wrapper


@bp.route("/login", methods=["POST"])
@limiter.limit("5 per hour")
def admin_login():
    data = request.get_json() or request.form
    email = data.get("email")
    password = data.get("password")
    if not email or not password:
        return jsonify({"error": "email and password required"}), 400
    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        record_audit_event("admin.authentication_failed", target_type="user", target_id=str(email)[:254])
        db.session.commit()
        return jsonify({"error": "invalid credentials"}), 401
    if not user.is_admin:
        return jsonify({"error": "not an admin user"}), 403
    login_user(user)
    record_audit_event("admin.authentication_logged_in", actor_id=user.id, target_type="user", target_id=user.id)
    db.session.commit()
    return jsonify({"status": "ok", "message": "logged in"})


@bp.route("/logout", methods=["POST"])
@login_required
@admin_required
def admin_logout():
    record_audit_event(
        "admin.authentication_logged_out", actor_id=current_user.id, target_type="user", target_id=current_user.id
    )
    db.session.commit()
    logout_user()
    return jsonify({"status": "ok", "message": "logged out"})


@bp.route("/licenses", methods=["GET"])
@login_required
@admin_required
def list_licenses():
    licenses = License.query.all()
    out = []
    for lic in licenses:
        out.append(
            {
                "id": lic.id,
                "user_id": lic.user_id,
                "license_key": lic.license_key,
                "license_type": lic.license_type,
                "status": lic.status,
                "issued_at": lic.issued_at.isoformat() if lic.issued_at else None,
                "expires_at": lic.expires_at.isoformat() if lic.expires_at else None,
            }
        )
    return jsonify(out)


@bp.route("/licenses/create", methods=["POST"])
@login_required
@admin_required
def create_license():
    data = request.get_json() or request.form
    user_id = data.get("user_id")
    license_type = str(data.get("license_type", ""))
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
    if license_type not in PLANS or User.query.get(user_id) is None:
        return jsonify({"error": "valid user_id and license_type required"}), 400
    lic = provision_license(user_id, license_type, source="admin", actor_id=current_user.id)
    record_audit_event("admin.license_created", actor_id=current_user.id, target_type="license", target_id=str(lic.id))
    db.session.commit()
    return jsonify({"status": "ok", "license_id": lic.id, "license_key": lic.license_key})


@bp.route("/licenses/<int:license_id>/status", methods=["POST"])
@login_required
@admin_required
def set_license_status(license_id):
    data = request.get_json() or request.form
    status = data.get("status")
    if status not in {"pending", "active", "expired", "revoked"}:
        return jsonify({"error": "valid status required"}), 400
    lic = License.query.get(license_id)
    if not lic:
        return jsonify({"error": "license not found"}), 404
    lic.status = status
    record_audit_event(
        "admin.license_status_changed",
        actor_id=current_user.id,
        target_type="license",
        target_id=str(lic.id),
        metadata={"status": status},
    )
    db.session.commit()
    return jsonify({"status": "ok", "license_id": lic.id, "new_status": status})


@bp.route("/ui")
@login_required
@admin_required
def admin_ui():
    return render_template("admin.html")
