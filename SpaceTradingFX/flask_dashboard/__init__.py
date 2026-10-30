"""SpaceTradingFX Flask application factory."""

from __future__ import annotations

import logging
import os
from typing import Mapping

from flask import Flask, jsonify
from sqlalchemy import text
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import get_config
from .extensions import csrf, db, limiter, login_manager

logger = logging.getLogger(__name__)


def create_app(config_override: Mapping[str, object] | None = None) -> Flask:
    """Create one explicitly configured SpaceTradingFX web application."""
    app = Flask(__name__)
    config_class = get_config()

    errors = config_class.validate()
    if errors and not (config_override and config_override.get("TESTING")):
        raise RuntimeError("Invalid application configuration: " + "; ".join(errors))

    app.config.from_object(config_class)
    if config_override:
        app.config.update(config_override)

    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = os.environ.get("SESSION_SECRET") or os.environ.get("SECRET_KEY")

    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)  # type: ignore[method-assign]
    app.logger.setLevel(logging.DEBUG if app.config.get("DEBUG") else logging.INFO)
    db.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to access this page."

    # Import all models to ensure complete SQLAlchemy metadata registration
    from . import models  # noqa: F401
    from .models import BrokerAccount, User  # noqa: F401

    @login_manager.user_loader
    def load_user(user_id: str | None) -> User | None:
        try:
            if not user_id:
                return None
            return db.session.get(User, str(user_id))
        except Exception as e:
            logger.error(f"Error loading user {user_id}: {e}")
            return None

    # Defensive provisioning: Ensure all registered tables (including broker_accounts) exist
    with app.app_context():
        try:
            db.create_all()
        except Exception as exc:
            app.logger.warning("Defensive db.create_all() hook encountered error: %s", exc)

    _register_blueprints(app)
    _register_health_endpoints(app)

    # Start non-blocking autonomous trading scheduler and unified SpaceTradeWorker in live runtime
    if not app.config.get("TESTING") and (not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true"):
        from .services.autonomous_scanner import start_autonomous_scheduler
        from .services.trade_worker import start_space_trade_worker_daemon

        start_autonomous_scheduler(app)
        start_space_trade_worker_daemon(app=app, interval_seconds=int(os.environ.get("TRADE_WORKER_INTERVAL", "30")))

    return app


def _register_blueprints(app: Flask) -> None:
    """Register every HTTP surface exactly once and in one visible location."""
    from .activation_api import bp as activation_bp
    from .admin import bp as admin_bp
    from .blueprints.mobile import mobile_bp
    from .blueprints.secure_auth import auth_bp
    from .blueprints.strategy_adaptation import strategy_bp
    from .blueprints.trading import trading_bp
    from .payments import bp as payments_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(mobile_bp, url_prefix="/m")
    app.register_blueprint(trading_bp)
    app.register_blueprint(strategy_bp)
    app.register_blueprint(activation_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(admin_bp)


def _register_health_endpoints(app: Flask) -> None:
    @app.get("/health/live")
    @limiter.exempt
    def health_live():
        return jsonify({"status": "ok"})

    @app.get("/health/ready")
    @limiter.exempt
    def health_ready():
        try:
            db.session.execute(text("SELECT 1"))
        except Exception:
            app.logger.exception("Readiness database check failed")
            return jsonify({"status": "not_ready"}), 503
        return jsonify({"status": "ready"})

    @app.get("/health/paper-worker")
    @limiter.exempt
    def health_paper_worker():
        """Report a worker lease without starting or controlling a worker."""
        from .models import PaperWorkerLease, utcnow

        lease = db.session.get(PaperWorkerLease, "paper-lifecycle")
        expires_at = (
            lease.expires_at.replace(tzinfo=utcnow().tzinfo)
            if lease and lease.expires_at.tzinfo is None
            else (lease.expires_at if lease else None)
        )
        if lease and expires_at > utcnow():
            payload = {
                "status": "degraded" if lease.last_error else "running",
                "execution_mode": "paper",
                "last_cycle_at": lease.last_cycle_at.isoformat() if lease.last_cycle_at else None,
                "last_success_at": lease.last_success_at.isoformat() if lease.last_success_at else None,
            }
            return jsonify(payload), (503 if lease.last_error else 200)
        return jsonify({"status": "not_running", "execution_mode": "paper"}), 503
