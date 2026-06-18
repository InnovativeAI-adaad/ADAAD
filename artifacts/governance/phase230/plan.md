# Phase 230 Plan — INNOV-135 · CAVE

## Objective

Implement the Constitutional Autonomous Verdict Executor (CAVE) — Arc III ACI Module 06.
Fills the ROADMAP debt item: HOLD/REJECT/DEFER verdict enforcement has no execution path.
CADE issues verdicts; CAVE enacts them with constitutional guarantees.

## Scope

- `dorkllm/constitutional_autonomous_verdict_executor.py` — core module (639 lines)
- `app/api/cave.py` — FastAPI router, 11 endpoints (172 lines)
- `tests/test_phase230_cave.py` — 30-test acceptance suite (415 lines)
- 4 governance artifacts under `artifacts/governance/phase230/`
- Four-surface version bump: 10.40.0 → 10.41.0

## Subsystems

| Subsystem | Role | Key Invariants |
|---|---|---|
| VerdictRouter | CADE verdict validation and routing | CAVE-SCOPE-0, CAVE-ORIGIN-0, CAVE-DETERM-0 |
| QuarantineEngine | REJECT/DEFER immutable sealing + HUMAN-0 release | CAVE-QUARANTINE-0, CAVE-HUMAN0-0, CAVE-IMMUT-0 |
| CHIReEvaluator | Deterministic HOLD → CHI re-eval trigger issuance | CAVE-REEVAL-0, CAVE-DETERM-0 |
| QuarantineLedger | HMAC-SHA-256 append-only verdict ledger | CAVE-CHAIN-0, CAVE-APPEND-0 |
| CAVEAuditor | Parallel HMAC-chained audit log | CAVE-AUDIT-0 |
| CAVEEngine | Facade coordinating all subsystems | All |

## API Endpoints (11)

POST /cave/execute · POST /cave/release/{id} · POST /cave/reeval/{id}/complete  
GET /cave/record/{id} · GET /cave/records · GET /cave/quarantined  
GET /cave/trigger/{id} · GET /cave/triggers · GET /cave/triggers/pending  
GET /cave/verify-chain · GET /cave/audit · GET /cave/status
