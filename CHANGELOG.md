## [10.2.0] — Phase 191 · INNOV-96 · CIL

### Added
- **INNOV-96 Constitutional Integrity Ledger (CIL)** — World-first constitutionally-governed cross-ledger HMAC-chain integrity attestation engine; verifies all ADAAD governance ledgers, seals attestations in an append-only constitutional integrity journal, and escalates violations to HUMAN-0 before any further mutation activity is permitted.
- 10 Hard-class invariants: CIL-VERIFY-0, CIL-CHAIN-0, CIL-HUMAN0-0, CIL-IMMUT-0, CIL-DETERM-0, CIL-SCOPE-0, CIL-AUDIT-0, CIL-ATOMIC-0, CIL-REPLAY-0, CIL-SEAL-0.
- 30-test acceptance suite `tests/test_phase191_cil.py` (T191-CIL-01…30) — 30/30 pass.
- 4 governance artifacts: ILA JSON, plan JSON, tier summary, replay digest.

**Cumulative invariants: 537 | Innovations shipped: 96**

---

## [10.1.0] — Phase 190 · INNOV-95 · MSR

### Added
- **INNOV-95 Mutation Strategy Router (MSR)** — HMAC-chained ledger-sealed router dispatching mutation proposals to constitutional execution strategies via entropy SignalVectors and blast-radius scope enforcement.
- 5 Hard-class invariants: MSR-ROUTE-0, MSR-CHAIN-0, MSR-HUMAN0-0, MSR-SCOPE-0, MSR-ATOMIC-0.
- 30-test acceptance suite (30/30 pass).

### Fixed (P1 deprecations)
- `runtime/innovations_bus.py`: `asyncio.get_event_loop()` → `get_running_loop()`
- `dorkllm/governance_tag_certifier.py`: `datetime.utcnow()` → `datetime.now(timezone.utc)`
- `dorkllm/intelligence.py`: `datetime.utcnow()` → `datetime.now(timezone.utc)`
- `dorkllm/mutation_calibration_engine.py`: `datetime.utcnow()` → `datetime.now(timezone.utc)`
- `app/api/streams.py`: `asyncio.get_event_loop().time()` → `get_running_loop().time()`

**Cumulative invariants: 527 | Innovations shipped: 95**

---

## [9.114.0] — Phase 181 · INNOV-86 · GIR — Governance Implementation Readiness

**Date:** 2026-05-18  **Author:** DEVADAAD · InnovativeAI LLC  **Governor:** DUSTIN L REID

### Added
- INNOV-86 · GIR — Governance Implementation Readiness
- `dorkllm/governance_implementation_readiness.py` — multi-subsystem readiness synthesis engine
- 10 new Hard-class invariants: GIR-CHAIN-0, GIR-DETERM-0, GIR-HUMAN0-0, GIR-READONLY-0, GIR-ATOMIC-0, GIR-SEAL-0, GIR-SCOPE-0, GIR-AUDIT-0, GIR-THRESHOLD-0, GIR-REPLAY-0
- 30-test suite: `tests/test_phase181_gir.py` (T181-GIR-01..30) — 30/30
- Governance artifacts: `artifacts/governance/phase181/` (ILA + HUMAN-0 sign-off)
- `data/gir/` runtime ledger directory

### World-First
First constitutionally-governed multi-subsystem governance readiness synthesis engine to aggregate signals from the full ADAAD stack (CSC/SCSI, CPI pressure, CAL amendments, IIS impact, CAR rollbacks, invariant registry) into a sealed, HMAC-chained Governance Readiness Score attestation gating milestone promotion behind HUMAN-0 explicit authority.

### Governance
- Hard-class invariants: 440 → 450
- Innovations shipped: 85 → 86
- Version: v9.113.0 → v9.114.0
- HUMAN-0 ratification: APPROVED ; DUSTIN L. REID — 2026-05-18
- GPG tag v9.114.0: pending ADAADell ceremony

---

## [9.113.0] — Phase 180 · INNOV-85 · CAR — Constitutional Amendment Rollback
## [9.122.0] — Phase 189 · INNOV-94 · V10ET — V10 Epoch Transition Engine (2026-05-24)
## [10.0.1] — Phase 189 · INNOV-94 · V10ET — V10 Epoch Transition Engine (2026-05-24)

### INNOV-94 · V10ET — V10 Epoch Transition Engine
- Terminal innovation of the v9.x.x governance arc
- Consumes GTC Release Bundle (INNOV-93), independently re-validates Constitutional Merkle Root (V10ET-VERIFY-0)
- Seals v9→v10 epoch boundary as immutable HMAC-chained ledger record (V10ET-CHAIN-0, V10ET-EPOCH-0)
- Emits structured HUMAN-0 Track B runbook before seal (V10ET-HUMAN0-0)
- 5 new Hard-class invariants: V10ET-SCOPE-0, V10ET-CHAIN-0, V10ET-HUMAN0-0, V10ET-EPOCH-0, V10ET-VERIFY-0
- Cumulative Hard-class invariants: 522
- 30/30 acceptance tests passing
- REST endpoints: POST /v10et/seal, GET /v10et/history, GET /v10et/verify-chain, GET /v10et/advisory

## [9.121.0] — Phase 188 · INNOV-93 · GTC — Governance Tag Certifier (2026-05-21)

### INNOV-93 · GTC — Governance Tag Certifier

**World-first:** Constitutionally-governed, Merkle-rooted Release Bundle certifier bridging the GPE GA-READY signal to the v10.0.0 tag ceremony with a mandatory HUMAN-0 ceremony runbook.

**New module:** `dorkllm/governance_tag_certifier.py` (588 lines)
**New router:** `app/api/governance_tag_certifier.py`
**New endpoints:** `POST /gtc/certify`, `GET /gtc/history`, `GET /gtc/verify-chain`, `GET /gtc/advisory`
**Tests:** 30/30 passing (`tests/test_phase188_gtc.py`)

**Hard-class invariants added (+5 → 517 total):**
- `GTC-SCOPE-0` — GTC reads only GPE manifest, VERSION, agent state; never mutates upstream
- `GTC-CHAIN-0` — Release bundle entries form valid HMAC-SHA-256 chain; broken chain halts
- `GTC-HUMAN0-0` — HUMAN-0 ceremony advisory emitted and recorded before bundle is sealed
- `GTC-MERKLE-0` — Constitutional Merkle Root computed deterministically over sorted innovation digests
- `GTC-IMMUT-0` — Release ledger is append-only; entries never modified after write

**Ratified by:** DUSTIN L REID (HUMAN-0) · Governor: InnovativeAI LLC

## [9.120.0] — Phase 187 · INNOV-92 · GPE — GA Promotion Engine

**Date:** 2026-05-17  **Author:** DEVADAAD · InnovativeAI LLC  **Governor:** DUSTIN L REID

### Added
- **INNOV-92 · GPE — GA Promotion Engine** (`dorkllm/ga_promotion_engine.py`)
  - World-first constitutionally-governed GA Promotion Engine; closes the V10 convergence arc
  - Evaluates all seven V10 convergence criteria; verifies PyPI ↔ repo version alignment
  - Directly addresses GA_ALIGNMENT (V10 C7 — the final outstanding convergence criterion)
  - Sealed HMAC-SHA-256 GA Release Manifests in append-only hash-chained ledger
  - HUMAN0_REQUIRED status emitted when all 7 criteria MET and versions aligned
  - HUMAN-0 ratification advisory generated for v10.0.0 General Availability promotion ceremony
  - 12 hard-class invariants: GPE-SCOPE-0 GPE-CHAIN-0 GPE-IMMUT-0 GPE-DETERM-0 GPE-HUMAN0-0
    GPE-AUDIT-0 GPE-PERSIST-0 GPE-SEAL-0 GPE-ALIGN-0 GPE-CRITERIA-0 GPE-READONLY-0 GPE-SNAPSHOT-0
- **REST router** `/api/gpe/*` (assess, status, manifest, verify) · **30/30 tests** `tests/test_phase187_gpe.py`
- **Cumulative invariants: 512** | **Innovations shipped: 92** | **Phases complete: 187**
- **World first**: `phase187-world-first-ga-promotion-engine-v10-c7-alignment`
- **HUMAN-0 action**: publish `adaad-core==9.120.0` to PyPI, then tag `v10.0.0` GA ceremony

---

## [9.119.0] — Phase 186 · INNOV-91 · CLS — CEL Loop Sentinel

**Date:** 2026-05-16  **Author:** DEVADAAD · InnovativeAI LLC  **Governor:** DUSTIN L REID

### Added
- **INNOV-91 · CLS — CEL Loop Sentinel** (`dorkllm/cel_loop_sentinel.py`)
  - World-first constitutionally-governed CEL gate registry and closure monitoring engine
  - Nine frozen CEL gates (G1–G9) evaluated deterministically; closure score 0.0–1.0
  - FULLY_CLOSED status when all gates PASS; HUMAN-0 advisory when closure_score < 1.0
  - HMAC-SHA-256-sealed snapshots in append-only hash-chained ledger; tamper detection on verify
  - Directly satisfies V10 Criterion C5 (CEL Loop Closure, weight 0.125, P0)
  - 12 hard-class invariants: CLS-SCOPE-0 CLS-DETERM-0 CLS-CHAIN-0 CLS-IMMUT-0 CLS-ADVISORY-0
    CLS-SEAL-0 CLS-READONLY-0 CLS-AUDIT-0 CLS-HUMAN0-0 CLS-CLOSURE-0 CLS-PERSIST-0 CLS-SNAPSHOT-0
- **REST router** `/api/cls/*` (scan, status, ledger, verify) · **30/30 tests** `tests/test_phase186_cls.py`
- **Cumulative invariants: 500** | **Innovations shipped: 90** | **Phases complete: 186**
- **World first**: `phase186-world-first-cel-loop-sentinel-v10-c5-closure`

---

## [9.118.0] — Phase 185 · INNOV-90 · CCA — Convergence Certification Auditor

**Date:** 2026-05-15  **Author:** DEVADAAD · InnovativeAI LLC  **Governor:** DUSTIN L REID

### Added
- **INNOV-90 · CCA — Convergence Certification Auditor** (`dorkllm/convergence_certification_auditor.py`)
  - World-first constitutionally-governed V10 convergence certification engine
  - Eight frozen V10 criteria (CCA-CRITERIA-0); Convergence Score 0.0-1.0; V10 Certificate at ≥ 0.875
  - HMAC-SHA-256-sealed certificates, HUMAN-0 advisory gate, append-only ledger, idempotency guard
  - 12 hard-class invariants: CCA-SCOPE-0 CCA-CHAIN-0 CCA-IMMUT-0 CCA-DETERM-0 CCA-THRESHOLD-0
    CCA-AUDIT-0 CCA-SEAL-0 CCA-HUMAN0-0 CCA-CRITERIA-0 CCA-PERSIST-0 CCA-IDEMPOTENT-0 CCA-READONLY-0
- **REST router** `/api/cca/*` · **30/30 tests** `tests/test_phase184_cca.py`
- **World first**: `phase185-world-first-governed-convergence-certification-auditor`

---
