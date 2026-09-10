"""Explicit, interactive administrator bootstrap command.

Run only after the database migration has been applied:
    python -m SpaceTradingFX.flask_dashboard.bootstrap_admin admin@example.com
"""

from __future__ import annotations

import argparse
import getpass
from uuid import uuid4

from . import create_app
from .extensions import db
from .models import User


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or promote one SpaceTradingFX administrator.")
    parser.add_argument("email")
    args = parser.parse_args()
    email = args.email.strip().lower()
    password = getpass.getpass("Administrator password: ")
    confirmation = getpass.getpass("Confirm administrator password: ")
    if len(password) < 12 or password != confirmation:
        raise SystemExit("Passwords must match and contain at least 12 characters.")

    app = create_app()
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        if user is None:
            user = User(id=str(uuid4()), email=email, first_name="Administrator")
            db.session.add(user)
        user.set_password(password)
        user.is_admin = True
        db.session.commit()

    print(f"Administrator bootstrap completed for {email}.")


if __name__ == "__main__":
    main()
