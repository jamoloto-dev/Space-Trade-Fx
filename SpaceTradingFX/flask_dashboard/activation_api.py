from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from .audit import record_audit_event
from .extensions import db, limiter
from .license_manager import check_license_valid, license_status, record_activation
from .models import License

bp = Blueprint("activation_api", __name__, url_prefix="/api/license")


@bp.route("/activate", methods=["POST"])
@login_required
@limiter.limit("10 per hour")
def activate_license():
    data = request.get_json() or {}
    license_key = str(data.get("license_key", "")).strip().upper()
    account_number = str(data.get("account_number", "")).strip()
    server = str(data.get("server", "")).strip()[:100] or None
    machine_fingerprint = str(data.get("machine_fingerprint", "")).strip()[:128] or None

    if not license_key or not account_number:
        return jsonify({"ok": False, "error": "license_key and account_number required"}), 400

    lic = License.query.filter_by(license_key=license_key, user_id=current_user.id).first()
    if not lic:
        return jsonify({"ok": False, "error": "license_not_found"}), 404

    # Ensure license still valid
    valid, reason = check_license_valid(current_user.id)
    if not valid:
        return jsonify({"ok": False, "error": f"invalid_license: {reason}"}), 403

    try:
        activation, created = record_activation(lic, account_number, server, machine_fingerprint)
        record_audit_event(
            "license.activated",
            actor_id=current_user.id,
            target_type="license",
            target_id=str(lic.id),
            metadata={"created": created},
        )
        db.session.commit()
        return jsonify(
            {
                "ok": True,
                "created": created,
                "activation": {
                    "account_number": activation.account_number,
                    "server": activation.server,
                    "machine_fingerprint": activation.machine_fingerprint,
                    "created_at": activation.created_at.isoformat(),
                    "last_check_at": activation.last_check_at.isoformat(),
                    "status": activation.status,
                },
            }
        )
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 429


@bp.route("/status", methods=["GET"])
@login_required
def status():
    license_key = request.args.get("license_key")
    if not license_key:
        return jsonify({"ok": False, "error": "license_key required"}), 400
    license_key = str(license_key).strip().upper()
    lic = License.query.filter_by(license_key=license_key).first()
    if not lic:
        return jsonify({"ok": False, "error": "not_found"}), 404
    if not (current_user.is_admin or lic.user_id == current_user.id):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    result = license_status(license_key)
    code = 200 if result.get("ok") else 404 if result.get("error") == "not_found" else 400
    return jsonify(result), code


@bp.route("/revoke", methods=["POST"])
@login_required
def revoke():
    data = request.get_json() or {}
    license_key = data.get("license_key")
    if not license_key:
        return jsonify({"ok": False, "error": "license_key required"}), 400
    lic = License.query.filter_by(license_key=license_key).first()
    if not lic:
        return jsonify({"ok": False, "error": "not_found"}), 404
    # Allow revoke if current user is admin or owner
    if not (current_user.is_admin or lic.user_id == current_user.id):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    lic.status = "revoked"
    record_audit_event("license.revoked", actor_id=current_user.id, target_type="license", target_id=str(lic.id))
    db.session.commit()
    return jsonify({"ok": True, "status": "revoked"})
