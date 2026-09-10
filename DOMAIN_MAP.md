# Domain Map

## Current modules and target ownership

| Current area | Target domain | Phase status |
|---|---|---|
| `models.User`, login/admin/OAuth | Identity | Phase 0 containment; later service extraction |
| `license_manager`, activation routes | Licensing | Canonical catalog and state transitions later |
| `payments`, Stripe webhook | Payments | Phase 0 registration/webhook safety; transactional idempotency later |
| `mentor_system`, `notifications` | Commercial/engagement | Preserve, then extract behind services |
| `trading_engine`, `forex_data`, `mt5_connector` | Trading/integrations | Simulation-only; extract in Phase 4 |
| `space_trading_fx` mock package | Legacy/demo | Quarantine or retire after behavior is audited |

## Canonical trading model (future)

```text
Strategy -> StrategyVersion -> Signal -> TradeIntent -> RiskDecision
  -> Order -> Execution -> Fill -> Position -> Portfolio
                              -> TradeLedgerEntry / ReconciliationRecord
```

Every transition is persisted, versioned, and attributable. Financial values use `Decimal` and PostgreSQL `NUMERIC`; timestamps are UTC-aware. Brokers are adapters behind a broker-independent protocol, beginning with a paper broker.

## Canonical commercial model (future)

```text
LicensePlan -> FeatureEntitlement / UsageLimit
License -> LicenseActivation -> Device/BrokerAccountActivation
CheckoutSession -> PaymentIntent -> PaymentEvent -> Invoice/Refund
```

One product catalog supplies plan, currency, price, duration, features, trade/broker/AI limits, and activation limits to UI, Stripe, API, and validation.
