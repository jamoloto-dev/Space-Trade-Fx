from datetime import datetime, timezone

from flask_dance.consumer.storage.sqla import OAuthConsumerMixin
from flask_login import UserMixin
from sqlalchemy import CheckConstraint, Numeric, UniqueConstraint
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


# User model (mandatory for Replit Auth)
def utcnow() -> datetime:
    """Return an aware UTC value for every new persisted timestamp."""
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.String, primary_key=True)
    email = db.Column(db.String, unique=True, nullable=False)
    first_name = db.Column(db.String, nullable=True)
    last_name = db.Column(db.String, nullable=True)
    profile_image_url = db.Column(db.String, nullable=True)
    password_hash = db.Column(db.String, nullable=True)
    is_admin = db.Column(db.Boolean, default=False)
    has_unlimited_premium = db.Column(db.Boolean, default=False)
    # Mentor/Referral fields
    mentor_id = db.Column(db.String(3), unique=True, nullable=True)  # 3-digit mentor ID
    is_mentor = db.Column(db.Boolean, default=False)
    referred_by_mentor_id = db.Column(db.String(3), nullable=True)  # Who referred this user
    total_referrals = db.Column(db.Integer, default=0)
    total_commission = db.Column(Numeric(18, 2), default=0, nullable=False)
    # Notification preferences
    email_notifications = db.Column(db.Boolean, default=True)
    trade_alerts = db.Column(db.Boolean, default=True)
    signal_alerts = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    # Relationships
    licenses = db.relationship("License", backref="user", lazy=True)
    trading_preferences = db.relationship("TradingPreference", backref="user", uselist=False, lazy=True)
    trades = db.relationship("Trade", backref="user", lazy=True)
    notifications = db.relationship("Notification", backref="user", lazy=True)
    broker_account = db.relationship(
        "BrokerAccount", backref="user", uselist=False, lazy=True, cascade="all, delete-orphan"
    )

    def set_password(self, password: str):
        if password is None:
            self.password_hash = None
            return
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)


# OAuth model (mandatory for Replit Auth)
class OAuth(OAuthConsumerMixin, db.Model):
    user_id = db.Column(db.String, db.ForeignKey(User.id))
    browser_session_key = db.Column(db.String, nullable=False)
    user = db.relationship(User)

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "browser_session_key",
            "provider",
            name="uq_user_browser_session_key_provider",
        ),
    )


# License model for managing user subscriptions
class License(db.Model):
    __tablename__ = "licenses"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'active', 'expired', 'revoked')", name="ck_licenses_status"),
        db.Index("idx_licenses_user_status", "user_id", "status"),
        db.Index("idx_licenses_expires", "expires_at"),
        db.Index("idx_licenses_key", "license_key"),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=False)
    license_key = db.Column(db.String(500), unique=True, nullable=False)
    license_type = db.Column(db.String(50), nullable=False)  # 'basic', 'premium', 'professional'
    status = db.Column(db.String(20), default="pending")  # 'pending', 'active', 'expired', 'revoked'
    issued_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=True)
    stripe_payment_id = db.Column(db.String(255), unique=True, nullable=True)
    max_active_trades = db.Column(db.Integer, default=3)
    features = db.Column(db.JSON, default=dict)  # Store additional features as JSON
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    # Activation relationship (populated after EA/user binds account/server)
    activations = db.relationship("Activation", backref="license", lazy=True)


# Trading preferences for each user
class TradingPreference(db.Model):
    __tablename__ = "trading_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_trading_preferences_user"),
        CheckConstraint("risk_percentage > 0 AND risk_percentage <= 2", name="ck_trading_preferences_risk"),
        CheckConstraint(
            "max_concurrent_trades >= 1 AND max_concurrent_trades <= 20", name="ck_trading_preferences_trade_limit"
        ),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=False)
    currency_pairs = db.Column(db.JSON, default=list)  # ['EURUSD', 'GBPUSD', etc.]
    timeframe = db.Column(db.String(10), default="1H")  # '1M', '5M', '15M', '1H', '4H', 'D'
    risk_percentage = db.Column(Numeric(5, 2), default=1, nullable=False)  # Risk per paper trade as % of account
    max_concurrent_trades = db.Column(db.Integer, default=3)
    trading_enabled = db.Column(db.Boolean, default=False)
    mt5_account = db.Column(db.String(100), nullable=True)
    mt5_server = db.Column(db.String(100), nullable=True)
    strategy_settings = db.Column(db.JSON, default=dict)  # Store strategy parameters
    # Per-currency direction preferences: { 'EURUSD': 'BOTH'|'BUY'|'SELL' }
    direction_preferences = db.Column(db.JSON, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


# Trade history and active trades
class Trade(db.Model):
    __tablename__ = "trades"
    __table_args__ = (
        # Idempotency belongs to a caller's ledger, not the whole product. A
        # client retry key from one account must not reject another account's
        # otherwise valid order.
        UniqueConstraint("user_id", "idempotency_key", name="uq_trades_user_idempotency_key"),
        UniqueConstraint("broker_order_id", name="uq_trades_broker_order_id"),
        CheckConstraint(
            "status IN ('draft', 'validated', 'open', 'closing', 'closed', 'rejected', 'failed')",
            name="ck_trades_status",
        ),
        CheckConstraint("trade_type IN ('BUY', 'SELL')", name="ck_trades_direction"),
        CheckConstraint("execution_mode IN ('broker', 'live', 'demo', 'paper')", name="ck_trades_execution_mode"),
        CheckConstraint(
            "reconciliation_state IN ('pending', 'reconciled', 'exception')", name="ck_trades_reconciliation_state"
        ),
        db.Index("idx_trades_user_status", "user_id", "status"),
        db.Index("idx_trades_opened_at", "opened_at"),
        db.Index("idx_trades_user_pair", "user_id", "currency_pair"),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=False)
    currency_pair = db.Column(db.String(10), nullable=False)
    trade_type = db.Column(db.String(10), nullable=False)  # 'BUY' or 'SELL'
    entry_price = db.Column(Numeric(20, 10), nullable=False)
    exit_price = db.Column(Numeric(20, 10), nullable=True)
    lot_size = db.Column(Numeric(12, 4), nullable=False)
    stop_loss = db.Column(Numeric(20, 10), nullable=True)
    take_profit = db.Column(Numeric(20, 10), nullable=True)
    status = db.Column(db.String(32), default="draft", nullable=False)
    profit_loss = db.Column(Numeric(18, 2), default=0, nullable=False)
    execution_mode = db.Column(db.String(20), default="broker", nullable=False)
    idempotency_key = db.Column(db.String(64), nullable=True)
    mt5_ticket = db.Column(db.String(50), nullable=True)
    broker_order_id = db.Column(db.String(100), nullable=True)
    broker_response = db.Column(db.JSON, nullable=True)
    reconciliation_state = db.Column(db.String(20), default="pending", nullable=False)
    last_reconciled_at = db.Column(db.DateTime(timezone=True), nullable=True)

    opened_at = db.Column(db.DateTime(timezone=True), default=utcnow)
    closed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    signal_data = db.Column(db.JSON, default=dict)  # Store signal indicators that triggered trade
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class PaperOrderEvent(db.Model):
    """Immutable lifecycle event for a simulated order."""

    __tablename__ = "paper_order_events"
    __table_args__ = (
        UniqueConstraint("trade_id", "sequence", name="uq_paper_order_events_trade_sequence"),
        CheckConstraint(
            "event_type IN ('intent_recorded', 'risk_validated', 'opened', 'close_requested', 'closed', 'rejected', 'reconciled', 'reconciliation_exception')",
            name="ck_paper_order_events_type",
        ),
        db.Index("idx_paper_order_events_trade_created", "trade_id", "created_at"),
    )
    id = db.Column(db.Integer, primary_key=True)
    trade_id = db.Column(db.Integer, db.ForeignKey("trades.id"), nullable=False)
    sequence = db.Column(db.Integer, nullable=False)
    event_type = db.Column(db.String(32), nullable=False)
    state_before = db.Column(db.String(32), nullable=True)
    state_after = db.Column(db.String(32), nullable=False)
    details = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class PaperReconciliationRun(db.Model):
    """Durable record of a deterministic internal paper-ledger reconciliation."""

    __tablename__ = "paper_reconciliation_runs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=False)
    checked_count = db.Column(db.Integer, nullable=False, default=0)
    exception_count = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class PaperWorkerLease(db.Model):
    """Database lease ensuring only one paper lifecycle worker is active."""

    __tablename__ = "paper_worker_leases"
    name = db.Column(db.String(64), primary_key=True)
    owner_id = db.Column(db.String(64), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    last_cycle_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_success_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_error = db.Column(db.String(250), nullable=True)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


# Trading signals from analysis
class TradingSignal(db.Model):
    __tablename__ = "trading_signals"
    id = db.Column(db.Integer, primary_key=True)
    currency_pair = db.Column(db.String(10), nullable=False)
    signal_type = db.Column(db.String(10), nullable=False)  # 'BUY' or 'SELL'
    strength = db.Column(Numeric(5, 2), nullable=False)  # Signal strength 0-100
    price = db.Column(Numeric(20, 10), nullable=False)
    indicators = db.Column(db.JSON, default=dict)  # RSI, MACD, MA, etc.
    timeframe = db.Column(db.String(10), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=True)


# License activations (bind a license to MT5 account/server/machine)
class Activation(db.Model):
    __tablename__ = "license_activations"
    __table_args__ = (
        UniqueConstraint("license_id", "account_number", name="uq_activation_license_account"),
        CheckConstraint("status IN ('active', 'revoked')", name="ck_activations_status"),
    )
    id = db.Column(db.Integer, primary_key=True)
    license_id = db.Column(db.Integer, db.ForeignKey("licenses.id"), nullable=False)
    account_number = db.Column(db.String(50), nullable=False)
    server = db.Column(db.String(100), nullable=True)
    machine_fingerprint = db.Column(db.String(128), nullable=True)
    status = db.Column(db.String(20), default="active")  # 'active', 'revoked'
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    last_check_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


# Notification model for user notifications
class Notification(db.Model):
    __tablename__ = "notifications"
    __table_args__ = (
        db.Index("idx_notifications_user_read", "user_id", "is_read"),
        db.Index("idx_notifications_created", "created_at"),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(50), nullable=False)  # 'trade', 'signal', 'license', 'system', 'referral'
    is_read = db.Column(db.Boolean, default=False)
    data = db.Column(db.JSON, default=dict)  # Additional data like trade_id, etc.
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


# Referral tracking for mentor commissions
class Referral(db.Model):
    __tablename__ = "referrals"
    __table_args__ = (
        UniqueConstraint("referred_user_id", name="uq_referrals_referred_user"),
        UniqueConstraint("mentor_id", "license_id", name="uq_referrals_mentor_license"),
    )
    id = db.Column(db.Integer, primary_key=True)
    mentor_id = db.Column(db.String(3), nullable=False)  # The mentor's ID
    referred_user_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=False)
    license_id = db.Column(db.Integer, db.ForeignKey("licenses.id"), nullable=True)
    commission_amount = db.Column(Numeric(18, 2), default=0, nullable=False)
    commission_paid = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    paid_at = db.Column(db.DateTime(timezone=True), nullable=True)


class ProcessedStripeEvent(db.Model):
    """A Stripe event ledger; its unique event id makes webhook delivery idempotent."""

    __tablename__ = "processed_stripe_events"
    id = db.Column(db.Integer, primary_key=True)
    stripe_event_id = db.Column(db.String(255), unique=True, nullable=False)
    event_type = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(32), nullable=False, default="received")
    payload = db.Column(db.JSON, nullable=False, default=dict)
    processed_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class AuditEvent(db.Model):
    """Append-only record of sensitive security and financial actions."""

    __tablename__ = "audit_events"
    __table_args__ = (
        db.Index("idx_audit_events_actor_created", "actor_id", "created_at"),
        db.Index("idx_audit_events_target", "target_type", "target_id"),
    )
    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(100), nullable=False)
    actor_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=True)
    target_type = db.Column(db.String(64), nullable=True)
    target_id = db.Column(db.String(255), nullable=True)
    request_id = db.Column(db.String(64), nullable=True)
    event_metadata = db.Column("metadata", db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class BrokerAccount(db.Model):
    """Encrypted credential vault and bridge link for user MT4/MT5 accounts."""

    __tablename__ = "broker_accounts"
    __table_args__ = (
        CheckConstraint("platform IN ('MT4', 'MT5')", name="ck_broker_accounts_platform"),
        db.Index("idx_broker_accounts_user", "user_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String, db.ForeignKey("users.id"), unique=True, nullable=False)
    platform = db.Column(db.String(10), default="MT5", nullable=False)
    server = db.Column(db.String(100), nullable=False)
    account_login = db.Column(db.String(64), nullable=False)
    encrypted_password = db.Column(db.Text, nullable=False)
    is_connected = db.Column(db.Boolean, default=True, nullable=False)
    currency = db.Column(db.String(10), default="USD", nullable=False)
    balance = db.Column(Numeric(12, 2), default=0, nullable=False)
    equity = db.Column(Numeric(12, 2), default=0, nullable=False)
    free_margin = db.Column(Numeric(12, 2), default=0, nullable=False)
    last_synced_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
