"""Root database seeding entrypoint."""

import sys
from pathlib import Path

# Ensure SpaceTradingFX package root is on sys.path if not present
_space_trading_fx_dir = str(Path(__file__).resolve().parent / "SpaceTradingFX")
if _space_trading_fx_dir not in sys.path:
    sys.path.insert(0, _space_trading_fx_dir)

from flask_dashboard.seed_db import main  # noqa: E402

if __name__ == "__main__":
    main()
