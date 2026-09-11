# Setup notes

SpaceTradingFX is a Paper Trading application. No component may connect to a
broker, retain broker passwords, or submit a live order.

For local development, from the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
alembic upgrade head
python run.py
```

Use `python -m flask_dashboard.bootstrap_admin EMAIL` for the sole interactive
administrator bootstrap path. Production requires `SESSION_SECRET`,
`DATABASE_URL`, `LICENSE_PUBLIC_KEY_PEM`, and `LICENSE_PRIVATE_KEY_PEM`; use
the Docker Compose configuration, which verifies them before startup.

License activation binds a license to an account identifier for entitlement
purposes only. It is not a broker connection or authorization to trade live.
