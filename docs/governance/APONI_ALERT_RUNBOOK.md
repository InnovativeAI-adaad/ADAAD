# Aponi Governance Alert Runbook

## Scope

Operational guidance for deterministic alerts from `GET /alerts/evaluate`.

## Alert Buckets

- `critical`: immediate governance intervention required.
- `warning`: investigate and monitor closely.
- `info`: informative signal; no immediate intervention.

## Current Alert Codes

- `instability_critical`: instability index above critical threshold.
- `instability_warning`: instability index above warning threshold.
- `replay_failure_warning`: replay failure rate above warning threshold.
- `instability_velocity_spike`: large absolute instability velocity delta.

## Response Guidance

1. **critical**
   - Pause autonomous mutation promotion workflows.
   - Review `/risk/instability`, `/risk/summary`, and `/replay/divergence`.
   - Run `GET /policy/simulate` against candidate strict policies for containment planning.
2. **warning**
   - Increase monitoring cadence.
   - Validate replay integrity and recent semantic drift categories.
3. **info**
   - Record as telemetry trend; no immediate action unless correlated with warning/critical signals.

## Determinism Invariants

- Alerts are read-only projections.
- Alert outputs are deterministic functions of persisted telemetry and fixed thresholds.
- Alert routing does not mutate governance policy or mutation authority.
