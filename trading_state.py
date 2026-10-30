"""Trading execution state and persistent trigger manager.

Provides synchronization between Streamlit dashboard UI, background MetaApi robot,
autonomous market scanners, local trigger/state files, and SQLite database.
Thin re-export bridging to flask_dashboard.services.trading_state for backward compatibility.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure SpaceTradingFX package root is on sys.path if not present
_space_trading_fx_dir = str(Path(__file__).resolve().parent / "SpaceTradingFX")
if _space_trading_fx_dir not in sys.path:
    sys.path.insert(0, _space_trading_fx_dir)

from flask_dashboard.services import trading_state as _impl  # noqa: E402

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
