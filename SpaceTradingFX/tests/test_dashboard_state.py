"""Tests for Dashboard State Persistence, Execution Flag/Trigger File, and Robot Link."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

try:
    from streamlit.testing.v1 import AppTest

    HAS_STREAMLIT = True
except ImportError:
    AppTest = None  # type: ignore[assignment,misc]
    HAS_STREAMLIT = False

from trading_state import (
    is_execution_authorized,
    load_execution_state,
    save_execution_state,
)


@pytest.fixture
def temp_workspace():
    """Create a temporary directory for isolated state and trigger testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = os.path.join(tmpdir, "trading_state.json")
        trigger_file = os.path.join(tmpdir, ".trading_active")
        db_file = os.path.join(tmpdir, "trading.db")

        # Initialize mock SQLite schema
        with sqlite3.connect(db_file) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE trading_preferences (
                    id INTEGER PRIMARY KEY,
                    user_id TEXT,
                    trading_enabled BOOLEAN,
                    strategy_settings TEXT,
                    updated_at TEXT
                )
                """
            )
            cursor.execute(
                """
                INSERT INTO trading_preferences (id, user_id, trading_enabled, strategy_settings, updated_at)
                VALUES (1, 'test-user', 1, '{"auto_pilot": true}', '2026-10-23T00:00:00Z')
                """
            )
            conn.commit()

        yield {
            "root": tmpdir,
            "state_file": state_file,
            "trigger_file": trigger_file,
            "db_file": db_file,
        }


def test_save_and_load_execution_state(temp_workspace):
    """Verify saving active/inactive state persists to state JSON, trigger file, and database."""
    root = temp_workspace["root"]
    state_file = temp_workspace["state_file"]
    trigger_file = temp_workspace["trigger_file"]
    db_file = temp_workspace["db_file"]

    # Initial state should be True (from DB or default)
    assert load_execution_state(base_dir=root) is True

    # 1. Turn trading OFF
    res_off = save_execution_state(False, base_dir=root, source="test")
    assert res_off["trading_active"] is False

    # Check state file
    assert os.path.exists(state_file)
    with open(state_file, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["trading_active"] is False
        assert data["source"] == "test"

    # Check trigger file
    assert os.path.exists(trigger_file)
    with open(trigger_file, "r", encoding="utf-8") as f:
        content = f.read().strip()
        assert content == "0"

    # Check SQLite DB
    with sqlite3.connect(db_file) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT trading_enabled, strategy_settings FROM trading_preferences WHERE id = 1")
        row = cursor.fetchone()
        assert row[0] == 0
        settings = json.loads(row[1])
        assert settings["auto_pilot"] is False

    # Verify load_execution_state returns False
    assert load_execution_state(base_dir=root) is False
    assert is_execution_authorized(base_dir=root) is False

    # 2. Turn trading ON
    res_on = save_execution_state(True, base_dir=root, source="test")
    assert res_on["trading_active"] is True

    with open(state_file, "r", encoding="utf-8") as f:
        assert json.load(f)["trading_active"] is True

    with open(trigger_file, "r", encoding="utf-8") as f:
        assert f.read().strip() == "1"

    with sqlite3.connect(db_file) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT trading_enabled, strategy_settings FROM trading_preferences WHERE id = 1")
        row = cursor.fetchone()
        assert row[0] == 1
        assert json.loads(row[1])["auto_pilot"] is True

    assert load_execution_state(base_dir=root) is True
    assert is_execution_authorized(base_dir=root) is True


def test_environment_variable_force_override(temp_workspace):
    """Verify TRADING_EXECUTION_FORCE overrides file and database states."""
    root = temp_workspace["root"]
    save_execution_state(False, base_dir=root)
    assert load_execution_state(base_dir=root) is False

    with patch.dict(os.environ, {"TRADING_EXECUTION_FORCE": "true"}):
        assert load_execution_state(base_dir=root) is True

    with patch.dict(os.environ, {"TRADING_EXECUTION_FORCE": "0"}):
        assert load_execution_state(base_dir=root) is False


@pytest.mark.skipif(not HAS_STREAMLIT or AppTest is None, reason="streamlit is not installed")
def test_streamlit_dashboard_session_state_and_button_toggle(temp_workspace):
    """Test Streamlit dashboard session_state initialization, badge rendering, and click toggle."""
    app_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "..",
        "dashboard",
        "app.py",
    )
    app_path = os.path.abspath(app_path)
    assert os.path.exists(app_path)

    # Initialize state file to True
    save_execution_state(True, base_dir=temp_workspace["root"])

    # Run Streamlit AppTest in isolation
    with patch.dict(
        os.environ,
        {
            "TRADING_STATE_FILE": temp_workspace["state_file"],
            "TRADING_TRIGGER_FILE": temp_workspace["trigger_file"],
            "TRADING_DB_PATH": temp_workspace["db_file"],
        },
    ):
        at = AppTest.from_file(app_path)
        at.run()
        assert not at.exception

        # Check session state
        assert at.session_state["trading_active"] is True

        # Check active status badge rendered in markdown
        active_markdown = [m.value for m in at.markdown if "ROBOT STATUS: ACTIVE" in m.value]
        assert len(active_markdown) == 1
        assert "Authorized to Trade" in active_markdown[0]

        # Check toggle button label
        btn = at.button(key="btn_toggle_trading")
        assert "STOP TRADING" in btn.label

        # Click the button to toggle to INACTIVE
        btn.click().run()
        assert not at.exception
        assert at.session_state["trading_active"] is False

        # Status badge should now show INACTIVE
        inactive_markdown = [m.value for m in at.markdown if "ROBOT STATUS: INACTIVE" in m.value]
        assert len(inactive_markdown) == 1
        assert "Execution Paused" in inactive_markdown[0]

        # Button label should now be START TRADING
        btn2 = at.button(key="btn_toggle_trading")
        assert "START TRADING" in btn2.label

        # Click START TRADING to toggle back to ACTIVE
        btn2.click().run()
        assert not at.exception
        assert at.session_state["trading_active"] is True


@pytest.mark.anyio
async def test_metaapi_robot_pauses_when_trading_inactive(temp_workspace):
    """Verify metaapi_robot respects the execution flag and pauses execution when inactive."""
    import metaapi_robot

    root = temp_workspace["root"]
    save_execution_state(False, base_dir=root)

    mock_connection = MagicMock()
    mock_connection.connect = AsyncMock()
    mock_connection.wait_synchronized = AsyncMock()
    mock_connection.get_account_information = AsyncMock(
        return_value={"balance": 1000.0, "equity": 1000.0, "freeMargin": 1000.0, "credit": 0.0}
    )
    mock_connection.get_positions = AsyncMock(return_value=[])

    mock_account = MagicMock()
    mock_account.state = "DEPLOYED"
    mock_account.connection_status = "CONNECTED"
    mock_account.wait_connected = AsyncMock()
    mock_account.get_rpc_connection = MagicMock(return_value=mock_connection)

    mock_api = MagicMock()
    mock_api.metatrader_account_api.get_account = AsyncMock(return_value=mock_account)

    with (
        patch.dict(
            os.environ,
            {
                "METAAPI_TOKEN": "mock.jwt.token",
                "METAAPI_ACCOUNT_ID": "mock-account-id",
                "TRADING_STATE_FILE": temp_workspace["state_file"],
                "TRADING_TRIGGER_FILE": temp_workspace["trigger_file"],
                "TRADING_DB_PATH": temp_workspace["db_file"],
            },
        ),
        patch("metaapi_robot.MetaApi", return_value=mock_api),
        patch("metaapi_robot.evaluate_market_signal") as mock_signal,
    ):
        await metaapi_robot.run_trading_robot(
            symbols=["EURUSD.ifx"],
            loop=False,
            max_cycles=1,
            monitor_positions=False,
        )
        # Because execution was paused, evaluate_market_signal was never called!
        assert mock_signal.call_count == 0


@pytest.mark.anyio
async def test_metaapi_robot_proceeds_when_trading_active(temp_workspace):
    """Verify metaapi_robot proceeds to evaluate signals when trading is authorized/active."""
    import metaapi_robot

    root = temp_workspace["root"]
    save_execution_state(True, base_dir=root)

    mock_connection = MagicMock()
    mock_connection.connect = AsyncMock()
    mock_connection.wait_synchronized = AsyncMock()
    mock_connection.get_account_information = AsyncMock(
        return_value={"balance": 1000.0, "equity": 1000.0, "freeMargin": 1000.0, "credit": 0.0}
    )
    mock_connection.get_positions = AsyncMock(return_value=[])
    mock_connection.close = AsyncMock()

    mock_account = MagicMock()
    mock_account.state = "DEPLOYED"
    mock_account.connection_status = "CONNECTED"
    mock_account.wait_connected = AsyncMock()
    mock_account.get_rpc_connection = MagicMock(return_value=mock_connection)

    mock_api = MagicMock()
    mock_api.metatrader_account_api.get_account = AsyncMock(return_value=mock_account)

    with (
        patch.dict(
            os.environ,
            {
                "METAAPI_TOKEN": "mock.jwt.token",
                "METAAPI_ACCOUNT_ID": "mock-account-id",
                "TRADING_STATE_FILE": temp_workspace["state_file"],
                "TRADING_TRIGGER_FILE": temp_workspace["trigger_file"],
                "TRADING_DB_PATH": temp_workspace["db_file"],
            },
        ),
        patch("metaapi_robot.MetaApi", return_value=mock_api),
        patch("metaapi_robot.resolve_tradable_symbol", AsyncMock(return_value="EURUSD.ifx")),
        patch(
            "metaapi_robot.evaluate_market_signal",
            return_value={"signal": "HOLD", "confidence": 0.50},
        ) as mock_signal,
    ):
        await metaapi_robot.run_trading_robot(
            symbols=["EURUSD.ifx"],
            loop=False,
            max_cycles=1,
            monitor_positions=False,
        )
        # Because execution was authorized, evaluate_market_signal was executed!
        assert mock_signal.call_count == 1
