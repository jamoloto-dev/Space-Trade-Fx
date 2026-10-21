"""Flask extensions shared by the application factory and domain modules."""

from flask import current_app, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager, current_user
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""


db = SQLAlchemy(model_class=Base)
csrf = CSRFProtect()
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["10000 per day", "2000 per hour"],
    storage_uri="memory://",
)
login_manager = LoginManager()


@limiter.request_filter
def ip_and_user_whitelist() -> bool:
    """Exempt localhost, test client, and authenticated trading sessions from rate limits."""
    try:
        if current_app.config.get("TESTING"):
            return True
        client_ip = request.remote_addr or ""
        if client_ip in ("127.0.0.1", "::1", "localhost") or client_ip.startswith("127."):
            return True
        if current_user and current_user.is_authenticated:
            # Exempt all mobile pages and broker/market API calls for authenticated users
            if request.path.startswith(("/m/", "/api/", "/trading/")):
                return True
    except Exception:
        pass
    return False
