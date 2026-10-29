"""
SpaceTradingFX Blueprints Module
Organizes routes into logical groups
"""

# Import blueprints
from .mobile import mobile_bp
from .secure_auth import auth_bp
from .strategy_adaptation import strategy_bp
from .trading import trading_bp

# List of all blueprints for registration
ALL_BLUEPRINTS = [
    (auth_bp, {}),
    (mobile_bp, {"url_prefix": "/m"}),
    (trading_bp, {}),
    (strategy_bp, {}),
]


def register_blueprints(app):
    """Register all blueprints with the Flask app"""
    for blueprint, options in ALL_BLUEPRINTS:
        app.register_blueprint(blueprint, **options)


__all__ = [
    "auth_bp",
    "mobile_bp",
    "strategy_bp",
    "trading_bp",
    "register_blueprints",
    "ALL_BLUEPRINTS",
]
