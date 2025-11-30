from datetime import datetime
from app import db
from flask_dance.consumer.storage.sqla import OAuthConsumerMixin
from flask_login import UserMixin
from sqlalchemy import UniqueConstraint
from werkzeug.security import generate_password_hash, check_password_hash


# User model (mandatory for Replit Auth)
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.String, primary_key=True)
    email = db.Column(db.String, unique=True, nullable=True)
    first_name = db.Column(db.String, nullable=True)
    last_name = db.Column(db.String, nullable=True)
    profile_image_url = db.Column(db.String, nullable=True)
    password_hash = db.Column(db.String, nullable=True)
    is_admin = db.Column(db.Boolean, default=False)
    has_unlimited_premium = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationships
    licenses = db.relationship('License', backref='user', lazy=True)
    trading_preferences = db.relationship('TradingPreference', backref='user', lazy=True)
    trades = db.relationship('Trade', backref='user', lazy=True)

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

    __table_args__ = (UniqueConstraint(
        'user_id',
        'browser_session_key',
        'provider',
        name='uq_user_browser_session_key_provider',
    ),)


# License model for managing user subscriptions
class License(db.Model):
    __tablename__ = 'licenses'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String, db.ForeignKey('users.id'), nullable=False)
    license_key = db.Column(db.String(500), unique=True, nullable=False)
    license_type = db.Column(db.String(50), nullable=False)  # 'basic', 'premium', 'professional'
    status = db.Column(db.String(20), default='pending')  # 'pending', 'active', 'expired', 'revoked'
    issued_at = db.Column(db.DateTime, default=datetime.now)
    expires_at = db.Column(db.DateTime, nullable=True)
    stripe_payment_id = db.Column(db.String(100), nullable=True)
    max_active_trades = db.Column(db.Integer, default=3)
    features = db.Column(db.JSON, default=dict)  # Store additional features as JSON
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    # Activation relationship (populated after EA/user binds account/server)
    activations = db.relationship('Activation', backref='license', lazy=True)


# Trading preferences for each user
class TradingPreference(db.Model):
    __tablename__ = 'trading_preferences'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String, db.ForeignKey('users.id'), nullable=False)
    currency_pairs = db.Column(db.JSON, default=list)  # ['EURUSD', 'GBPUSD', etc.]
    timeframe = db.Column(db.String(10), default='1H')  # '1M', '5M', '15M', '1H', '4H', 'D'
    risk_percentage = db.Column(db.Float, default=1.0)  # Risk per trade as % of account
    max_concurrent_trades = db.Column(db.Integer, default=3)
    trading_enabled = db.Column(db.Boolean, default=False)
    mt5_account = db.Column(db.String(100), nullable=True)
    mt5_server = db.Column(db.String(100), nullable=True)
    strategy_settings = db.Column(db.JSON, default=dict)  # Store strategy parameters
    # Per-currency direction preferences: { 'EURUSD': 'BOTH'|'BUY'|'SELL' }
    direction_preferences = db.Column(db.JSON, default=dict)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)


# Trade history and active trades
class Trade(db.Model):
    __tablename__ = 'trades'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String, db.ForeignKey('users.id'), nullable=False)
    currency_pair = db.Column(db.String(10), nullable=False)
    trade_type = db.Column(db.String(10), nullable=False)  # 'BUY' or 'SELL'
    entry_price = db.Column(db.Float, nullable=False)
    exit_price = db.Column(db.Float, nullable=True)
    lot_size = db.Column(db.Float, nullable=False)
    stop_loss = db.Column(db.Float, nullable=True)
    take_profit = db.Column(db.Float, nullable=True)
    status = db.Column(db.String(20), default='open')  # 'open', 'closed', 'cancelled'
    profit_loss = db.Column(db.Float, default=0.0)
    mt5_ticket = db.Column(db.String(50), nullable=True)  # MetaTrader ticket ID
    opened_at = db.Column(db.DateTime, default=datetime.now)
    closed_at = db.Column(db.DateTime, nullable=True)
    signal_data = db.Column(db.JSON, default=dict)  # Store signal indicators that triggered trade
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)


# Trading signals from analysis
class TradingSignal(db.Model):
    __tablename__ = 'trading_signals'
    id = db.Column(db.Integer, primary_key=True)
    currency_pair = db.Column(db.String(10), nullable=False)
    signal_type = db.Column(db.String(10), nullable=False)  # 'BUY' or 'SELL'
    strength = db.Column(db.Float, nullable=False)  # Signal strength 0-100
    price = db.Column(db.Float, nullable=False)
    indicators = db.Column(db.JSON, default=dict)  # RSI, MACD, MA, etc.
    timeframe = db.Column(db.String(10), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    expires_at = db.Column(db.DateTime, nullable=True)


# License activations (bind a license to MT5 account/server/machine)
class Activation(db.Model):
    __tablename__ = 'license_activations'
    id = db.Column(db.Integer, primary_key=True)
    license_id = db.Column(db.Integer, db.ForeignKey('licenses.id'), nullable=False)
    account_number = db.Column(db.String(50), nullable=False)
    server = db.Column(db.String(100), nullable=True)
    machine_fingerprint = db.Column(db.String(128), nullable=True)
    status = db.Column(db.String(20), default='active')  # 'active', 'revoked'
    created_at = db.Column(db.DateTime, default=datetime.now)
    last_check_at = db.Column(db.DateTime, default=datetime.now)
