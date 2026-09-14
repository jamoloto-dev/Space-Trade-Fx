"""Installed console scripts must resolve the packaged Flask modules."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_installed_console_entrypoints_show_help_from_outside_repository():
    scripts_dir = Path(sys.executable).parent
    for name in ("spacetradingfx", "spacetradingfx-paper-worker"):
        result = subprocess.run([scripts_dir / name, "--help"], cwd="/tmp", capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert "SpaceTradingFX" in result.stdout
