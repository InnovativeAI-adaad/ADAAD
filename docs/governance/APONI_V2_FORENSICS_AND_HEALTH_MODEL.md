# Aponi V2 Replay Forensics and Governance Health Model

## Scope

This document defines deterministic, read-only Aponi V2 intelligence behavior.

- No mutation surfaces are introduced.
- All new surfaces are `GET` only.
- Data is computed from existing append-only metrics/lineage artifacts.

## Replay Forensics Endpoints

### `GET /replay/divergence`

Returns replay divergence/failure event counts over a fixed 200-event window and the most recent divergence-relevant events.

### `GET /replay/diff?epoch_id=...`

Returns deterministic replay-state comparison metadata for a specific epoch:

- initial/final state fingerprints (`sha256` over canonical JSON)
- changed/add/removed keys
- semantic drift summary (`semantic_drift`) with deterministic class counts and per-key assignments
- epoch hash-chain anchor (`epoch_chain_anchor`) for tamper-evident replay lineage projection
- bundle count

`semantic_drift.class_counts` is emitted in a stable order and includes:

- `config_drift`
- `governance_drift`
- `trait_drift`
- `runtime_artifact_drift`
- `uncategorized_drift`

The endpoint performs read-only epoch reconstruction and does not trigger mutation execution.

### `GET /risk/instability`

Returns a deterministic weighted instability projection with:

- `instability_index` in `[0,1]`
- `instability_velocity` (difference between latest two fixed momentum windows)
- `instability_acceleration` (second difference across the latest three fixed momentum windows)
- explicit `weights`
- explicit `inputs` (`semantic_drift_density`, `replay_failure_rate`, `escalation_frequency`, `determinism_drift_index`, `timeline_window`, `momentum_window`)

`semantic_drift_density` is computed as a drift-class-weighted projection (with higher `governance_drift` weight than `config_drift`) over recent replay-reconstructable epochs. Momentum metrics use fixed 20-entry windows over the latest 60 timeline entries.

The endpoint also exposes a deterministic Wilson-style confidence interval and `velocity_spike_anomaly` when velocity exceeds a fixed threshold.
Anomaly mode is `absolute_delta`: both sharp destabilization and sharp stabilization deltas are flagged for operator review.

### `GET /policy/simulate`

Read-only policy simulation endpoint that compares health outcomes under current policy vs a candidate governance policy artifact.

- No mutation or policy state is changed
- Candidate policy is loaded and validated with the same deterministic policy loader
- Output includes input telemetry, current policy health, and simulated policy health

### `GET /alerts/evaluate`

Deterministic alert projection endpoint for operator routing.

- Returns `critical`, `warning`, and `info` buckets
- Uses fixed thresholds over `/risk/instability` and `/risk/summary` outputs
- Exposes the active thresholds and derived inputs in payload for auditability

## Governance Health Model (`v1.0.0`)

The model metadata and thresholds are loaded from the versioned policy artifact at `governance/governance_policy_v1.json`.

Inputs:

- rolling determinism score (`window=200`)
- mutation rate limiter state (`ok`)
- mutation aggression index (`rate_per_hour / max_mutations_per_hour`)
- entropy trend slope (linear slope over observed entropy in last 100 events)
- constitution escalations in last 100 events

Thresholds (from policy artifact):

- `PASS`: `determinism_score >= determinism_pass` and `rate_limiter_ok`
- `WARN`: `determinism_score >= determinism_warn`
- `BLOCK`: otherwise

Auditability: `/system/intelligence` returns a `policy_fingerprint` (`sha256`) of the loaded policy payload.

Constitution escalation count uses canonical event normalization from `runtime/governance/event_taxonomy.py`, with deterministic fallback heuristic matching for backward compatibility.

## Security Headers

Aponi HTML responses enforce:

- `Cache-Control: no-store`
- `Content-Security-Policy: default-src 'self'; script-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'`

The UI JavaScript is served as `/ui/aponi.js` to remain CSP-compatible without inline script execution.

## Determinism Invariants

1. UI endpoints never mutate lineage, ledger, or replay state.
2. Risk/intelligence outputs are pure functions of persisted telemetry windows.
3. Replay diff output is canonical-hash based and reproducible for identical epoch inputs.
