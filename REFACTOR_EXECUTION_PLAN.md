# Refactor Execution Plan

## Phase 0 — security containment (current work)

1. Replace unsafe authentication and implicit admin creation.
2. Centralise application construction and route registration.
3. Make webhook/admin/activation registration and authorization deterministic.
4. Correct Docker/CLI startup parity, remove path hacks, remove exposed credentials.
5. Add route-map and security regression tests; add Alembic foundation and remove `create_all` from startup.

**Exit gate:** all P0 tests pass; no automatic admin/passwordless login/duplicate webhook/import-side-effect registration remains; a deployment uses the same factory route map as local execution.

## Phase 1 — foundation

Dependency/lockfile cleanup, PostgreSQL migration testing, structured logging, configuration validation, CI quality gates, and ADRs for factory/migrations/HTTP strategy.

## Phase 2 — domain integrity

Service boundaries; canonical plan catalog; state transitions; UTC/Decimal migration; constraints and idempotency; audit events and outbox.

## Phase 3 — paper-first trading

Market and broker protocols, risk engine, OMS, paper broker, ledger, portfolio, reconciliation, and kill switches.

## Phase 4 — research and validation

Historical data, deterministic backtesting, experiment registry, walk-forward/stress/overfitting analysis, and reproducible reporting.

## Phase 5 — governed AI

Provider abstraction, guardrails, LangGraph ADR/workflow, sandboxed research, model registry, evaluations, and approval gates.

## Later phases

Progressive modern dashboard, MT5 machine integration, restricted read-only/paper operation, then institutional broker readiness. Live trading requires a separate risk/security/governance approval and is explicitly out of scope for this plan.
