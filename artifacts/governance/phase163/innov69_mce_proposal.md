# INNOV-69 · MCE — Mutation Calibration Engine
## Phase 163 Feature Proposal
**Date:** 2026-04-30  
**Author:** DEVADAAD · InnovativeAI LLC  
**Session:** ADAAD-SESSION-20260430-Architect  
**Status:** PROPOSED — awaiting HUMAN-0 ratification

---

## 6.1 Purpose

**What:** MCE (Mutation Calibration Engine) closes the governance analytics feedback
loop by recording actual mutation outcomes against MIA pre-admission predictions and
using outcome deltas to continuously calibrate MIA's composite scoring weights.

**Why:** MIA (INNOV-68) scores mutations before execution with fixed weights
(_W_PRECEDENT=0.25, _W_INVARIANT=0.35, _W_CSI=0.20, _W_FORECAST=0.20). These
weights are static — they do not adapt when MIA's predictions diverge from actual
outcomes. Over time, fixed weights produce scoring drift. MCE provides the
calibration signal that makes MIA a learning governance system.

**Innovation number:** INNOV-69  
**Ships in phase:** Phase 163  
**CEL steps modified:** Step 05 (Scoring), Step 06 (Ledger Write), Step 07 (Governance Review)

---

## 6.2 Inputs / Outputs

**Input dataclass:** MutationOutcome
  - impact_id: str          (references MIA ImpactAssessment)
  - mutation_id: str
  - actual_result: OutcomeClass  (APPROVED / REVERTED / BLOCKED_POST_GATE / NEUTRAL)
  - execution_phase: int
  - csi_delta: float        (CSI score change post-execution)
  - invariant_violations: int
  - submitted_by: str

**Output dataclass:** CalibrationRecord
  - calibration_id: str     (deterministic from impact_id + actual_class + phase)
  - impact_id: str
  - prediction_tier: str    (MIA's original tier)
  - actual_class: str
  - prediction_error: float (0.0-1.0)
  - weight_delta: dict      ({precedent, invariant, csi, forecast})
  - cumulative_weights: dict
  - prev_digest: str        (SHA-256 of previous record canonical JSON)
  - chain_hash: str         (HMAC-SHA-256 chain link)
  - ledger_seq: int
  - timestamp_utc: str

**Ledger:** ledger/mutation_calibration.jsonl (append-only)
**Weight store:** governance/mce_weights.json (Tier-1 guarded)

---

## 6.3 Failure Modes

| Failure | Exception Class | Ledger Entry | Recovery | CEL Effect |
|---|---|---|---|---|
| Chain break | MCEChainError(RuntimeError) | {type: chain_break} | Halt; no weight write | P1 halt |
| Weight sum != 1.0 | MCEWeightError(RuntimeError) | {type: weight_invalid} | Reject; retain prior | P1 halt |
| impact_id missing | MCELookupError(RuntimeError) | {type: impact_missing} | Skip; log | Warning |
| Caller not in VALID_SOURCES | MCESourceError(RuntimeError) | {type: source_violation} | Reject | P1 halt |
| Delta > ±0.05 per weight | MCEDriftError(RuntimeError) | {type: drift_exceeded} | Clamp to bound | Warning |
| Cumulative shift >0.10 | MCEHuman0Gate (CGTH emit) | HUMAN0_AUTHORISATION event | Pause write for HUMAN-0 | Tier-0 gate |

---

## 6.4 Governance

**Invariant tier:** Tier-1 (Hard-class)  
**human_signoff_token required:** Yes — cumulative weight shift >0.10 on any dimension  
**VALID_SOURCES:** frozenset({"cel_loop", "governance_review", "test_harness", "phase163_migration"})  
**Audit log:** ledger/mutation_calibration.jsonl  
**CGTH events:** MCE_CALIBRATION_CYCLE, MCE_WEIGHT_UPDATED

**Hard-class invariants (5):**
- MCE-CHAIN-0   : calibration ledger HMAC-chained; chain break aborts all writes
- MCE-WEIGHT-0  : weights must sum to 1.0 ± 1e-9; invalid sums rejected
- MCE-DRIFT-0   : per-cycle delta capped at ±0.05 per dimension
- MCE-HUMAN0-0  : cumulative shift >0.10 requires HUMAN-0 sign-off via CGTH
- MCE-DETERM-0  : calibration_id deterministic from impact_id + actual_class + phase

---

## 6.5 Optimization Targets

| Target | Threshold |
|---|---|
| Calibration coverage | ≥80% of MIA-assessed mutations have recorded outcome within 5 phases |
| Prediction error reduction | MIA mean absolute error decreases ≥10% over 20-calibration window |
| Weight stability | No single weight shifts >0.15 cumulative across any 10-calibration window |
| Chain integrity | 100% of calibration ledger entries pass chain verification |
| Acceptance test pass rate | 30/30 on first execution |

---

## 6.6 Acceptance Test Suite (30 tests)

Unit (10): calibration_id determinism, weight sum invariant, drift clamp,
chain-break abort, VALID_SOURCES rejection, missing impact_id, HUMAN-0
threshold gate, weight persistence, OutcomeClass enum, prev_digest link.

Integration (10): MIA-to-MCE roundtrip, CGTH calibration event, CGTH weight
event, weight reload on restart, 20-cycle error reduction, CEL Step 05 wire,
CEL Step 07 calibration, API outcome POST, API weights GET, API chain verify.

Invariant (10): MCEChainError is RuntimeError, MCEWeightError is RuntimeError,
CalibrationRecord has prev_digest, append-only JSONL write, hmac.compare_digest
used, VALID_SOURCES is frozenset, MCE_* constants block present, atomic weight
file write, calibration_id from canonical JSON, HUMAN0_AUTHORISATION before write.

---

## 6.7 Four-File Version Bump Specification

Bump type: minor
From: 9.95.0 → To: 9.96.0

VERSION:                 9.96.0
pyproject.toml:          version = "9.96.0"
CHANGELOG.md header:     ## [9.96.0] - Phase 163 . INNOV-69 . MCE - Mutation Calibration Engine
.adaad_agent_state.json: "version": "9.96.0", "phase": 163, "current_phase": 163

---

## 6.8 Track B Runbook (HUMAN-0 on ADAADell)

```bash
git fetch origin feat/phase163-mce
git log --oneline origin/feat/phase163-mce

git checkout main
git merge --no-ff origin/feat/phase163-mce \
  -m "merge(phase163): INNOV-69 · MCE — Mutation Calibration Engine · v9.96.0"

git tag -s v9.96.0-phase163 \
  -m "Phase 163: INNOV-69 · MCE — Mutation Calibration Engine — closes MIA feedback loop"
# GPG key: 4C95E2F99A775335B1CF3DAF247B015A1CCD95F6

git push origin main
git push origin v9.96.0-phase163

git verify-tag v9.96.0-phase163
git ls-remote origin refs/tags/v9.96.0-phase163
```

---
*INNOV-69 MCE Proposal · ADAAD-SESSION-20260430-Architect · Awaiting HUMAN-0 ratification*
