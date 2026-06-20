# Phase 232 Plan — INNOV-137 · CACG

## Objective

Implement the Constitutional Autonomous Cycle Governor (CACG) — Arc III ACI
Module 08, the Arc III governance capstone per ROADMAP.md. CACG does not
replace any existing Arc III module; it orchestrates them, enforcing
deterministic per-stage timeouts and routing stalled cycles to HUMAN-0.

## Scope

- `dorkllm/constitutional_autonomous_cycle_governor.py` — core module
- `app/api/cacg.py` — FastAPI router, 12 endpoints
- `tests/test_phase232_cacg.py` — 30-test acceptance suite
- 4 governance artifacts under `artifacts/governance/phase232/`
- Four-surface version bump: 10.42.0 → 10.43.0

## Subsystems

| Subsystem | Role | Key Invariants |
|---|---|---|
| CycleOrchestrator | Opens cycles, enforces the fixed 7-stage order | CACG-STAGE-0, CACG-IMMUT-0 |
| TimeoutEnforcer | Deterministic per-stage stall detection | CACG-DETERM-0, CACG-TIMEOUT-0 |
| EscalationEngine | Raises and tracks HUMAN-0 escalations | CACG-ESCALATE-0, CACG-HUMAN0-0, CACG-IMMUT-0 |
| CycleLedger | HMAC-SHA-256 append-only cycle-transition ledger | CACG-CHAIN-0, CACG-APPEND-0 |
| CACGAuditor | Parallel HMAC-chained audit log | CACG-AUDIT-0 |
| CACGEngine | Facade coordinating all subsystems | All |

## The Fixed 7-Stage ACI Cycle (CACG-STAGE-0)

CASL → CADE → EXECUTE (CAPE or CAVE) → CAOE → CALI → CACP → CAMS

## API Endpoints (12)

POST /cacg/cycle/open · POST /cacg/cycle/{id}/advance · POST /cacg/cycle/{id}/complete
POST /cacg/cycle/{id}/check-timeout · POST /cacg/escalation/{id}/resolve
GET /cacg/cycle/{id} · GET /cacg/cycles · GET /cacg/cycles/open · GET /cacg/escalations
GET /cacg/verify-chain · GET /cacg/audit · GET /cacg/status

## Implementation Note — Ledger Snapshot Fix

Initial implementation stored a live `CycleRecord` reference inside each
`CycleLedgerEntry`. Because `CycleRecord` continues to mutate across
subsequent `advance()`/`complete()` calls on the same cycle, re-deriving a
prior entry's hash from that live reference produced a different digest than
the one computed at append time, breaking `verify_chain()`. Caught in
pre-commit smoke testing; fixed by snapshotting `status`/`stage_index` as
plain immutable fields on the ledger entry at append time rather than
referencing the mutable record.
