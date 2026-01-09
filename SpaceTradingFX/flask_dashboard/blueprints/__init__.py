"""
SpaceTradingFX Blueprints Module
Organizes routes into logical groups
"""

from flask import Blueprint

# Import blueprints
from .auth import auth_bp
from .mobile import mobile_bp
from .trading import trading_bp

# List of all blueprints for registration
ALL_BLUEPRINTS = [
    (auth_bp, {}),
    (mobile_bp, {'url_prefix': '/m'}),
    (trading_bp, {}),
]


def register_blueprints(app):
    """Register all blueprints with the Flask app"""
    for blueprint, options in ALL_BLUEPRINTS:
        app.register_blueprint(blueprint, **options)


__all__ = [
    'auth_bp',
    'mobile_bp',
    'trading_bp',
    'register_blueprints',
    'ALL_BLUEPRINTS',
]
