"""
SpaceTradingFX Services Module
Aggregates all business logic services
"""

# Import all service modules for easy access
# These are re-exported for backward compatibility

from ..forex_data import ForexDataProvider, get_forex_provider
from ..license_manager import (
    LICENSE_TYPES,
    check_license_valid,
    create_user_license,
    generate_license_key,
    get_active_license,
    license_status,
    record_activation,
    require_license,
    validate_license_key,
)
from ..mentor_system import (
    COMMISSION_RATE,
    generate_mentor_id,
    get_mentor_by_id,
    get_mentor_stats,
    process_referral_commission,
    register_as_mentor,
    track_referral,
)
from ..mentor_system import LICENSE_PRICES as MENTOR_LICENSE_PRICES
from ..mt5_connector import MT5_AVAILABLE, MT5Connector, get_mt5_connector
from ..notifications import (
    create_notification,
    get_unread_count,
    get_user_notifications,
    mark_all_as_read,
    mark_as_read,
    notify_commission_earned,
    notify_license_expiring,
    notify_new_referral,
    notify_new_signal,
    notify_trade_closed,
    notify_trade_opened,
    send_email_notification,
)
from ..trading_engine import TradingEngine
from .broker_bridge import (
    DEFAULT_SYMBOL_SPECS,
    BrokerConnectionError,
    BrokerError,
    BrokerExecutionError,
    BrokerValidationError,
    decrypt_broker_password,
    dispatch_test_ping_trade,
    encrypt_broker_password,
    execute_robot_trade,
    get_symbol_spec,
    normalize_volume,
    resolve_filling_mode,
    verify_and_connect,
)

__all__ = [
    # Notifications
    "create_notification",
    "get_user_notifications",
    "get_unread_count",
    "mark_as_read",
    "mark_all_as_read",
    "send_email_notification",
    "notify_trade_opened",
    "notify_trade_closed",
    "notify_new_signal",
    "notify_license_expiring",
    "notify_new_referral",
    "notify_commission_earned",
    # Mentor System
    "generate_mentor_id",
    "register_as_mentor",
    "get_mentor_by_id",
    "track_referral",
    "process_referral_commission",
    "get_mentor_stats",
    "COMMISSION_RATE",
    "MENTOR_LICENSE_PRICES",
    # MT5
    "MT5Connector",
    "MT5_AVAILABLE",
    "get_mt5_connector",
    # Trading
    "TradingEngine",
    # Forex Data
    "ForexDataProvider",
    "get_forex_provider",
    # License Management
    "generate_license_key",
    "validate_license_key",
    "create_user_license",
    "record_activation",
    "license_status",
    "get_active_license",
    "check_license_valid",
    "require_license",
    "LICENSE_TYPES",
    # Broker Bridge
    "BrokerError",
    "BrokerConnectionError",
    "BrokerValidationError",
    "BrokerExecutionError",
    "DEFAULT_SYMBOL_SPECS",
    "encrypt_broker_password",
    "decrypt_broker_password",
    "verify_and_connect",
    "execute_robot_trade",
    "normalize_volume",
    "resolve_filling_mode",
    "get_symbol_spec",
    "dispatch_test_ping_trade",
]
