# Current-State Audit — 2026-09-10

This audit confirms the findings in `REFACTORING_ASSESSMENT.md` and records one additional P0 finding: a tracked legacy demo module contains a plaintext credential. Treat all credentials that have appeared in source control as compromised and rotate them outside this repository.

## Confirmed P0 findings

| Finding | Status before Phase 0 | Evidence |
|---|---|---|
| Passwordless login | Confirmed | Legacy and blueprint login flows authenticate an existing account from an email address alone. |
| Automatic privileged account | Confirmed | `flask_dashboard/app.py` creates an unlimited-premium administrator at import/startup. |
| Public admin page | Confirmed | `GET /admin/ui` has no authorization decorator. |
| Import-side-effect composition | Confirmed | `payments.py`, `admin.py`, and `activation_api.py` self-register; routes are otherwise registered by importing `routes.py`. |
| Production route omission | Confirmed | Docker starts `app:app`; that module does not import `routes.py` or the activation blueprint. |
| Duplicate/no-op payment webhook | Confirmed | `app.py` defines a no-op `/payments/webhook`; `payments.py` defines the actual handler at the same URL. |
| Unmanaged production schema changes | Confirmed | `db.create_all()` runs at import/startup; migration helper only targets SQLite. |
| Plaintext credential in tracked code | Confirmed | Legacy mock-broker code embeds a non-placeholder password. It must be removed and rotated. |

## Material P1 findings

- Legacy routes and blueprints duplicate nearly every web feature and have drifted.
- Packaging is inconsistent: entry point targets a nonexistent function, imports mix package/top-level forms, and dependency manifests disagree.
- Plan/catalog values differ between licensing, payments, and documentation.
- Trading writes simulated trades before durable broker acknowledgement, uses `float` and hard-coded pip assumptions, and has no reconciliation model.
- The global MT5 connector is process-local and unsafe as shared multi-worker state.
- Broad exception swallowing hides failures in authentication-adjacent, database, notification, and broker code.
- Current tests cover only narrow legacy flows; the local Linux environment lacks runnable project dependencies and the committed `venv` is Windows-specific.

## Current runtime topology

```text
Local run.py -> mutates sys.path -> imports app -> imports routes
                                            -> routes imports payments/admin

Docker -> gunicorn app:app -> app only
                           -> no dashboard routes or activation API
```

## Audit conclusion

The project is a Flask dashboard prototype, not yet a safe live-trading system. Phase 0 must resolve access control, deterministic application construction, deployment parity, webhook correctness, and credential exposure before any AI, live broker, or new frontend work.
