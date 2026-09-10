"""
SpaceTradingFX API Module
Aggregates all API blueprints and routes
"""

# This module organizes all API-related blueprints
# Blueprints are registered in the main app

# Import blueprints
from ..activation_api import bp as activation_bp
from ..payments import bp as payments_bp
from ..admin import bp as admin_bp

# List of all API blueprints for easy registration
API_BLUEPRINTS = [
    activation_bp,
    payments_bp,
    admin_bp,
]

__all__ = [
    'activation_bp',
    'payments_bp', 
    'admin_bp',
    'API_BLUEPRINTS',
]
