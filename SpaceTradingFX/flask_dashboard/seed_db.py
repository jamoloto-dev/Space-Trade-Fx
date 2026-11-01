"""Automatic database seeder for SpaceTradingFX.

Ensures the administrator account, active professional license, broker credentials,
and trading preferences exist and are up to date on application startup.
Runs idempotently after Alembic database migrations.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] [seeder] %(message)s")
logger = logging.getLogger("seed_db")


def seed_database(app=None) -> None:
    # Avoid import-time database connection before app context
    try:
        from . import create_app
        from .extensions import db
        from .models import BrokerAccount, License, TradingPreference, User, utcnow
        from .services.broker_bridge import encrypt_broker_password
    except ImportError:
        # Fallback when executed as top-level script
        from SpaceTradingFX.flask_dashboard import create_app
        from SpaceTradingFX.flask_dashboard.extensions import db
        from SpaceTradingFX.flask_dashboard.models import BrokerAccount, License, TradingPreference, User, utcnow
        from SpaceTradingFX.flask_dashboard.services.broker_bridge import encrypt_broker_password

    admin_email = os.environ.get("ADMIN_EMAIL", "molotojafta30@gmail.com").strip().lower()
    admin_password = os.environ.get("ADMIN_PASSWORD", "Javalaava301%").strip()
    admin_first_name = os.environ.get("ADMIN_FIRST_NAME", "Jafta").strip()
    admin_last_name = os.environ.get("ADMIN_LAST_NAME", "Moloto").strip()
    primary_license_key = os.environ.get("ADMIN_LICENSE_KEY", "Y685-IK4P-99MY").strip().upper()
    secondary_license_key = os.environ.get("ADMIN_SECONDARY_LICENSE_KEY", "STL4-Q4VN-2964").strip().upper()

    mt5_login = os.environ.get("MT5_ACCOUNT_LOGIN", "1861949").strip()
    mt5_server = os.environ.get("MT5_SERVER", "IFXBrokers-Real").strip()
    mt5_password = os.environ.get("MT5_PASSWORD", "Javalava30%").strip()

    if app is None:
        app = create_app()
    with app.app_context():
        logger.info("Checking database state for administrator: %s", admin_email)

        # 1. Seed / verify Administrator User
        user = User.query.filter_by(email=admin_email).first()

        # Determine mentor ID safely without violating unique constraint
        mentor_id = None
        if user and user.mentor_id:
            mentor_id = user.mentor_id
        else:
            if not User.query.filter_by(mentor_id="326").first():
                mentor_id = "326"

        if user is None:
            user = User(
                id=str(uuid4()),
                email=admin_email,
                first_name=admin_first_name,
                last_name=admin_last_name,
                is_admin=True,
                has_unlimited_premium=True,
                mentor_id=mentor_id,
                is_mentor=True if mentor_id else False,
                email_notifications=True,
                trade_alerts=True,
                signal_alerts=True,
            )
            user.set_password(admin_password)
            db.session.add(user)
            db.session.flush()
            logger.info("Created new admin user: %s (id: %s)", admin_email, user.id)
        else:
            user.set_password(admin_password)
            user.is_admin = True
            user.has_unlimited_premium = True
            if not user.first_name:
                user.first_name = admin_first_name
            if not user.last_name:
                user.last_name = admin_last_name
            if not user.mentor_id and mentor_id:
                user.mentor_id = mentor_id
                user.is_mentor = True
            db.session.flush()
            logger.info("Updated password and permissions for existing admin user: %s (id: %s)", admin_email, user.id)

        # 2. Seed / verify Active Professional License(s)
        # Ensure at least 1 year validity from current execution
        valid_until = utcnow() + timedelta(days=365)
        prof_features = {
            "features": [
                "advanced_signals",
                "paper_trading",
                "email_alerts",
                "priority_support",
                "custom_strategies",
            ],
            "provisioning_source": "startup_seeder",
        }

        for lic_key in [primary_license_key, secondary_license_key]:
            if not lic_key:
                continue
            lic = License.query.filter_by(license_key=lic_key).first()
            if lic is None:
                lic = License(
                    user_id=user.id,
                    license_key=lic_key,
                    license_type="professional",
                    status="active",
                    issued_at=utcnow(),
                    expires_at=valid_until,
                    max_active_trades=50,
                    features=prof_features,
                )
                db.session.add(lic)
                logger.info(
                    "Provisioned active Professional License: %s (expires: %s)", lic_key, valid_until.isoformat()
                )
            else:
                lic.user_id = user.id
                lic.license_type = "professional"
                lic.status = "active"
                lic.expires_at = valid_until
                lic.max_active_trades = 50
                lic.features = prof_features
                logger.info("Refreshed active Professional License: %s (expires: %s)", lic_key, valid_until.isoformat())

        # 3. Seed / verify Trading Preferences
        prefs = TradingPreference.query.filter_by(user_id=user.id).first()
        if prefs is None:
            prefs = TradingPreference(
                user_id=user.id,
                currency_pairs=["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "USDZAR"],
                timeframe="5M",
                risk_percentage=Decimal("1.00"),
                max_concurrent_trades=3,
                trading_enabled=False,
                strategy_settings={
                    "auto_pilot": False,
                    "scalping_mode": True,
                    "automated_paper_trading": True,
                    "trading_mode": "scalping",
                    "lot_sizes": {"EURUSD": "0.0210", "GBPUSD": "0.0210", "USDJPY": "0.0210"},
                    "automated_broker_trading": False,
                    "min_confidence": 65,
                },
                direction_preferences={"EURUSD": "BOTH", "GBPUSD": "BOTH", "USDJPY": "BOTH"},
            )
            db.session.add(prefs)
            logger.info("Created default trading preferences for user: %s", user.id)

        # 4. Seed / verify MT5 Broker Account
        if mt5_login and mt5_server:
            broker_acct = BrokerAccount.query.filter_by(user_id=user.id).first()
            encrypted_pw = encrypt_broker_password(mt5_password)
            if broker_acct is None:
                broker_acct = BrokerAccount(
                    user_id=user.id,
                    platform="MT5",
                    server=mt5_server,
                    account_login=mt5_login,
                    encrypted_password=encrypted_pw,
                    is_connected=True,
                    currency="USD",
                    balance=Decimal("0.01"),
                    equity=Decimal("0.01"),
                    free_margin=Decimal("0.01"),
                )
                db.session.add(broker_acct)
                logger.info("Created MT5 broker account connection for login %s (%s)", mt5_login, mt5_server)
            else:
                broker_acct.platform = "MT5"
                broker_acct.server = mt5_server
                broker_acct.account_login = mt5_login
                broker_acct.encrypted_password = encrypted_pw
                broker_acct.is_connected = True
                logger.info("Updated MT5 broker account connection for login %s (%s)", mt5_login, mt5_server)

        db.session.commit()
        logger.info("Database seeding successfully completed for admin %s.", admin_email)


def main() -> None:
    try:
        seed_database()
    except Exception as exc:
        logger.exception("Failed to seed database: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
