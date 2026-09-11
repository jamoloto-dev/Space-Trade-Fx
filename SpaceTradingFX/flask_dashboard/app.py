"""Compatibility imports for callers migrating to ``flask_dashboard:create_app``.

This module deliberately does not instantiate a Flask application at import
time. Gunicorn, the CLI and tests invoke the same factory.
"""

from . import create_app
from .extensions import csrf, db, limiter, login_manager

__all__ = ["create_app", "csrf", "db", "limiter", "login_manager"]
