# Governance Incident Scenario Narratives

These narratives are rehearsal-grade operator drills intended to complement the existing governance runbooks. They are deterministic, artifact-first, and fail-closed by default.

## 1) Replay divergence narrative

### Trigger signals
- `GET /alerts/evaluate` emits `replay_failure_warning` with rising replay failure rate.
- `GET /replay/divergence` reports one or more epochs with `decision: fail_closed`.
- `GovernanceDecisionEvent` entries show `reason: replay_divergence`.

### Exact artifact locations
- Runtime lineage ledger directory: `security/ledger/`
- Runtime ledger implementation reference: `runtime/evolution/lineage_v2.py`
- Replay divergence endpoint implementation: `ui/aponi_dashboard.py` (`/replay/divergence`, `/replay/diff`)

### Expected command outputs
```bash
curl -fsS "http://localhost:5000/replay/divergence"
```
Expected shape includes:
- `ok: true`
- `decision: "fail_closed"` or an explicit divergence summary payload

```bash
python - <<'PY'
from runtime.evolution.lineage_v2 import LineageLedgerV2
ledger = LineageLedgerV2()
print("entries", len(ledger.read_all()))
PY
```
Expected output prefix:
- `entries ` followed by a non-negative integer

### Escalation checkpoints
- Escalate to governance owner if divergence spans more than one epoch.
- Escalate to security lead if hash-chain integrity verification fails.
- Escalate to release authority before any replay-bypass request.

### Recovery completion criteria
- `/replay/divergence` returns no active divergence.
- New governance decisions no longer emit `fail_closed` for replay reasons.
- Post-recovery replay preflight succeeds in strict mode.

## 2) Governance halt narrative

### Trigger signals
- Mutation requests are denied with governance fail-closed reason.
- `GovernanceDecisionEvent` indicates halt/fail-closed state.
- `/risk/summary` and `/alerts/evaluate` both indicate elevated governance risk.

### Exact artifact locations
- Governor logic reference: `runtime/evolution/governor.py`
- Governance recovery runbook: `docs/governance/fail_closed_recovery_runbook.md`
- Alert triage runbook: `docs/governance/APONI_ALERT_RUNBOOK.md`
- Risk and alert endpoint implementation: `ui/aponi_dashboard.py` (`/risk/summary`, `/alerts/evaluate`)

### Expected command outputs
```bash
curl -fsS "http://localhost:5000/risk/summary"
```
Expected shape includes:
- `ok: true`
- governance-risk fields for current window

```bash
curl -fsS "http://localhost:5000/metrics/review-quality?limit=500&sla_seconds=86400"
```
Expected shape includes:
- review latency and SLA coverage fields for operator checkpointing

```bash
curl -fsS "http://localhost:5000/alerts/evaluate"
```
Expected shape includes:
- `ok: true`
- `alerts` array grouped by severity (`critical`/`warning`/`info`)

### Escalation checkpoints
- Immediate escalation when halt blocks production mutation queue.
- Escalate if halt persists beyond one review SLA window.
- Require multi-party governance sign-off for recovery signature issuance.

### Recovery completion criteria
- Governor exits fail-closed using approved recovery signature flow.
- Mutation queue returns to controlled acceptance (not blanket rejection).
- Audit trail includes decision reason, approvers, and timestamped recovery action.

## 3) Mutation rejection narrative

### Trigger signals
- Mutation submissions repeatedly return rejection reasons.
- Policy simulation predicts rejection for candidate mutation class.
- Rejections correlate with policy/rule updates or lineage continuity failures.

### Exact artifact locations
- Mutation lifecycle policy spec: `docs/governance/mutation_lifecycle.md`
- Policy simulation endpoint implementation: `ui/aponi_dashboard.py` (`/policy/simulate`)
- Rule validation and deterministic checks: `runtime/constitution.py`

### Expected command outputs
```bash
curl -fsS "http://localhost:5000/policy/simulate?profile=strict"
```
Expected shape includes:
- `ok: true`
- deterministic policy verdict fields

```bash
python - <<'PY'
from runtime.constitution import VALIDATOR_REGISTRY
print("validators", len(VALIDATOR_REGISTRY))
PY
```
Expected output prefix:
- `validators ` followed by a positive integer

### Escalation checkpoints
- Escalate when rejection rate exceeds the current governance SLO threshold.
- Escalate to policy owners when rejection reason distribution changes abruptly.
- Escalate to incident commander if rejection is caused by lineage integrity faults.

### Recovery completion criteria
- Policy simulation and live verdicts converge for representative samples.
- Rejection rate returns to baseline band with no invariant violations.
- No unauthorized policy override is used to clear backlog.

## 4) Instability spike narrative

### Trigger signals
- `GET /alerts/evaluate` emits `instability_critical` or `instability_velocity_spike`.
- `GET /risk/instability` crosses warning/critical thresholds.
- Drift in instability velocity is sustained across consecutive windows.

### Exact artifact locations
- Alert endpoint implementation: `ui/aponi_dashboard.py` (`/alerts/evaluate`)
- Instability endpoint implementation: `ui/aponi_dashboard.py` (`/risk/instability`)
- Alert policy model: `docs/governance/APONI_V2_FORENSICS_AND_HEALTH_MODEL.md`

### Expected command outputs
```bash
curl -fsS "http://localhost:5000/risk/instability"
```
Expected shape includes:
- `ok: true`
- instability index and threshold comparison fields

```bash
curl -fsS "http://localhost:5000/alerts/evaluate"
```
Expected shape includes:
- one or more instability-related alert codes

### Escalation checkpoints
- Escalate immediately on `critical` severity.
- Escalate if warning persists for two consecutive review intervals.
- Escalate to rollback authority when instability trend worsens after containment policy.

### Recovery completion criteria
- Instability index returns below warning threshold for agreed hold period.
- No new `instability_critical` alerts during hold period.
- Containment policy decisions are archived with deterministic replay evidence.

## 5) Ledger corruption recovery narrative

### Trigger signals
- Integrity check raises `lineage_hash_mismatch`, `lineage_prev_hash_mismatch`, or JSON corruption.
- Append operations fail after corruption is detected.
- Replay or governance checks fail-closed due to lineage integrity error.

### Exact artifact locations
- Ledger implementation and integrity checks: `runtime/evolution/lineage_v2.py`
- Ledger directory: `security/ledger/`
- Integrity regression tests: `tests/test_lineage_v2_integrity.py`

### Expected command outputs
```bash
python - <<'PY'
from runtime.evolution.lineage_v2 import LineageLedgerV2
ledger = LineageLedgerV2()
ledger.verify_integrity()
print("lineage_integrity:ok")
PY
```
Expected output:
- `lineage_integrity:ok` for healthy ledger, otherwise deterministic integrity exception.

```bash
pytest -q tests/test_lineage_v2_integrity.py
```
Expected output includes:
- passing integrity test cases for valid-chain and corruption-detection paths

### Escalation checkpoints
- Escalate to security incident process on confirmed tamper evidence.
- Escalate to governance board before any manual ledger surgery.
- Escalate to release manager before resuming mutation writes.

### Recovery completion criteria
- Integrity verification passes on recovered ledger artifact.
- Replay divergence checks and governance health checks return clean.
- Incident evidence bundle is archived and immutable export is recorded.
