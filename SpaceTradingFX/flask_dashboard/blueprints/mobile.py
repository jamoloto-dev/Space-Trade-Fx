"""
Mobile Blueprint
Handles all mobile-optimized routes (/m/*)
"""

from decimal import Decimal, InvalidOperation

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..symbols import DEFAULT_LOT_SIZE, SUPPORTED_SYMBOLS

mobile_bp = Blueprint("mobile", __name__)

DEFAULT_LOT_SIZES = {symbol: DEFAULT_LOT_SIZE for symbol in SUPPORTED_SYMBOLS}


@mobile_bp.route("/")
@mobile_bp.route("/home")
@login_required
def home():
    """Mobile Home Screen - Broker Connection and Robot Status"""
    from ..license_manager import check_license_valid
    from ..models import BrokerAccount, TradingPreference
    from ..trading_engine import TradingEngine

    is_valid, license_info = check_license_valid(current_user.id)
    engine = TradingEngine(current_user.id)
    account_summary = engine.get_account_summary()
    preferences = TradingPreference.query.filter_by(user_id=current_user.id).first()
    broker_account = BrokerAccount.query.filter_by(user_id=current_user.id).first()

    return render_template(
        "mobile_home.html",
        user=current_user,
        has_license=is_valid,
        license=license_info if is_valid else None,
        account_summary=account_summary,
        preferences=preferences,
        broker_account=broker_account,
        active_page="home",
    )


@mobile_bp.route("/quotes", methods=["GET", "POST"])
@login_required
def quotes():
    """Mobile Quotes Screen - Trading Symbols Configuration"""
    from ..extensions import db
    from ..models import TradingPreference

    preferences = TradingPreference.query.filter_by(user_id=current_user.id).first()
    if not preferences:
        preferences = TradingPreference()  # type: ignore
        preferences.user_id = current_user.id
        db.session.add(preferences)
        db.session.commit()

    available_pairs = sorted(SUPPORTED_SYMBOLS)

    if request.method == "POST":
        enabled_pairs = request.form.getlist("enabled_pairs")
        preferences.currency_pairs = enabled_pairs

        direction_prefs = {}
        lot_sizes = preferences.strategy_settings.get("lot_sizes", {}) if preferences.strategy_settings else {}

        for pair in available_pairs:
            direction = request.form.get(f"direction_{pair}", "BOTH")
            if direction in ("BOTH", "BUY", "SELL"):
                direction_prefs[pair] = direction

            lot_size = request.form.get(f"lot_{pair}")
            if lot_size:
                try:
                    parsed_lot = Decimal(lot_size)
                    if not Decimal("0") < parsed_lot <= Decimal("1.00"):
                        raise ValueError
                    lot_sizes[pair] = str(parsed_lot.quantize(Decimal("0.0001")))
                except (InvalidOperation, ValueError):
                    lot_sizes[pair] = str(DEFAULT_LOT_SIZES.get(pair, DEFAULT_LOT_SIZE))

        preferences.direction_preferences = direction_prefs

        if not preferences.strategy_settings:
            preferences.strategy_settings = {}
        preferences.strategy_settings["lot_sizes"] = lot_sizes

        preferences.trading_enabled = request.form.get("trading_enabled") == "on"

        db.session.commit()
        flash("Settings saved successfully!", "success")
        return redirect(url_for("mobile.quotes"))

    symbols = []
    lot_sizes = preferences.strategy_settings.get("lot_sizes", {}) if preferences.strategy_settings else {}
    direction_prefs = preferences.direction_preferences if preferences.direction_preferences else {}

    from ..models import BrokerAccount
    broker_acct = BrokerAccount.query.filter_by(user_id=current_user.id, is_connected=True).first()
    active_platform = broker_acct.platform if broker_acct else "MT5"

    for pair in available_pairs:
        symbols.append(
            {
                "pair": pair,
                "enabled": pair in (preferences.currency_pairs or []),
                "lot_size": lot_sizes.get(pair, DEFAULT_LOT_SIZES.get(pair, 0.01)),
                "direction": direction_prefs.get(pair, "BOTH"),
                "platform": active_platform,
            }
        )

    return render_template(
        "mobile_quotes.html", symbols=symbols, trading_enabled=preferences.trading_enabled, active_page="quotes"
    )


@mobile_bp.route("/metatrader", methods=["GET", "POST"])
@login_required
def metatrader():
    """Direct users to the MT4/MT5 broker connection interface."""
    return redirect(url_for("mobile.connect_broker"))


@mobile_bp.route("/history")
@login_required
def history():
    """Mobile trade history page"""
    from ..models import Trade

    filter_type = request.args.get("filter", "all")
    query = Trade.query.filter_by(user_id=current_user.id)

    if filter_type == "open":
        query = query.filter_by(status="open")
    elif filter_type == "closed":
        query = query.filter_by(status="closed")
    elif filter_type == "profit":
        query = query.filter(Trade.profit_loss >= 0, Trade.status == "closed")
    elif filter_type == "loss":
        query = query.filter(Trade.profit_loss < 0, Trade.status == "closed")

    trades = query.order_by(Trade.opened_at.desc()).all()

    closed_trades = Trade.query.filter_by(user_id=current_user.id, status="closed").all()
    total_trades = len(closed_trades)
    total_profit = sum(t.profit_loss for t in closed_trades)
    winning_trades = len([t for t in closed_trades if t.profit_loss >= 0])
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

    return render_template(
        "mobile_history.html",
        trades=trades,
        filter=filter_type,
        total_trades=total_trades,
        total_profit=total_profit,
        win_rate=round(win_rate, 1),
        active_page="history",
    )


@mobile_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    """Mobile profile and settings page"""
    from ..extensions import db
    from ..models import License

    if request.method == "POST":
        if request.form.get("become_mentor"):
            try:
                from ..mentor_system import register_as_mentor

                mentor_id = register_as_mentor(current_user.id)
                flash(f"You are now a mentor! Your ID is: {mentor_id}", "success")
            except Exception:
                current_app.logger.exception("Failed to register mentor for user %s", current_user.id)
                flash("Could not register as mentor at this time. Please try again later.", "error")
        else:
            current_user.email_notifications = "email_notifications" in request.form
            current_user.trade_alerts = "trade_alerts" in request.form
            current_user.signal_alerts = "signal_alerts" in request.form
            db.session.commit()
            flash("Settings saved!", "success")

        return redirect(url_for("mobile.profile"))

    license_obj = License.query.filter_by(user_id=current_user.id, status="active").first()
    from ..models import BrokerAccount

    broker_account = BrokerAccount.query.filter_by(user_id=current_user.id).first()

    mentor_stats = None
    if current_user.is_mentor:
        try:
            from ..mentor_system import get_mentor_stats

            mentor_stats = get_mentor_stats(current_user.id)
        except Exception:
            current_app.logger.exception("Failed to fetch mentor stats for user %s", current_user.id)

    return render_template(
        "mobile_profile.html",
        license=license_obj,
        mentor_stats=mentor_stats,
        broker_account=broker_account,
        active_page="profile",
    )


@mobile_bp.route("/connect-broker", methods=["GET", "POST"])
@login_required
def connect_broker():
    """Connect or update MT4/MT5 broker account credentials."""
    from ..extensions import db
    from ..models import BrokerAccount, utcnow
    from ..services.broker_bridge import (
        BrokerConnectionError,
        BrokerValidationError,
        encrypt_broker_password,
        verify_and_connect,
    )

    broker_account = BrokerAccount.query.filter_by(user_id=current_user.id).first()

    if request.method == "POST":
        action = request.form.get("action")
        if action == "disconnect":
            if broker_account:
                broker_account.is_connected = False
                db.session.commit()
                flash("Broker account disconnected successfully.", "info")
            return redirect(url_for("mobile.connect_broker"))

        # Thoroughly strip all leading and trailing whitespace from input credentials
        platform = str(request.form.get("platform", "MT5") or "").strip().upper()
        server = str(request.form.get("server", "") or "").strip()
        login = str(request.form.get("login", "") or "").strip()
        password = str(request.form.get("password", "") or "").strip()

        if platform not in {"MT4", "MT5"}:
            flash("Please select MetaTrader 4 (MT4) or MetaTrader 5 (MT5).", "error")
            return render_template("mobile_connect_broker.html", broker_account=broker_account, active_page="profile")

        if not server or len(server) < 3:
            flash("Please enter a valid broker server name (e.g. IFXBrokersHoldings-Demo, Deriv-Server).", "error")
            return render_template("mobile_connect_broker.html", broker_account=broker_account, active_page="profile")

        if not login or not login.isdigit():
            flash(f"Invalid account login ID '{login}'. Account ID must contain only numeric digits.", "error")
            return render_template("mobile_connect_broker.html", broker_account=broker_account, active_page="profile")

        if not password or len(password) < 3:
            flash("Please enter your broker account password (minimum 3 characters).", "error")
            return render_template("mobile_connect_broker.html", broker_account=broker_account, active_page="profile")

        try:
            verify_and_connect(platform=platform, server=server, login=login, password=password)
        except BrokerValidationError as exc:
            current_app.logger.warning("Broker validation failed for user %s: %s", current_user.id, exc)
            flash(f"Broker Validation Error: {exc}", "error")
            return render_template("mobile_connect_broker.html", broker_account=broker_account, active_page="profile")
        except BrokerConnectionError as exc:
            current_app.logger.warning("Broker authentication rejected for user %s on %s: %s", current_user.id, server, exc)
            flash(f"Broker Authentication Failed: {exc}", "error")
            return render_template("mobile_connect_broker.html", broker_account=broker_account, active_page="profile")
        except Exception as exc:
            current_app.logger.exception("Diagnostic connection failure for user %s on %s", current_user.id, server)
            flash(f"Connection Diagnostic Error: {exc}", "error")
            return render_template("mobile_connect_broker.html", broker_account=broker_account, active_page="profile")

        if not broker_account:
            broker_account = BrokerAccount(user_id=current_user.id)
            db.session.add(broker_account)

        broker_account.platform = platform
        broker_account.server = server
        broker_account.account_login = login
        broker_account.encrypted_password = encrypt_broker_password(password)
        broker_account.is_connected = True
        broker_account.last_synced_at = utcnow()
        db.session.commit()

        flash(
            f"Successfully connected to {server} ({platform})! Automated robot signals will execute on your account.",
            "success",
        )
        return redirect(url_for("mobile.profile"))

    return render_template("mobile_connect_broker.html", broker_account=broker_account, active_page="profile")


@mobile_bp.route("/api/broker/test-trade", methods=["POST"])
@login_required
def api_broker_test_trade():
    """Execute a verification test ping trade on connected Deriv or IFX Brokers account."""
    from ..services.broker_bridge import (
        BrokerError,
        dispatch_test_ping_trade,
    )

    try:
        result = dispatch_test_ping_trade(current_user.id)
        return jsonify(result), 200
    except BrokerError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception:
        current_app.logger.exception("Unexpected error executing broker test trade for user %s", current_user.id)
        return jsonify({"success": False, "error": "Internal broker bridge execution error."}), 500


@mobile_bp.route("/notifications", methods=["GET", "POST"])
@login_required
def notifications():
    """Mobile notifications page"""
    if request.method == "POST":
        action = request.form.get("action")

        if action == "mark_read":
            notification_id_str = request.form.get("notification_id", "")
            if notification_id_str:
                try:
                    from ..notifications import mark_as_read

                    mark_as_read(int(notification_id_str), current_user.id)
                except Exception:
                    current_app.logger.exception(
                        "Failed to mark notification %s read for user %s", notification_id_str, current_user.id
                    )

        elif action == "mark_all_read":
            try:
                from ..notifications import mark_all_as_read

                mark_all_as_read(current_user.id)
                flash("All notifications marked as read", "success")
            except Exception:
                current_app.logger.exception("Failed to mark all notifications read for user %s", current_user.id)
                flash("Could not mark all notifications as read", "error")

        return redirect(url_for("mobile.notifications"))

    try:
        from ..notifications import get_unread_count, get_user_notifications

        user_notifications = get_user_notifications(current_user.id, limit=50)
        unread_count = get_unread_count(current_user.id)
    except Exception:
        current_app.logger.exception("Failed to retrieve notifications for user %s", current_user.id)
        user_notifications = []
        unread_count = 0

    return render_template(
        "mobile_notifications.html",
        notifications=user_notifications,
        unread_count=unread_count,
        active_page="notifications",
    )
