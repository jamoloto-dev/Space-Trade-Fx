"""Trading execution state and persistent trigger manager.

Provides synchronization between Streamlit dashboard UI, background MetaApi robot,
autonomous market scanners, local trigger/state files, and SQLite database.
Thin re-export bridging to flask_dashboard.services.trading_state for backward compatibility.
"""

from __future__ import annotations

try:
    from flask_dashboard.services import trading_state as _impl
except ImportError:
    try:
        from SpaceTradingFX.flask_dashboard.services import trading_state as _impl
    except ImportError:
        import importlib.util
        from pathlib import Path

        _candidate = (
            Path(__file__).resolve().parent / "SpaceTradingFX" / "flask_dashboard" / "services" / "trading_state.py"
        )
        if _candidate.is_file():
            _spec = importlib.util.spec_from_file_location("flask_dashboard.services.trading_state", _candidate)
            _impl = importlib.util.module_from_spec(_spec)
            assert _spec.loader is not None
            _spec.loader.exec_module(_impl)
        else:
            raise

STATE_FILE_NAME = _impl.STATE_FILE_NAME
TRIGGER_FILE_NAME = _impl.TRIGGER_FILE_NAME
DB_FILE_NAME = _impl.DB_FILE_NAME

_resolve_base_dir = _impl._resolve_base_dir
get_state_file_path = _impl.get_state_file_path
get_trigger_file_path = _impl.get_trigger_file_path
get_db_path = _impl.get_db_path
load_execution_state = _impl.load_execution_state
save_execution_state = _impl.save_execution_state
is_execution_authorized = _impl.is_execution_authorized

__all__ = [
    "DB_FILE_NAME",
    "STATE_FILE_NAME",
    "TRIGGER_FILE_NAME",
    "_resolve_base_dir",
    "get_db_path",
    "get_state_file_path",
    "get_trigger_file_path",
    "is_execution_authorized",
    "load_execution_state",
    "save_execution_state",
]
