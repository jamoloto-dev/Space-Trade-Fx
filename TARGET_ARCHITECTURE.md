# Target Architecture

## Guiding rule

AI can generate research, explanations, hypotheses, and typed candidates. It never submits, modifies, or cancels broker orders. Deterministic code owns risk and execution.

```text
AI/ML -> research recommendation -> signal candidate -> deterministic validation
      -> deterministic risk engine -> order intent -> execution gateway
      -> broker adapter -> broker
```

## Near-term: modular Flask monolith

Keep Flask while stabilising the product. A single `create_app()` composes configuration, extensions, logging, database, migrations, authentication, CSRF, rate limiting, health endpoints, and explicit blueprints. Controllers are thin adapters over application services.

```text
flask_dashboard/
  factory + extensions
  blueprints: identity, licenses, payments, trading, mobile, admin
  services: application orchestration
  models/repositories: transactional persistence
  integrations: Stripe, SMTP, market data, MT5
```

No module may register a route as an import side effect. No global in-memory connection/state is a source of truth across workers.

## Target logical boundaries

```text
Identity | Licensing | Payments | Notifications | Referrals
Trading: strategies | signals | risk | OMS | execution | portfolio | reconciliation
Research: datasets | backtests | experiments | validation | reports
AI: provider | graphs | tools | guardrails | evaluation | registry
Integrations: brokers | market data | payments | email
```

Extraction into services occurs only when independently justified by load, reliability, security isolation, or deployment needs. PostgreSQL remains transactional source of truth; Redis is ephemeral/coordination only; object storage holds large artifacts.

## Future decision points

Create ADRs before selecting FastAPI coexistence/migration, message broker, time-series database, LangGraph, Next.js, FIX, and service extraction. No big-bang framework or microservice rewrite.
