"""Stripe checkout and verified, idempotent license provisioning.

Browser redirects are informational only. They never grant a license: Stripe's
signed webhook is the customer provisioning authority.
"""

from __future__ import annotations

from typing import Any

from flask import Blueprint, current_app, jsonify, redirect, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from .audit import record_audit_event
from .extensions import csrf, db, limiter
from .license_manager import provision_license
from .models import ProcessedStripeEvent, User
from .plan_catalog import PLANS, get_plan, public_plan_catalog

try:
    import stripe as stripe_lib
except ImportError:  # pragma: no cover - deployment dependency guard
    stripe_lib = None


bp = Blueprint("payments", __name__, url_prefix="/payments")


def _stripe() -> Any | None:
    if stripe_lib is None:
        return None
    api_key = current_app.config.get("STRIPE_SECRET_KEY", "")
    if not api_key:
        return None
    stripe_lib.api_key = api_key
    return stripe_lib


def _requested_plan() -> str:
    data = request.get_json(silent=True) or request.form
    return str(data.get("license_type", request.args.get("license_type", ""))).strip().lower()


def _create_checkout_session(license_type: str) -> Any:
    stripe = _stripe()
    if stripe is None:
        raise RuntimeError("Payments are not configured")
    plan = get_plan(license_type)
    success_url = url_for("payments.payment_success", _external=True) + "?session_id={CHECKOUT_SESSION_ID}"
    cancel_url = url_for("payments.payment_cancel", _external=True)
    if plan.stripe_price_id:
        line_item: dict[str, Any] = {"price": plan.stripe_price_id, "quantity": 1}
    else:
        line_item = {
            "price_data": {
                "currency": "usd",
                "unit_amount": plan.price_cents,
                "product_data": {"name": f"SpaceTradingFX {plan.code.title()} License"},
            },
            "quantity": 1,
        }
    return stripe.checkout.Session.create(
        payment_method_types=["card"], line_items=[line_item], mode="payment",
        success_url=success_url, cancel_url=cancel_url, customer_email=current_user.email,
        client_reference_id=current_user.id,
        metadata={"user_id": current_user.id, "license_type": plan.code},
    )


@bp.get("/config")
def get_config():
    return jsonify({"publishable_key": current_app.config.get("STRIPE_PUBLISHABLE_KEY", ""), "prices": public_plan_catalog()})


@bp.post("/create-checkout-session")
@login_required
@limiter.limit("10 per hour")
def create_checkout_session():
    license_type = _requested_plan()
    if license_type not in PLANS:
        return jsonify({"error": "Invalid license plan"}), 400
    try:
        session = _create_checkout_session(license_type)
    except RuntimeError:
        return jsonify({"error": "Payment system is not configured"}), 503
    except Exception:
        current_app.logger.exception("Stripe checkout creation failed")
        return jsonify({"error": "Unable to start checkout"}), 502
    record_audit_event("payment.checkout_started", actor_id=current_user.id, target_type="plan", target_id=license_type)
    db.session.commit()
    return jsonify({"id": session.id, "url": session.url})


@bp.post("/start-checkout")
@login_required
@limiter.limit("10 per hour")
def start_checkout():
    """HTML form endpoint used by the purchase catalogue."""
    license_type = _requested_plan()
    if license_type not in PLANS:
        return redirect(url_for("auth.buy_license"))
    try:
        session = _create_checkout_session(license_type)
    except RuntimeError:
        current_app.logger.warning("Checkout requested while Stripe is unconfigured")
        return jsonify({"error": "Payment system is not configured"}), 503
    except Exception:
        current_app.logger.exception("Stripe checkout creation failed")
        return jsonify({"error": "Unable to start checkout"}), 502
    record_audit_event("payment.checkout_started", actor_id=current_user.id, target_type="plan", target_id=license_type)
    db.session.commit()
    return redirect(session.url, code=303)


@bp.get("/success")
@login_required
def payment_success():
    """Never trust a success redirect; webhook processing remains authoritative."""
    return redirect(url_for("auth.activate_license"))


@bp.get("/cancel")
@login_required
def payment_cancel():
    return redirect(url_for("auth.buy_license"))


@bp.post("/webhook")
@csrf.exempt
@limiter.exempt
def webhook():
    """Verify a Stripe event before writing an idempotent provisioning record."""
    stripe = _stripe()
    signing_secret = current_app.config.get("STRIPE_WEBHOOK_SECRET", "")
    if stripe is None or not signing_secret:
        current_app.logger.error("Rejected Stripe webhook: signature verification is not configured")
        return jsonify({"error": "Webhook verification is not configured"}), 503
    try:
        event = stripe.Webhook.construct_event(request.get_data(), request.headers.get("Stripe-Signature", ""), signing_secret)
    except ValueError:
        return jsonify({"error": "Invalid payload"}), 400
    except Exception:
        current_app.logger.warning("Rejected Stripe webhook with invalid signature")
        return jsonify({"error": "Invalid signature"}), 400

    event_id, event_type = str(event.get("id", "")), str(event.get("type", ""))
    if not event_id or not event_type:
        return jsonify({"error": "Malformed Stripe event"}), 400
    if ProcessedStripeEvent.query.filter_by(stripe_event_id=event_id).first():
        return jsonify({"status": "already_processed"}), 200

    ledger_entry = ProcessedStripeEvent(stripe_event_id=event_id, event_type=event_type, payload=event)
    db.session.add(ledger_entry)
    try:
        if event_type != "checkout.session.completed":
            ledger_entry.status = "ignored"
        else:
            session = event["data"]["object"]
            if session.get("payment_status") != "paid":
                ledger_entry.status = "ignored_unpaid"
            else:
                metadata = session.get("metadata") or {}
                user_id = str(metadata.get("user_id", ""))
                plan_code = str(metadata.get("license_type", ""))
                if not user_id or plan_code not in PLANS or db.session.get(User, user_id) is None:
                    ledger_entry.status = "rejected_metadata"
                    record_audit_event("payment.webhook_rejected", target_type="stripe_event", target_id=event_id)
                else:
                    provision_license(user_id, plan_code, stripe_payment_id=str(session["id"]), source="stripe_webhook")
                    ledger_entry.status = "processed"
                    record_audit_event("payment.verified", actor_id=user_id, target_type="stripe_event", target_id=event_id)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        if ProcessedStripeEvent.query.filter_by(stripe_event_id=event_id).first():
            return jsonify({"status": "already_processed"}), 200
        current_app.logger.exception("Stripe webhook integrity failure")
        return jsonify({"error": "Webhook persistence failed"}), 500
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Stripe webhook processing failed")
        return jsonify({"error": "Webhook processing failed"}), 500
    return jsonify({"status": ledger_entry.status}), 200


__all__ = ["bp", "webhook", "create_checkout_session", "start_checkout"]
