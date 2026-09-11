"""Test that Alembic migration schema matches SQLAlchemy models with zero drift."""

import subprocess
import sys


def test_alembic_check_has_no_schema_drift():
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Alembic check detected drift:\nStdout: {result.stdout}\nStderr: {result.stderr}"
    assert "No new upgrade operations detected" in result.stdout
