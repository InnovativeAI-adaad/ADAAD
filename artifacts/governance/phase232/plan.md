# Phase 232 Plan — INNOV-137 · CACG — Constitutional Autonomous Cycle Governor

**Arc III ACI Module 08 — Governance Capstone**

## Objective

CACG closes the Arc III outer governance loop. While CACP proves per-cycle convergence and CAMS monitors live CHI health, CACG governs the *cycle lifecycle itself*: starting cycles, enforcing stage-level timeout contracts, detecting stalls, escalating to HUMAN-0 on constitutional violations, and publishing sealed HMAC-chained governance proofs.

## Architecture

| Subsystem | Invariants | Responsibility |
|---|---|---|
| `TimeoutEnforcer` | CACG-TIMEOUT-0, CACG-STAGES-0, CACG-DETERM-0 | Validate timeouts; deterministic stage outcome classification |
| `CycleGovernanceLedger` | CACG-CHAIN-0, CACG-APPEND-0, CACG-PROOF-0 | HMAC-SHA-256-chained append-only sealed cycle records |
| `EscalationEngine` | CACG-HUMAN0-0, CACG-IMMUT-0 | Issue + acknowledge HUMAN-0 escalations |
| `CACGAuditor` | CACG-AUDIT-0 | Parallel HMAC-chained audit log |
| `CACGEngine` | All | Facade coordinating all subsystems |

## API Surface (10 endpoints)

```
POST   /cacg/cycles/start
POST   /cacg/cycles/{id}/stages
POST   /cacg/cycles/{id}/close
GET    /cacg/cycles/{id}
GET    /cacg/cycles/active/all
POST   /cacg/escalations/{id}/acknowledge
GET    /cacg/escalations/{id}
GET    /cacg/ledger
GET    /cacg/verify-chain
GET    /cacg/audit
GET    /cacg/status
```

## ACI Pipeline Stages Governed (8)

CASL → CADE → CAPE → CAVE → CAOE → CALI → CACP → CAMS
