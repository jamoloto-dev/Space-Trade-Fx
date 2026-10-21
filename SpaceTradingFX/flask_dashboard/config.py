"""
SpaceTradingFX Configuration Classes
Provides environment-specific configurations
"""

import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "trading.db")


class Config:
    """Base configuration"""

    # Security
    SECRET_KEY = os.environ.get("SESSION_SECRET") or os.environ.get("SECRET_KEY")
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600  # 1 hour

    # Session
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_DURATION = timedelta(days=14)

    # Database
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }

    # Rate Limiting
    RATELIMIT_ENABLED = True
    RATELIMIT_STORAGE_URI = os.environ.get("REDIS_URL", "memory://")
    RATELIMIT_STRATEGY = "fixed-window"
    RATELIMIT_DEFAULT = "200 per day, 50 per hour"
    RATELIMIT_HEADERS_ENABLED = True

    # License System
    LICENSE_MAX_ACTIVATIONS = int(os.environ.get("LICENSE_MAX_ACTIVATIONS", "3"))

    # Feature Flags
    ENABLE_GPT5_FOR_ALL_CLIENTS = os.environ.get("ENABLE_GPT5_FOR_ALL_CLIENTS", "true").lower() in ("1", "true", "yes")

    # Broker Execution & Trading Safety
    PAPER_TRADING_ONLY = False
    LIVE_TRADING_ENABLED = True
    MT5_ORDER_EXECUTION_ENABLED = True
    TRADING_KILL_SWITCH = os.environ.get("TRADING_KILL_SWITCH", "false").lower() in ("1", "true", "yes")
    PAPER_TRADING_KILL_SWITCH = TRADING_KILL_SWITCH
    PAPER_WORKER_ENABLED = False
    MARKET_DATA_PROVIDER = os.environ.get("MARKET_DATA_PROVIDER", "simulation").lower()
    MARKET_DATA_MAX_STALENESS = int(os.environ.get("MARKET_DATA_MAX_STALENESS", "86400"))
    STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
    STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
    STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

    # Email
    SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_USER = os.environ.get("SMTP_USER", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    FROM_EMAIL = os.environ.get("FROM_EMAIL", "noreply@spacetradingfx.com")

    @staticmethod
    def validate():
        """Validate configuration on startup"""
        errors = []

        if not Config.SECRET_KEY:
            errors.append("SESSION_SECRET or SECRET_KEY environment variable is required")

        return errors


class DevelopmentConfig(Config):
    """Development configuration"""

    DEBUG = True

    # Security - relaxed for development
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    WTF_CSRF_ENABLED = True  # Keep CSRF even in dev

    # Use a default secret key for development only
    SECRET_KEY = os.environ.get("SESSION_SECRET") or "dev-secret-key-change-in-production"

    # Rate limiting - more lenient in dev
    RATELIMIT_DEFAULT = "1000 per day, 200 per hour"

    @staticmethod
    def validate():
        """Development config is more permissive"""
        return []  # No required vars in dev


class ProductionConfig(Config):
    """Production configuration"""

    DEBUG = False

    # Security - strict for production
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True

    # Require HTTPS
    PREFERRED_URL_SCHEME = "https"

    # Stricter rate limiting
    RATELIMIT_DEFAULT = "200 per day, 50 per hour"

    @staticmethod
    def validate():
        """Production requires certain environment variables"""
        errors = []

        if not os.environ.get("SESSION_SECRET") and not os.environ.get("SECRET_KEY"):
            errors.append("SESSION_SECRET environment variable is required in production")

        if not os.environ.get("DATABASE_URL"):
            errors.append("DATABASE_URL environment variable is required in production")

        if os.environ.get("STRIPE_SECRET_KEY") and not os.environ.get("STRIPE_WEBHOOK_SECRET"):
            errors.append("STRIPE_WEBHOOK_SECRET is required when Stripe payments are enabled")

        if not os.environ.get("LICENSE_PUBLIC_KEY_PEM") or not os.environ.get("LICENSE_PRIVATE_KEY_PEM"):
            errors.append("LICENSE_PUBLIC_KEY_PEM and LICENSE_PRIVATE_KEY_PEM are required in production")

        return errors


class TestingConfig(Config):
    """Testing configuration"""

    TESTING = True
    DEBUG = True

    # Use in-memory SQLite for tests
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"

    # Disable CSRF for testing (easier form submissions)
    WTF_CSRF_ENABLED = False

    # Disable rate limiting in tests
    RATELIMIT_ENABLED = False
    SESSION_COOKIE_SECURE = False

    # Use a fixed secret key
    SECRET_KEY = "test-secret-key-for-testing-only"

    @staticmethod
    def validate():
        return []


# Configuration mapping
config = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}


def get_config():
    """Get configuration based on environment"""
    env = os.environ.get("FLASK_ENV", "development").lower()
    return config.get(env, config["default"])
