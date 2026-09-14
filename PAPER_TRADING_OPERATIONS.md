# Automated paper trading operations

## Boundary and assumptions

This is a local **paper simulation**. It cannot submit broker orders. A paper
order is filled at the latest valid source candle close observed by the worker
or manual request. It does not model bid/ask,
spread, commission, swaps, slippage, latency, partial fills, margin, or FX
conversion. P/L is displayed as USD-assumed simulated account units and is not
evidence of profitability.

Simulation is the default market-data mode. Set `MARKET_DATA_PROVIDER=alphavantage`
only to opt into external analysis data; this does not change execution mode.
Only 1M, 5M, 15M, and 1H source intervals are supported. Other intervals are
rejected rather than relabelled.

## Start and operate

1. Apply migrations: `alembic upgrade head`.
2. In the dashboard, select supported symbols, set fixed paper lot sizes in the
   mobile Quotes page, enable “Allow new paper orders,” then explicitly enable
   deterministic automated paper signals in Preferences.
3. Start exactly one lifecycle process:

   ```bash
   spacetradingfx-paper-worker --interval 30
   ```

   It owns a database lease. A second process reports standby and does not
   process transitions. The web process never starts a scheduler. The supplied
   Compose configuration defines one `paper-worker` service; do not scale it.
4. Check `/health/live`, `/health/ready`, and `/health/paper-worker`.

Set `PAPER_TRADING_KILL_SWITCH=true` to stop new manual and automated paper
submissions. Monitoring and close management continue. Clearing the setting
requires restarting/reconfiguring the application; it can never enable live
trading.

## Recovery and deterministic demonstration

Orders, events, worker leases, and reconciliation runs are database-backed.
After a worker restart, start one worker again; it resumes open-position quote
monitoring and local-ledger reconciliation. The worker does not contact a
broker and does not repair mismatches silently.

The deterministic test demonstration is:

```bash
.venv/bin/python -m pytest SpaceTradingFX/tests/test_paper_automation.py -q
```

Expected result: seven passing tests. They demonstrate one automated `EURUSD`
paper BUY from a fixed 2024-01-02 synthetic bar; a second cycle creates no
duplicate order, a simulated 1.10400 quote closes the BUY at its 40-pip target,
and a competing worker remains standby.
