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
from .autonomous_scanner import (
    run_autonomous_cycle,
    start_autonomous_scheduler,
    stop_autonomous_scheduler,
)
from .backtest_runner import (
    BacktestConfig,
    BacktestReport,
    SpaceTradeBacktestRunner,
)
from .binary_inspector import (
    SpaceTradeBinaryInspector,
    SpaceTradeBinaryReport,
)
from .broker_bridge import (
    DEFAULT_SYMBOL_SPECS,
    BrokerConnectionError,
    BrokerError,
    BrokerExecutionError,
    BrokerValidationError,
    clean_broker_symbol,
    decrypt_broker_password,
    dispatch_test_ping_trade,
    encrypt_broker_password,
    execute_robot_trade,
    fetch_metaapi_accounts,
    fetch_metaapi_positions,
    get_account_currency,
    get_active_metaapi_account_id,
    get_broker_telemetry,
    get_currency_symbol,
    get_symbol_spec,
    match_metaapi_account,
    normalize_volume,
    resolve_broker_symbol,
    resolve_filling_mode,
    resolve_metaapi_account_id,
    resolve_metaapi_provisioning_base_url,
    sync_broker_positions,
    verify_and_connect,
)
from .execution_broker import (
    AccountTelemetry,
    CloseResult,
    ExecutionBroker,
    LiveMetaApiBroker,
    OrderIntent,
    OrderResult,
    PaperExecutionBroker,
    Position,
)
from .news_intelligence import (
    MacroNewsEngine,
    check_ai_veto,
    evaluate_macro_sentiment,
    get_macro_pulse,
)
from .risk_manager import (
    RiskAssessmentResult,
    RiskLimits,
    SpaceTradeRiskManager,
)
from .signal_bridge import (
    SignalBridgeConfig,
    SpaceTradeSignalBridge,
)
from .strategy_transpiler import (
    SpaceTradeStrategyEngine,
    SpaceTradeStrategyTranspiler,
    SpaceTradeTranspilationResult,
)
from .trade_worker import (
    SpaceTradeWorker,
    start_space_trade_worker_daemon,
    stop_space_trade_worker_daemon,
)
from .trading_state import (
    DB_FILE_NAME,
    STATE_FILE_NAME,
    TRIGGER_FILE_NAME,
    get_db_path,
    get_state_file_path,
    get_trigger_file_path,
    is_execution_authorized,
    load_execution_state,
    save_execution_state,
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
    # Autonomous Background Scanner
    "start_autonomous_scheduler",
    "stop_autonomous_scheduler",
    "run_autonomous_cycle",
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
    "get_account_currency",
    "get_broker_telemetry",
    "fetch_metaapi_positions",
    "sync_broker_positions",
    "normalize_volume",
    "resolve_filling_mode",
    "get_symbol_spec",
    "dispatch_test_ping_trade",
    "clean_broker_symbol",
    "resolve_broker_symbol",
    "get_currency_symbol",
    "fetch_metaapi_accounts",
    "match_metaapi_account",
    "get_active_metaapi_account_id",
    "resolve_metaapi_account_id",
    "resolve_metaapi_provisioning_base_url",
    # News & Macro Intelligence
    "MacroNewsEngine",
    "check_ai_veto",
    "evaluate_macro_sentiment",
    "get_macro_pulse",
    # Strategy Adaptation & Transpilation Engine
    "SpaceTradeStrategyEngine",
    "SpaceTradeStrategyTranspiler",
    "SpaceTradeTranspilationResult",
    # Universal Signal Bridge
    "SpaceTradeSignalBridge",
    "SignalBridgeConfig",
    # Binary Diagnostics & Metadata Triage
    "SpaceTradeBinaryInspector",
    "SpaceTradeBinaryReport",
    # Vectorized Backtesting Engine
    "SpaceTradeBacktestRunner",
    "BacktestConfig",
    "BacktestReport",
    # Execution Broker Protocol & Unified Worker
    "ExecutionBroker",
    "OrderIntent",
    "OrderResult",
    "CloseResult",
    "Position",
    "AccountTelemetry",
    "PaperExecutionBroker",
    "LiveMetaApiBroker",
    "SpaceTradeRiskManager",
    "RiskLimits",
    "RiskAssessmentResult",
    "SpaceTradeWorker",
    "start_space_trade_worker_daemon",
    "stop_space_trade_worker_daemon",
    # Trading State Management
    "DB_FILE_NAME",
    "STATE_FILE_NAME",
    "TRIGGER_FILE_NAME",
    "get_db_path",
    "get_state_file_path",
    "get_trigger_file_path",
    "is_execution_authorized",
    "load_execution_state",
    "save_execution_state",
]
