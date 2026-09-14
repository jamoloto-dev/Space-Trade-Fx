# SpaceTradingFX staged roadmap

## Completed in this foundation / automated-paper stage

- Keep the application paper-only, retain the central Flask factory, payment
  verification, authentication, audit events and order history.
- Align the ORM with existing broker-correlation migration columns and add a
  forward migration for a database worker lease.
- Use one paper-FX catalogue, explicit supported source timeframes, fixed lot
  sizing, a deterministic risk gate, and explicit manual versus automated
  paper modes.
- Add a standalone lease-protected lifecycle worker for deterministic signal
  submission, P/L updates, SL/TP handling and local-ledger reconciliation.

## Stage 2 — historical evaluation (not implemented)

Build versioned historical-data ingestion with source/licence/provenance,
instrument metadata, timezone-normalised bid/ask bars, gaps and corporate or
provider corrections. Use an event-driven simulator that applies spread,
commissions, swaps where applicable, slippage, order timing, rejection and
fill assumptions. Share intent/risk logic with paper execution.

Store immutable dataset and strategy versions. Evaluate chronologically with
train/validation/test separation, leakage checks, out-of-sample reports and
walk-forward windows. Report return, drawdown, turnover, exposure, expectancy
and cost sensitivity without interpreting a backtest as future performance.

## Stage 3 — ML experiments (not implemented)

Start in shadow mode with a market-regime filter for deterministic RSI/MACD
signals. Features must be observable at decision time (lagged returns,
volatility, trend and spread); labels must occur after the decision horizon.
Compare against the unfiltered deterministic baseline after modeled costs.

Version datasets, feature code, model binary, training configuration and
metrics. Use chronological splits and walk-forward validation. Promote only
after shadow-mode evaluation; on missing features, model failure, drift or
rollback, reject the automated intent or use the deterministic baseline per
an explicitly tested policy. An LLM journal assistant, if added, remains
advisory with no execution credentials or order authority.

## Stage 4 — broker demo integration (not implemented)

First decide broker, demo-account terms, operating system, hosting, supported
instruments, account currency and operational ownership. Define an adapter
contract for authenticated connection health, quotes, instrument metadata,
orders, fills, positions, cancel/modify, history and reconciliation. Keep
adapter credentials isolated. Validate only against a demo account after a
separate approval; do not assume MT5 is the final broker.

## Stage 5 — controlled live execution (not implemented)

Require explicit owner authorisation after demo reconciliation, tested
idempotency/recovery, enforced risk limits, kill switches, monitoring/alerts,
credential isolation, incident runbooks and independent release review.
Technical tests and strategy results are not profitability evidence; no fixed
profit threshold is a release gate.

## Decisions deliberately unresolved

- Historical data supplier, redistribution rights, retention period and the
  authoritative instrument/session calendar.
- Paper and eventual broker account currency, conversion method, margin model,
  and the unit used for strategy-level risk reporting.
- Broker, demo-account terms, supported operating system/hosting, adapter
  ownership, and operational response responsibility.
- Any criterion for moving from shadow evaluation to demo or live operation;
  this requires explicit owner approval, not an assumed performance target.
