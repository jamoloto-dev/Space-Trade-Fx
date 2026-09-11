"""
Mobile Blueprint
Handles all mobile-optimized routes (/m/*)
"""

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

mobile_bp = Blueprint("mobile", __name__)

# Default lot sizes for symbols
DEFAULT_LOT_SIZES = {
    "EURUSD": 0.02,
    "GBPUSD": 0.01,
    "XAUUSD": 0.01,
    "USDJPY": 0.02,
    "AUDUSD": 0.01,
    "USDCAD": 0.01,
    "USDCHF": 0.01,
    "NZDUSD": 0.01,
}


@mobile_bp.route("/")
@mobile_bp.route("/home")
@login_required
def home():
    """Mobile Home Screen - EA Connection Status"""
    from ..license_manager import check_license_valid
    from ..models import TradingPreference
    from ..trading_engine import TradingEngine

    is_valid, license_info = check_license_valid(current_user.id)
    engine = TradingEngine(current_user.id)
    account_summary = engine.get_account_summary()
    preferences = TradingPreference.query.filter_by(user_id=current_user.id).first()

    return render_template(
        "mobile_home.html",
        user=current_user,
        has_license=is_valid,
        license=license_info if is_valid else None,
        account_summary=account_summary,
        preferences=preferences,
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

    available_pairs = ["EURUSD", "GBPUSD", "XAUUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD"]

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
                    lot_sizes[pair] = float(lot_size)
                except ValueError:
                    lot_sizes[pair] = DEFAULT_LOT_SIZES.get(pair, 0.01)

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

    for pair in available_pairs:
        symbols.append(
            {
                "pair": pair,
                "enabled": pair in (preferences.currency_pairs or []),
                "lot_size": lot_sizes.get(pair, DEFAULT_LOT_SIZES.get(pair, 0.01)),
                "direction": direction_prefs.get(pair, "BOTH"),
                "platform": "PAPER",
            }
        )

    return render_template(
        "mobile_quotes.html", symbols=symbols, trading_enabled=preferences.trading_enabled, active_page="quotes"
    )


@mobile_bp.route("/metatrader", methods=["GET", "POST"])
@login_required
def metatrader():
    """Paper-trading status screen; broker accounts cannot be linked."""
    from ..extensions import db
    from ..models import TradingPreference

    platform = request.args.get("platform", "mt5")

    preferences = TradingPreference.query.filter_by(user_id=current_user.id).first()
    if not preferences:
        preferences = TradingPreference()  # type: ignore
        preferences.user_id = current_user.id
        db.session.add(preferences)
        db.session.commit()

    if request.method == "POST":
        flash("Broker account linking is unavailable while Paper Trading is enabled.", "info")
        return redirect(url_for("mobile.metatrader"))

    return render_template(
        "mobile_metatrader.html",
        preferences=preferences,
        platform=platform,
        is_connected=False,
        common_servers=[],
        active_page="metatrader",
    )


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

    mentor_stats = None
    if current_user.is_mentor:
        try:
            from ..mentor_system import get_mentor_stats

            mentor_stats = get_mentor_stats(current_user.id)
        except Exception:
            current_app.logger.exception("Failed to fetch mentor stats for user %s", current_user.id)

    return render_template("mobile_profile.html", license=license_obj, mentor_stats=mentor_stats, active_page="profile")


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
