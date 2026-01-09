"""
SpaceTradingFX Services Module
Aggregates all business logic services
"""

# Import all service modules for easy access
# These are re-exported for backward compatibility

from notifications import (  # type: ignore
    create_notification,
    get_user_notifications,
    get_unread_count,
    mark_as_read,
    mark_all_as_read,
    send_email_notification,
    notify_trade_opened,
    notify_trade_closed,
    notify_new_signal,
    notify_license_expiring,
    notify_new_referral,
    notify_commission_earned
)

from mentor_system import (  # type: ignore
    generate_mentor_id,
    register_as_mentor,
    get_mentor_by_id,
    track_referral,
    process_referral_commission,
    get_mentor_stats,
    COMMISSION_RATE,
    LICENSE_PRICES as MENTOR_LICENSE_PRICES
)

from mt5_connector import (  # type: ignore
    MT5Connector,
    MT5_AVAILABLE,
    get_mt5_connector
)

from trading_engine import TradingEngine  # type: ignore

from forex_data import (  # type: ignore
    ForexDataProvider,
    get_forex_provider
)

from license_manager import (  # type: ignore
    generate_license_key,
    validate_license_key,
    create_user_license,
    record_activation,
    license_status,
    get_active_license,
    check_license_valid,
    require_license,
    LICENSE_TYPES
)

__all__ = [
    # Notifications
    'create_notification',
    'get_user_notifications',
    'get_unread_count',
    'mark_as_read',
    'mark_all_as_read',
    'send_email_notification',
    'notify_trade_opened',
    'notify_trade_closed',
    'notify_new_signal',
    'notify_license_expiring',
    'notify_new_referral',
    'notify_commission_earned',
    
    # Mentor System
    'generate_mentor_id',
    'register_as_mentor',
    'get_mentor_by_id',
    'track_referral',
    'process_referral_commission',
    'get_mentor_stats',
    'COMMISSION_RATE',
    'MENTOR_LICENSE_PRICES',
    
    # MT5
    'MT5Connector',
    'MT5_AVAILABLE',
    'get_mt5_connector',
    
    # Trading
    'TradingEngine',
    
    # Forex Data
    'ForexDataProvider',
    'get_forex_provider',
    
    # License Management
    'generate_license_key',
    'validate_license_key',
    'create_user_license',
    'record_activation',
    'license_status',
    'get_active_license',
    'check_license_valid',
    'require_license',
    'LICENSE_TYPES',
]
