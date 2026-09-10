# Security Remediation Plan

## Phase 0 controls

1. Remove email-only login and implicit registration. Require password registration/login using Werkzeug password hashes; reserve MFA integration points for a later identity provider or TOTP implementation.
2. Remove automatic administrator creation. Provide an explicit, interactive `bootstrap_admin` command. Never accept or log bootstrap passwords in source/configuration.
3. Make all admin endpoints—including the HTML UI—require authenticated admin authorization.
4. Build the application only through an explicit factory and centrally register all blueprints once.
5. Remove duplicate payment webhook rules. The actual webhook alone is CSRF-exempt and verifies Stripe signatures; test configuration is explicitly separate.
6. Remove committed plaintext credentials; rotate any credential exposed in source/history. Maintain `.env` exclusion and never print secrets.
7. Disable live-trading defaults (`LIVE_TRADING_ENABLED=false`, `MT5_ORDER_EXECUTION_ENABLED=false`) until a later reviewed phase.
8. Replace schema creation at process startup with Alembic migration management. Production must fail fast for missing security configuration.

## Security tests required in Phase 0

- Unknown/known account cannot authenticate without a valid password.
- No administrator exists merely because the process starts.
- Non-admin and anonymous callers cannot access admin UI/actions.
- Real webhook endpoint is unique, CSRF-exempt, and rejects unsigned/invalid payloads.
- Production and development factories expose the same intended route map.
- Docker starts the same factory application.

## Rotation and incident action

Rotate Stripe, SMTP, broker, database, license-signing, session/JWT, and AI-provider credentials before exposing a new deployment. Review Git history and deployment logs; revoke broker access if the discovered credential was ever active. This repository must not record rotation values or secrets.
