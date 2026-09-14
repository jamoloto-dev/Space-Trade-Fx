"""SpaceTradingFX Flask application factory."""

from __future__ import annotations

import logging
from typing import Mapping

from flask import Flask, jsonify
from sqlalchemy import text
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import get_config
from .extensions import csrf, db, limiter, login_manager


def create_app(config_override: Mapping[str, object] | None = None) -> Flask:
    """Create one explicitly configured SpaceTradingFX web application."""
    app = Flask(__name__)
    config_class = get_config()
    app.config.from_object(config_class)
    if config_override:
        app.config.update(config_override)

    errors = config_class.validate()
    if errors and not app.config.get("TESTING"):
        raise RuntimeError("Invalid application configuration: " + "; ".join(errors))

    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)  # type: ignore[method-assign]
    app.logger.setLevel(logging.DEBUG if app.config.get("DEBUG") else logging.INFO)
    db.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to access this page."

    from .models import User

    @login_manager.user_loader
    def load_user(user_id: str) -> User | None:
        return db.session.get(User, user_id)

    _register_blueprints(app)
    _register_health_endpoints(app)
    return app


def _register_blueprints(app: Flask) -> None:
    """Register every HTTP surface exactly once and in one visible location."""
    from .activation_api import bp as activation_bp
    from .admin import bp as admin_bp
    from .blueprints.mobile import mobile_bp
    from .blueprints.secure_auth import auth_bp
    from .blueprints.trading import trading_bp
    from .payments import bp as payments_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(mobile_bp, url_prefix="/m")
    app.register_blueprint(trading_bp)
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
