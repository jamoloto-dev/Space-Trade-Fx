# AI Architecture and Governance

## Scope and prohibition

AI is a research and explanation subsystem. It may emit schema-validated `StrategyCandidate`, `SignalCandidate`, `MarketAnalysis`, `ParameterCandidate`, `RiskExplanation`, and `ResearchHypothesis`. It must never receive a money-moving broker tool or final risk authority.

## Future research graph

```text
Collect context -> validate data -> identify regime -> hypothesis
-> compile candidate -> deterministic backtest -> statistical validation
-> risk/overfitting critique -> human approval -> paper candidate
```

The graph has persisted checkpoints and explicit maximum iterations, token/cost budgets, timeout, data boundaries, and human promotion gates. Failed experiments are retained.

## Required controls before implementation

- provider abstraction (`generate`, `structured_generate`, `health`, `usage`);
- output schemas and validation; isolated execution sandbox for generated code;
- prompt/model/workflow versioning and final output hashes;
- audit telemetry without prompts containing secrets or personal data;
- model registry with purpose, owner, data, metrics, approval, deployment, limitations, and rollback;
- deterministic fakes for all AI tests.

AI availability must not affect authentication, risk enforcement, reconciliation, order cancellation, or kill switches. LangGraph is an ADR-backed candidate, not a Phase 0 dependency.
