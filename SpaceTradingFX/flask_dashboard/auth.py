"""Deprecated compatibility import for the password-auth blueprint.

The former OIDC demo authenticated unsigned token contents and registered
routes through import side effects.  It has been retired; application setup
registers :mod:`blueprints.secure_auth` explicitly in the factory.
"""

from .blueprints.secure_auth import auth_bp

__all__ = ["auth_bp"]
