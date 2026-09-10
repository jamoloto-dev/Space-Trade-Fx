"""Compatibility WSGI module for ``flask_dashboard.app:app``."""

from . import create_app
from .extensions import csrf, db, limiter, login_manager

app = create_app()

__all__ = ["app", "csrf", "db", "limiter", "login_manager"]
