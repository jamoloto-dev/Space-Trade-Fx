# SpaceTradingFX refactoring assessment

**Assessment date:** 2026-09-10  
**Purpose:** a factual codebase handoff for an implementation model. This is an assessment, not a request to change behaviour without first preserving it in tests.

## Executive summary

SpaceTradingFX is a Flask dashboard for licensing, manual/automated trading records, MT5 connectivity, payments, notifications, and mentor referrals. It also contains a separate `space_trading_fx` package that is mostly mock/demo trading code and is not integrated into the dashboard runtime.

The application needs a **stabilisation and security pass before feature refactoring**. It currently has two overlapping route implementations, relies on import side effects to compose the app, and has production paths that do not register the dashboard routes. The highest risk is authorization: the normal login accepts an email address with no password and a default administrator is created at startup. With the default email, this allows an unauthenticated visitor to log in as the administrator.


## What was inspected and what was verified

- 6,183 lines across Python/configuration/documentation files; `routes.py` alone is 777 lines.
- The project has two web implementations:
  - legacy decorators on the global app in `SpaceTradingFX/flask_dashboard/routes.py`;
  - duplicate `auth`, `mobile`, and `trading` blueprints in `SpaceTradingFX/flask_dashboard/blueprints/`.
- `run.py` and `flask_dashboard/main.py` import `routes`, so local execution uses the legacy routes. The Docker command starts `app:app` and therefore does **not** import `routes`.
- `activation_api.py`, `payments.py`, and `admin.py` register blueprints as module import side effects. The activation module is not imported by the ordinary app startup path.
- Source compilation succeeded with Python 3.14.7. The configured test and lint executables were unavailable in the current Linux environment (`pytest: command not found`, `ruff: command not found`), so the existing tests were not executed. The checked-in virtual environment is Windows-formatted (`venv/Scripts/*.exe`) and cannot validate this Linux workspace.

## Confirmed high-priority defects and risks

| Priority | Finding | Evidence and impact | Required outcome |
|---|---|---|---|
| P0 | Passwordless account impersonation and default admin takeover | `/login` creates or logs in a user using only an email address. `app.py` creates a default, unlimited-premium administrator using a real default email, and the same login flow will log that user in without checking a password. | Remove the email-only login from production. Do not seed a privileged user automatically. Add real registration, password/OAuth verification, and a one-time explicit admin bootstrap procedure. |
| P0 | Docker production does not register dashboard routes | Docker starts `app:app`; route registration occurs only when `routes.py` is imported by `run.py`/`main.py`. The factory module does not import it. The deployed app therefore lacks the documented dashboard and most APIs. | Make a factory explicitly register every blueprint. Point Gunicorn at the factory-created WSGI app. Add a smoke test asserting the route map. |
| P0 | Payment webhook is shadowed by a no-op handler | `app.py` registers `/payments/webhook` with `pass`. Importing `payments.py` later registers the same URL. Flask resolves the first matching rule, so the placeholder can receive Stripe requests and return a server error. | Delete the placeholder; declare the webhook once in the payments blueprint and exempt that actual endpoint from CSRF while retaining Stripe signature verification. |
| P0 | License activation routes are not reliably available | `activation_api.py` self-registers, but current startup does not import it. Tests expect `/api/license/*`, yet their fixture imports `flask_dashboard.app` only. | Register the activation blueprint centrally. Test all documented routes through the production factory. |
| P0 | Admin UI is public | `GET /admin/ui` has no `login_required` or `admin_required` decorator. | Require authentication and authorization for every admin route and template. Add negative authorization tests. |
| P1 | Two divergent route layers cause behavior drift | `routes.py` duplicates functions in all three blueprints, including login, preferences, mobile screens, trading actions, notification APIs, and MT5 APIs. They already differ: blueprint MT5 validation is stricter and endpoint names/redirects differ. | Select blueprints as the sole HTTP layer, port any missing legacy behavior, then delete `routes.py`; do not register both implementations. |
| P1 | Package/entry-point contract is broken | The console entry point targets `SpaceTradingFX.flask_dashboard.main:main`, but `main.py` has no `main` function. Absolute imports such as `from app import db` require path hacks and conflict with package imports. `pyproject.toml` also omits runtime packages used by `app.py` (`flask-wtf`, `flask-limiter`). | Adopt package-relative imports and a valid factory/CLI entry point. Make one lockfile/dependency manifest authoritative and verify clean installation in CI. |
| P1 | Financial/trading behavior is unsafe to present as live execution | `TradingEngine` persists trades before sending a broker order; it uses hard-coded pip and P/L math, a fallback price of `1.0`, `float` values for prices/volumes/P&L, and no durable broker order state. Market provider failures are broadly swallowed. | Treat dashboard trades as simulation until a broker adapter with idempotency, decimal arithmetic, symbol metadata, risk checks, audit trails, and reconciliation exists. Gate real trading behind explicit feature controls. |
| P1 | Database changes are unmanaged | Startup calls `db.create_all()`. `db_migrate.py` is an SQLite-only, partial imperative migration helper; production uses PostgreSQL. | Adopt Alembic/Flask-Migrate migrations. Remove schema mutation from normal startup and prove upgrades on a PostgreSQL database in CI. |
| P1 | License and payment rules are duplicated and inconsistent | `license_manager.LICENSE_TYPES`, `payments.LICENSE_PRICES`, and README disagree (for example Premium is $79.99 vs $99.99; Basic max trades 3 vs 10). `features` is a list in one flow and a dictionary in another. | Create one typed product/catalog definition used by checkout, issuance, license validation, UI, and tests. |

## Architecture today

```text
run.py / flask_dashboard/main.py
  -> path injection + import `app`
  -> import `routes` (legacy app decorators)
       -> imports `payments` and `admin` (side-effect registration)
       -> does not import `activation_api`

Docker Gunicorn: `app:app`
  -> imports only app.py
       -> creates tables and a default admin
       -> registers /health and a placeholder /payments/webhook
       -> no legacy routes, no application blueprints

blueprints/ (auth, mobile, trading)
  -> overlap with routes.py
  -> registration helper exists but is not called by app.py
```

The desired direction is:

```text
create_app(config) -> extensions -> models/migrations -> explicit blueprints
                                      |
                      HTTP controllers (thin validation/auth adapters)
                                      |
       application services: identity | licenses | payments | trading | notifications
                                      |
 ports/adapters: SQLAlchemy repo | Stripe | MT5 | market-data provider | SMTP
```

## Detailed technical findings

### Application composition and deployability

- `app.py` constructs a global app at import time, configures extensions, creates tables, and creates an admin account. This makes tests, CLI, workers, and deployment difficult to configure independently.
- Imports are a mixture of package imports (`flask_dashboard.app`) and top-level imports (`from app import db`, `from config import get_config`). The latter only work when `flask_dashboard` is inserted onto `sys.path` or is the working directory.
- The plain-module and package forms can create two module instances (`app` and `flask_dashboard.app`) with different `db`/app objects. Standardize on `flask_dashboard.*` relative imports.
- `api/__init__.py` describes aggregation but importing it can also duplicate registration because its modules self-register. Registry ownership must have exactly one home: the factory.
- The root README, nested README, Docker, and `pyproject.toml` describe incompatible start and packaging paths. There is no reliable clean-install contract.

### Authentication and authorization

- Normal login is explicitly marked development-only but is mounted by normal production startup. It uses email as identity proof.
- The default admin creation catches all errors and silently continues, hiding a failed security bootstrap or schema problem. It also logs personal data.
- Admin decorators are hand-written without `functools.wraps`; use a central policy/dependency instead. The public `/admin/ui` is the immediate authorization gap.
- License activation/status routes require a browser login, while the bundled MT5 EA is meant to make HTTP calls. Define an explicit machine-authentication protocol for the EA (e.g. signed request/API credential bound to a license activation), rate limit it, and never rely on browser session cookies.
- All state-changing browser routes need a deliberate CSRF policy. Keep CSRF enabled for forms; use narrow exemptions only for authenticated external webhooks/API credential endpoints.

### Domain logic and data integrity

- Models use naive `datetime.now`; use timezone-aware UTC timestamps and database defaults where appropriate.
- Currency values, prices, lot sizes, and commissions use `Float`; use `Decimal`/database numeric columns. Store monetary currency and unit conventions.
- Statuses are unvalidated strings (`active`, `expired`, `revoked`, etc.). Introduce enums/state transitions and enforce them at service boundaries.
- `get_active_license()` filters for unexpired licenses before checking whether a selected license expired, making its later expiration update branch unreachable. Expired records may remain marked `active`.
- Activation deduplication is application-only; add a database uniqueness constraint for the intended identity (at minimum `license_id + account_number`, after confirming the business rule) and make activation issuance transactional.
- `TradingPreference` creation and updates are repeated in controllers and engine construction. A unique `user_id` constraint plus a repository/service `get_or_create` operation is required to prevent duplicates.
- Referral relationships are not fully constrained: mentor IDs are stored as strings, and referral ownership/idempotency needs database-level rules.

### Trading and external services

- `TradingEngine` directly knows SQLAlchemy models and market-data access. Extract a pure risk/strategy layer and an application service that coordinates repositories/adapters.
- `ForexDataProvider` relies on response-key ordering (`list(data.keys())[1]`), maps dashboard timeframes such as `1H` directly to an Alpha Vantage API interval that expects other values, and returns raw exception messages. Create an adapter that validates provider responses and translates provider errors into stable domain errors.
- `MockForexDataProvider` uses random values, so tests cannot be deterministic. Inject a deterministic fake provider in tests.
- The `mt5_connector.py` instance state is process-local. With four Gunicorn workers, “connected” is not a reliable per-user connection state. Credentials are submitted to the server and connections need a deliberate lifecycle and secret-storage design.
- Existing `space_trading_fx` code is a separate mock/demo package (prints, mock API, minimal strategy/executor) rather than the dashboard’s domain engine. Decide whether to delete it, turn it into a tested shared domain package, or clearly isolate it as a demo. Do not maintain two trading cores.

### Reliability, observability, and maintainability

- Broad `except Exception`/bare `except` blocks frequently replace an actual error with a successful-looking empty result. Catch expected integration failures, roll back failed database transactions, log structured context without secrets, and return a stable user-safe error.
- Logging is globally set to DEBUG at import time. Use a configuration-driven structured logger and avoid passwords, license keys, payment payloads, and personal data in logs.
- The `/health` endpoint should have separate liveness and readiness semantics. Its database query should use `sqlalchemy.text` explicitly and never disclose raw exception strings in production responses.
- Route handlers parse numeric form/JSON values without validation, so bad inputs can result in `ValueError`/500 responses. Add request schemas/forms, bounds, allowed symbols, and domain validation.
- Tests cover only three narrow flows: a mock legacy strategy, license activation, and preferences persistence. They do not cover production startup, security boundaries, payments/webhook idempotency, broker execution, migrations, or error cases.

## Refactoring plan in safe order

### Phase 0 — contain production risk

1. Disable live deployment and live MT5 trade actions until identity and transaction controls are corrected.
2. Remove production email-only login and automatic default-admin creation; rotate `SESSION_SECRET`, Stripe keys, MT5 credentials, and license signing keys if the app has ever been exposed.
3. Require admin authorization on `/admin/ui`; remove the placeholder webhook and ensure Stripe verification is mandatory outside an explicitly isolated local test configuration.
4. Make app startup fail fast in production if required secrets/configuration are missing. Do not fall back to ephemeral license signing keys in production.

### Phase 1 — establish one executable application

1. Add `create_app(config_name=None)` in `flask_dashboard/__init__.py` or `app_factory.py`.
2. Instantiate extensions unbound (`db`, login manager, CSRF, limiter) and call `init_app` in the factory.
3. Convert all dashboard imports to package-relative imports. Remove `sys.path` manipulation from `run.py`.
4. Explicitly register, once each: auth, mobile, trading, admin, payment, and activation blueprints. Choose URL prefixes and endpoint names as a compatibility contract.
5. Port the active behavior from `routes.py` into blueprints where needed, then delete `routes.py` and all self-registration code.
6. Correct the console script and Docker command to the factory WSGI target. Add a smoke test that verifies expected routes in the production configuration.

### Phase 2 — create test and schema safety nets

1. Make `pyproject.toml` the single dependency source, include all imported packages, define a supported Python range, and regenerate the lockfile. Do not commit a platform-specific virtual environment.
2. Add Alembic migrations and baseline the existing schema. Test upgrade/downgrade on PostgreSQL.
3. Use per-test app factories, transaction isolation, and dependency injection. Remove `sys.path` mutations from tests.
4. Add tests for: unauthenticated/admin/owner authorization matrices; payment webhook signature and idempotency; license expiry/revocation/activation limits; input-validation failures; registration of every documented route; and database uniqueness races.
5. Add CI steps: clean install, `ruff check`, formatting check, type checking, unit/integration tests, migration check, and container smoke test.

### Phase 3 — separate the domain

1. Define typed DTOs/commands for preferences, license issuance, payment confirmation, trade intent, and broker execution result.
2. Move license catalog, state transitions, and activation policy to a `licenses` service with repositories. One catalog must supply Stripe and local issuance.
3. Split trading into strategy/risk calculation, ledger/order service, market-data adapter, and broker adapter. Make the “simulated versus live” state explicit.
4. Use `Decimal`, UTC timestamps, enums, database constraints, and idempotency keys. Maintain audit events for license/payment/trade state changes.
5. Integrate notifications/referrals through explicit service calls or an outbox after commit; do not silently ignore failures.

### Phase 4 — simplify and improve user behavior

1. Replace duplicated templates/controllers only after baseline tests preserve URLs and form behavior.
2. Add pagination and database aggregation for trade history and dashboard statistics rather than loading all trades into Python.
3. Add consistent error handling, request IDs, structured audit logs, and health/readiness endpoints.
4. Write operational documentation: environment variables, migration deployment, secrets rotation, recovery/reconciliation, and MT5 lifecycle.

## Acceptance criteria for the refactor

- A clean environment can install, migrate, and start the app with one documented command.
- Docker and local development use the same factory and expose the same tested route map.
- Exactly one handler exists for each URL and no routes are registered by import side effect.
- No user can authenticate as another user or an admin merely by supplying an email address.
- Admin pages/actions require explicit admin authorization; payment webhooks have verified signatures and are idempotent.
- Migrations, not `create_all`, manage production schema changes.
- License plan pricing/features/max-trade limits have one canonical source and stable data shape.
- Trade intent, broker submission, broker result, and ledger state are durable, auditable, and distinguish simulation from live execution.
- Tests execute deterministically on supported platforms and cover the critical authorization, payment, license, and deployment paths.

## Implementation brief for another model

```text
You are refactoring the SpaceTradingFX repository. First preserve behavior with tests, then implement the refactor incrementally. Do not make it a live-trading system as part of this work.

Non-negotiable constraints:
- Remove production email-only authentication and automatic default-admin creation. Use a secure auth flow and an explicit admin bootstrap command.
- Introduce one Flask application factory with explicit extension and blueprint registration. No route/blueprint registration by import side effect and no sys.path hacks.
- Make Docker, the CLI entry point, tests, and local development all create the same application.
- Consolidate the duplicated legacy `routes.py` and `blueprints/` implementations into one blueprint-based HTTP layer while preserving documented URLs or adding tested compatibility redirects.
- Register the payments, activation, and admin routes centrally. Remove the placeholder `/payments/webhook`; the real webhook must verify Stripe signatures and be the only CSRF-exempt webhook endpoint.
- Replace startup `create_all()` and the custom SQLite-only migration helper with Alembic migrations suitable for PostgreSQL.
- Make one typed license/product catalog the only source for prices, duration, features, and trade limits.
- Treat all trading as simulation until the system has explicit risk controls, Decimal values, an idempotent broker adapter, durable order states, reconciliation, and audit logs.
- Use package-relative imports, a single dependency manifest, deterministic test fakes, request validation, UTC timestamps, enums/constraints, and narrow error handling.

Work in small commits/changesets. After each phase, run formatting/linting, tests, migration checks, and an app-route smoke test. Report any behavior you cannot preserve before changing it.
```

## Useful source locations

- Application bootstrap and unsafe default admin: `SpaceTradingFX/flask_dashboard/app.py`
- Active legacy HTTP layer: `SpaceTradingFX/flask_dashboard/routes.py`
- Duplicate candidate blueprint layer: `SpaceTradingFX/flask_dashboard/blueprints/`
- Licensing and activation: `SpaceTradingFX/flask_dashboard/license_manager.py`, `activation_api.py`
- Payments: `SpaceTradingFX/flask_dashboard/payments.py`
- Trading/market/broker adapters: `trading_engine.py`, `forex_data.py`, `mt5_connector.py`
- Data model and migration helper
- : `models.py`, `db_migrate.py`
- Package/deploy configuration: `pyproject.toml`, `Dockerfile`, `docker-compose.yml`
