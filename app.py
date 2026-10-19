"""SpaceTradingFX Application Entrypoint & CLI Module."""

from __future__ import annotations

from flask_dashboard import create_app
from flask_dashboard.extensions import db

app = create_app()
app.app_context().push()

__all__ = ["app", "create_app", "db"]

if __name__ == "__main__":
    app.run()
