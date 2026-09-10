#!/usr/bin/env python3
"""Management script for admin user operations.

Usage:
  python manage_admin.py set-password --email EMAIL --password PASSWORD
"""
import argparse
import os
import sys

from .app import app
from .extensions import db
from .models import User


def set_password(email, password):
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        if not user:
            print("User not found; creating new user")
            user = User()
            user.id = f"cli-{email}"
            user.email = email
            user.first_name = os.environ.get('DEFAULT_ADMIN_FIRST', 'Jafta')
            user.last_name = os.environ.get('DEFAULT_ADMIN_LAST', 'Moloto')
            user.is_admin = True
            db.session.add(user)
        user.set_password(password)
        user.is_admin = True
        db.session.commit()
        print(f"Password set for {email}")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='cmd')
    p_set = sub.add_parser('set-password')
    p_set.add_argument('--email', required=True)
    p_set.add_argument('--password', required=True)

    args = parser.parse_args()
    if args.cmd == 'set-password':
        set_password(args.email, args.password)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
