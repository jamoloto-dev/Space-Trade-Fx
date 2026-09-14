# SpaceTradingFX

## Paper Trading only

SpaceTradingFX is a paper-trading dashboard. It records simulated orders and
uses market data for analysis; it does not connect to brokers or submit live
orders. MT5 HTTP routes deliberately return a feature-disabled, paper-only
response. Do not supply broker credentials to this application.

## Local development

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e '.[dev]'
export FLASK_ENV=development
alembic upgrade head
python run.py
pytest
```

The package install is required; it makes `flask_dashboard` available without
test-time `sys.path` changes. Create an administrator only through the
interactive command:

```bash
python -m flask_dashboard.bootstrap_admin admin@example.com
```

## Production

Set `SESSION_SECRET`, `DATABASE_URL`, `LICENSE_PUBLIC_KEY_PEM`, and
`LICENSE_PRIVATE_KEY_PEM` to real secrets. Stripe also needs
`STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, and `STRIPE_WEBHOOK_SECRET`.
The production Compose file intentionally fails fast if its required secrets
are absent. Its entrypoint runs `alembic upgrade head` before Gunicorn starts.

```bash
docker compose up --build
```

Browser checkout redirects are not proof of payment. Licenses are provisioned
only by signature-verified Stripe webhooks, with an event ledger and unique
payment IDs for idempotency.

## Paper order ledger

Paper orders use a validated lifecycle (`draft → validated → open → closing →
closed`) with an immutable event record, idempotency keys, and deterministic
internal reconciliation runs. Set `PAPER_TRADING_KILL_SWITCH=true` to reject
new paper orders immediately. Reconciliation is intentionally against the
local paper ledger only; it never contacts a broker.

## Automated paper workflow

Automation is opt-in. Configure supported symbols and fixed lots, enable
“Allow new paper orders” and “Enable deterministic automated paper signals”,
then run exactly one separate worker:

```bash
spacetradingfx-paper-worker --interval 30
```

The worker holds a database lease, updates simulated P/L and SL/TP exits, and
records local-ledger reconciliation runs. It never starts from Flask/Gunicorn.
`/health/paper-worker` reports whether its lease is active; detailed operating
assumptions and recovery steps are in [PAPER_TRADING_OPERATIONS.md](PAPER_TRADING_OPERATIONS.md).

The simulator fills at an observed candle close and deliberately omits
bid/ask, spreads, commissions, swaps, slippage, latency, partial fills,
margin, and FX conversion. Its results are not trading-performance evidence.

## Operational checks

- Liveness: `GET /health/live`
- Readiness: `GET /health/ready`
- Paper-only broker endpoints: `/api/mt5/connect`, `/api/mt5/positions`, and
  `/api/mt5/trade` return HTTP 409.

Generated virtual environments, cache files, logs, and local databases are
ignored by Git. Never commit credentials; rotate any credentials that may have
been committed historically.

The web-journey test suite uses Flask's test client; it is not real-browser
end-to-end coverage.
