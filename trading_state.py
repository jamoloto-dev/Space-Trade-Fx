"""Trading execution state and persistent trigger manager.

Provides synchronization between Streamlit dashboard UI, background MetaApi robot,
autonomous market scanners, local trigger/state files, and SQLite database.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("trading_state")

STATE_FILE_NAME = "trading_state.json"
TRIGGER_FILE_NAME = ".trading_active"
DB_FILE_NAME = "trading.db"


def _resolve_base_dir(base_dir: str | None = None) -> str:
    """Resolve project root directory."""
    if base_dir:
        return os.path.abspath(base_dir)
    env_dir = os.environ.get("SPACE_TRADING_ROOT")
    if env_dir and os.path.isdir(env_dir):
        return os.path.abspath(env_dir)
    # Default to current file's parent directory
    return os.path.dirname(os.path.abspath(__file__))


def get_state_file_path(base_dir: str | None = None) -> str:
    """Return path to JSON state file."""
    env_path = os.environ.get("TRADING_STATE_FILE")
    if env_path:
        return os.path.abspath(env_path)
    root = _resolve_base_dir(base_dir)
    return os.path.join(root, STATE_FILE_NAME)


def get_trigger_file_path(base_dir: str | None = None) -> str:
    """Return path to trigger flag file."""
    env_path = os.environ.get("TRADING_TRIGGER_FILE")
    if env_path:
        return os.path.abspath(env_path)
    root = _resolve_base_dir(base_dir)
    return os.path.join(root, TRIGGER_FILE_NAME)


def get_db_path(base_dir: str | None = None) -> str:
    """Return path to SQLite trading ledger."""
    env_path = os.environ.get("TRADING_DB_PATH")
    if env_path:
        return os.path.abspath(env_path)
    root = _resolve_base_dir(base_dir)
    return os.path.join(root, DB_FILE_NAME)


def load_execution_state(base_dir: str | None = None) -> bool:
    """Load persistent execution state.

    Checks (in priority order):
    1. TRADING_EXECUTION_FORCE environment variable ('1'/'true'/'0'/'false')
    2. Trigger file (.trading_active)
    3. State JSON file (trading_state.json)
    4. SQLite database (trading_preferences table)
    5. Default to True if unconfigured.
    """
    env_override = os.environ.get("TRADING_EXECUTION_FORCE")
    if env_override is not None:
        return env_override.strip().lower() in ("1", "true", "yes", "on")

    # 1. Trigger file check
    trigger_path = get_trigger_file_path(base_dir)
    if os.path.exists(trigger_path):
        try:
            content = Path(trigger_path).read_text(encoding="utf-8").strip().lower()
            if content in ("0", "false", "off", "no"):
                return False
            if content in ("1", "true", "yes", "on", ""):
                return True
        except Exception as exc:
            logger.debug("Failed reading trigger file %s: %s", trigger_path, exc)

    # 2. State JSON file check
    state_path = get_state_file_path(base_dir)
    if os.path.exists(state_path):
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "trading_active" in data:
                    return bool(data["trading_active"])
        except Exception as exc:
            logger.debug("Failed reading state JSON %s: %s", state_path, exc)

    # 3. SQLite database fallback check
    db_path = get_db_path(base_dir)
    if os.path.exists(db_path):
        try:
            with sqlite3.connect(db_path, timeout=2.0) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT trading_enabled, strategy_settings FROM trading_preferences LIMIT 1")
                row = cursor.fetchone()
                if row:
                    trading_enabled = bool(row[0])
                    auto_pilot = True
                    if row[1]:
                        try:
                            settings = json.loads(row[1]) if isinstance(row[1], str) else row[1]
                            if isinstance(settings, dict):
                                auto_pilot = bool(settings.get("auto_pilot", True))
                        except Exception:
                            pass
                    return trading_enabled and auto_pilot
        except Exception as exc:
            logger.debug("Failed checking database trading preferences: %s", exc)

    # Default to True when system first boots up
    return True


def save_execution_state(
    is_active: bool,
    base_dir: str | None = None,
    source: str = "dashboard",
) -> dict[str, Any]:
    """Persist execution state to JSON state file, trigger file, and database.

    Args:
        is_active: True to authorize trading execution, False to pause/stop.
        base_dir: Optional base directory.
        source: Identifier of the component updating state.

    Returns:
        Dictionary containing persisted state payload.
    """
    now_utc = datetime.now(timezone.utc).isoformat()
    state_payload = {
        "trading_active": bool(is_active),
        "updated_at": now_utc,
        "source": source,
    }

    # 1. Write state JSON file atomically
    state_path = get_state_file_path(base_dir)
    tmp_path = f"{state_path}.tmp"
    try:
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(state_payload, f, indent=2)
        os.replace(tmp_path, state_path)
    except Exception as exc:
        logger.warning("Could not persist state JSON to %s: %s", state_path, exc)
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    # 2. Write trigger flag file
    trigger_path = get_trigger_file_path(base_dir)
    try:
        os.makedirs(os.path.dirname(trigger_path), exist_ok=True)
        with open(trigger_path, "w", encoding="utf-8") as f:
            f.write("1\n" if is_active else "0\n")
    except Exception as exc:
        logger.warning("Could not persist trigger file to %s: %s", trigger_path, exc)

    # 3. Synchronize with SQLite database if present
    db_path = get_db_path(base_dir)
    if os.path.exists(db_path):
        try:
            with sqlite3.connect(db_path, timeout=3.0) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id, strategy_settings FROM trading_preferences LIMIT 1")
                pref_row = cursor.fetchone()
                if pref_row:
                    pref_id = pref_row[0]
                    raw_settings = pref_row[1]
                    settings_dict: dict[str, Any] = {}
                    if raw_settings:
                        try:
                            settings_dict = (
                                json.loads(raw_settings) if isinstance(raw_settings, str) else dict(raw_settings)
                            )
                        except Exception:
                            settings_dict = {}
                    settings_dict["auto_pilot"] = bool(is_active)
                    settings_dict["automated_broker_trading"] = bool(is_active)
                    cursor.execute(
                        "UPDATE trading_preferences "
                        "SET trading_enabled = ?, strategy_settings = ?, updated_at = ? "
                        "WHERE id = ?",
                        (1 if is_active else 0, json.dumps(settings_dict), now_utc, pref_id),
                    )
                    conn.commit()
        except Exception as exc:
            logger.warning("Could not update database trading_preferences: %s", exc)

    return state_payload


def is_execution_authorized(
    base_dir: str | None = None,
    db_path: str | None = None,
) -> bool:
    """Check if robot background process is authorized to execute trades.

    Convenience wrapper around load_execution_state with optional path overrides.
    """
    if db_path and not os.environ.get("TRADING_DB_PATH"):
        os.environ["TRADING_DB_PATH"] = db_path
    return load_execution_state(base_dir=base_dir)
