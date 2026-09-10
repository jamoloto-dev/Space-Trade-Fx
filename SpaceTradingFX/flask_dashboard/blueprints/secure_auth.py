"""Password-based identity routes for the Phase 0 dashboard."""

from __future__ import annotations

from email.utils import parseaddr
from uuid import uuid4

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from ..extensions import db, limiter
from ..audit import record_audit_event
from ..license_manager import check_license_valid, validate_license_key
from ..plan_catalog import PLANS, public_plan_catalog
from ..models import License, User

auth_bp = Blueprint("auth", __name__)


def _valid_email(value: str) -> bool:
    _, address = parseaddr(value)
    return address == value and "@" in address and len(address) <= 254


@auth_bp.get("/")
def index():
    return redirect(url_for("mobile.home")) if current_user.is_authenticated else render_template("landing.html")


@auth_bp.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per hour")
def register():
    if current_user.is_authenticated:
        return redirect(url_for("mobile.home"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirmation = request.form.get("password_confirmation", "")
        if not _valid_email(email) or len(password) < 12 or password != confirmation:
            flash("Enter a valid email and matching password of at least 12 characters.", "error")
        elif User.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "error")
        else:
            user = User(id=str(uuid4()), email=email, first_name="User")
            user.set_password(password)
            db.session.add(user)
            record_audit_event("authentication.registered", actor_id=user.id, target_type="user", target_id=user.id)
            db.session.commit()
            login_user(user, remember=False)
            flash("Account created. Activate a license to continue.", "success")
            return redirect(url_for("auth.activate_license"))
    return render_template("register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per hour")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("mobile.home"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first() if _valid_email(email) else None
        if not user or not user.check_password(password):
            record_audit_event("authentication.failed", target_type="user", target_id=email)
            db.session.commit()
            flash("Invalid email or password.", "error")
        else:
            login_user(user, remember=request.form.get("remember") == "on")
            record_audit_event("authentication.logged_in", actor_id=user.id, target_type="user", target_id=user.id)
            db.session.commit()
            return redirect(url_for("mobile.home"))
    return render_template("login.html")


@auth_bp.get("/logout")
@login_required
def logout():
    record_audit_event("authentication.logged_out", actor_id=current_user.id, target_type="user", target_id=current_user.id)
    db.session.commit()
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.index"))


@auth_bp.route("/activate", methods=["GET", "POST"])
@login_required
def activate_license():
    valid, _ = check_license_valid(current_user.id)
    if valid:
        return redirect(url_for("mobile.home"))
    if request.method == "POST":
        license_key = request.form.get("license_key", "").strip().upper()
        valid, result = validate_license_key(license_key) if license_key else (False, "License key required")
        license_record = License.query.filter_by(license_key=license_key).first() if valid else None
        if license_record and license_record.user_id == current_user.id:
            flash("License activated successfully.", "success")
            return redirect(url_for("mobile.home"))
        flash("This license cannot be activated for this account.", "error")
    return render_template("activate_license.html")


@auth_bp.get("/licenses")
@login_required
def view_licenses():
    return render_template("licenses.html", licenses=License.query.filter_by(user_id=current_user.id).all())


@auth_bp.route("/buy-license", methods=["GET", "POST"])
@login_required
def buy_license():
    """Display the catalogue; license issuance is webhook/admin-only.

    A POST no longer creates a license.  Checkout session creation is handled
    by the payments blueprint and a verified webhook is the sole customer
    provisioning path.
    """
    if request.method == "POST":
        license_type = request.form.get("license_type")
        if license_type in PLANS:
            return redirect(url_for("payments.start_checkout", license_type=license_type), code=307)
        flash("Select a valid license plan.", "error")
    return render_template("buy_license.html", license_types=public_plan_catalog())
