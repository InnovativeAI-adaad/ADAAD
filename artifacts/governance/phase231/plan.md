# Phase 231 Plan — INNOV-136 · CAMS

## Objective

Implement the Constitutional Autonomous Monitoring Sentinel (CAMS) — Arc III ACI Module 07.
Closes the observability gap in Arc III: CADE decides, CAPE executes, CALI learns —
CAMS continuously watches CHI health and gates CRITICAL findings behind HUMAN-0.

## Scope

- `dorkllm/constitutional_autonomous_monitoring_sentinel.py` — core module
- `app/api/cams.py` — FastAPI router, 9 endpoints
- `tests/test_phase231_cams.py` — 30-test acceptance suite
- 4 governance artifacts under `artifacts/governance/phase231/`
- Four-surface version bump: 10.41.0 → 10.42.0

## Subsystems

| Subsystem | Role | Key Invariants |
|---|---|---|
| CHIMonitor | Validates and ingests raw CHI samples from CASL | CAMS-SAMPLE-0 |
| TrendDetector | Deterministic rolling-window trend classification | CAMS-CLASS-0, CAMS-DETERM-0, CAMS-WINDOW-0 |
| AlertEngine | Raises and tracks CRITICAL alerts; HUMAN-0 acknowledgement gate | CAMS-ALERT-0, CAMS-HUMAN0-0, CAMS-IMMUT-0 |
| MonitoringLedger | HMAC-SHA-256 append-only observation ledger | CAMS-CHAIN-0, CAMS-APPEND-0 |
| CAMSAuditor | Parallel HMAC-chained audit log | CAMS-AUDIT-0 |
| CAMSEngine | Facade coordinating all subsystems | All |

## API Endpoints (9)

POST /cams/sample · POST /cams/alerts/{id}/acknowledge  
GET /cams/alerts/{id} · GET /cams/alerts · GET /cams/alerts/open/all  
GET /cams/ledger · GET /cams/verify-chain · GET /cams/audit · GET /cams/status

## Pre-Phase Drift Corrections (committed to main prior to this branch)

- `adaad/__init__.py` / `adaad_core/__init__.py` re-synced 10.40.0 → 10.41.0
- Phase 230 CAVE router (`app/api/cave.py`) was built but never mounted in
  `server.py` — wired in, 12 endpoints confirmed live
- Phase 230 `pytest.ini` marker (`phase230`/`cave`) had never been registered — added
  alongside the new `phase231`/`cams` markers in this phase's commit
