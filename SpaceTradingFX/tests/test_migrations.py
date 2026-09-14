"""Test that Alembic migration schema matches SQLAlchemy models with zero drift."""

import os
import sqlite3
import subprocess
import sys
import tempfile


def test_alembic_check_has_no_schema_drift():
    with tempfile.TemporaryDirectory(prefix="spacetradingfx-migration-test-") as directory:
        environment = {**os.environ, "DATABASE_URL": f"sqlite:///{directory}/schema.db"}
        upgrade = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"], capture_output=True, text=True, env=environment
        )
        assert upgrade.returncode == 0, f"Alembic upgrade failed:\n{upgrade.stdout}\n{upgrade.stderr}"
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "check"], capture_output=True, text=True, env=environment
        )
    assert result.returncode == 0, f"Alembic check detected drift:\nStdout: {result.stdout}\nStderr: {result.stderr}"
    assert "No new upgrade operations detected" in result.stdout


def test_upgrade_from_previous_supported_revision_preserves_a_compatible_schema():
    with tempfile.TemporaryDirectory(prefix="spacetradingfx-upgrade-test-") as directory:
        database_path = f"{directory}/upgrade.db"
        environment = {**os.environ, "DATABASE_URL": f"sqlite:///{database_path}"}
        previous = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "9ddf60f1d4ee"],
            capture_output=True,
            text=True,
            env=environment,
        )
        assert previous.returncode == 0, previous.stderr
        upgrade = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            env=environment,
        )
        assert upgrade.returncode == 0, upgrade.stderr
        with sqlite3.connect(database_path) as connection:
            trade_columns = {row[1] for row in connection.execute("PRAGMA table_info(trades)")}
            lease_columns = {row[1] for row in connection.execute("PRAGMA table_info(paper_worker_leases)")}
    assert {"mt5_ticket", "broker_order_id", "broker_response"} <= trade_columns
    assert {"last_cycle_at", "last_success_at", "last_error"} <= lease_columns
