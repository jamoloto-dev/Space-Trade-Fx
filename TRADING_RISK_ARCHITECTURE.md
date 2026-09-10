# Trading and Risk Architecture

## Safety model

The current dashboard is simulation-only. It must not be presented as live execution. A future execution path is:

```text
validated signal -> TradeIntent (immutable ID/idempotency key)
-> deterministic RiskDecision -> Order state machine -> BrokerAdapter
-> broker acknowledgement/fills -> reconciliation -> ledger/position
```

Failure defaults to **stop new risk**. `Global`, `Account`, `Strategy`, and `Broker` kill switches prevent new submissions immediately.

## Deterministic risk checks

Account/trade risk, exposure by symbol/currency/correlation, leverage, free margin, position count, daily loss, drawdown, loss streak, spread, slippage, market session, stale data, duplicate intent, price sanity, and latency limits are evaluated in code before submission. AI may explain a decision but cannot override it.

## Broker and market adapters

`PaperBrokerAdapter` is first. `MT5BrokerAdapter` follows it; `FIXBrokerAdapter` is future work. Adapters expose health, account/instrument/quote queries, orders, executions, positions, cancel/modify, and reconciliation. MT5 EA authentication is machine authentication bound to license, account, server, and installation—not browser cookies or dashboard passwords.

## Research and numerical rules

Backtests are event-driven and deterministic, model spread/commission/slippage/latency/swaps/gaps/rejections, and retain reproducible experiment evidence. Use `Decimal` and intentional `NUMERIC` precision for money, prices, quantities, fees, and P&L. Instrument metadata defines pip/tick/contract/volume/session behavior; no universal pip formula is permitted.
