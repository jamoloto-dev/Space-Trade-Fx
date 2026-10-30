"""Execution state bridge for Flask and background services."""

try:
    from .trading_state import (
        get_db_path,
        get_state_file_path,
        get_trigger_file_path,
        is_execution_authorized,
        load_execution_state,
        save_execution_state,
    )
except ImportError:
    from trading_state import (
        get_db_path,
        get_state_file_path,
        get_trigger_file_path,
        is_execution_authorized,
        load_execution_state,
        save_execution_state,
    )

__all__ = [
    "get_db_path",
    "get_state_file_path",
    "get_trigger_file_path",
    "is_execution_authorized",
    "load_execution_state",
    "save_execution_state",
]
