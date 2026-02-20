# Aponi V2 Replay Forensics and Governance Health Model

## Scope

This document defines deterministic Aponi V2 intelligence behavior.

- No direct mutation execution surfaces are introduced.
- Intelligence surfaces remain `GET` only.
- Command surfaces, when enabled, queue validated intents only.
- Data is computed from existing append-only metrics/lineage artifacts plus append-only command queue records.

## Strict-gated command queue endpoints

### `GET /control/free-sources`

Returns approved free capability sources from `data/free_capability_sources.json`.

### `GET /control/queue`

Returns latest queued command intents and queue status.

### `GET /control/skill-profiles`

Returns governed skill profiles from `data/governed_skill_profiles.json` including deterministic knowledge-domain and ability constraints.

### `GET /control/capability-matrix`

Returns a normalized deterministic compatibility matrix used by the UI to bind `skill_profile` -> `knowledge_domains` / `abilities` / allowed capabilities.

### `GET /control/policy-summary`

Returns deterministic command-surface policy envelope metadata (text/capability bounds, governance profiles, and inventory counts) for operator validation.

### `GET /control/templates`

Returns deterministic starter templates for `create_agent` and `run_task` intents per governed skill profile.

### `GET /control/environment-health`

Returns deterministic control-plane environment diagnostics constrained to governance-safe readiness data: policy load status/error, command-surface gate state, queue path readiness/writability, required governance data file presence, and schema-version compatibility status against the expected control data schema version. It does not expose secrets, tokens, or arbitrary host environment dumps.

### `GET /control/queue/verify`

Verifies append-only queue continuity and deterministic integrity (`queue_index`, `command_id`, `previous_digest` chain), and reports malformed payload records.

### `POST /control/queue`

Queues a governance command intent only when `APONI_COMMAND_SURFACE=1`.

Supported intent types:

- `create_agent`
- `run_task`

Deterministic validations:

- strict governance profile (`strict`/`high-assurance`)
- deterministic `agent_id` format
- skill profile allowlist (`data/governed_skill_profiles.json`)
- capability source allowlist plus skill-profile capability envelope
- knowledge-domain membership in selected skill profile
- type-specific required fields (`purpose` or `task`)
- `run_task` ability membership in selected skill profile
- deterministic capability deduplication with fixed max envelope
- normalized and size-bounded text fields prior to queue append
- deterministic queue continuity via `previous_digest` chain and verifier endpoint

Queueing an intent does not execute mutations and does not bypass constitutional gates.

Governance data artifacts `data/free_capability_sources.json` and `data/governed_skill_profiles.json` are versioned with top-level `_schema_version` for deterministic schema evolution controls.

## Replay Forensics Endpoints

### `GET /replay/divergence`

Returns replay divergence/failure event counts over a fixed 200-event window and the most recent divergence-relevant events.

### `GET /replay/diff?epoch_id=...`

Returns deterministic replay-state comparison metadata for a specific epoch plus forensic export metadata:

- `bundle_id` (immutable evidence export id)
- `export_metadata` (`digest`, canonical ordering mode, immutable export path, `retention_days`, `access_scope`, signer metadata)

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
Policy envelopes remain fail-closed and support deterministic signer verification paths (`cryovant-static-*`, dev-gated signatures, and `hmac-sha256` keyed verification via Cryovant key resolution env settings).

Constitution escalation count uses canonical event normalization from `runtime/governance/event_taxonomy.py`, with deterministic fallback heuristic matching for backward compatibility.

## Security Headers

Aponi HTML responses enforce:

- `Cache-Control: no-store`
- `Content-Security-Policy: default-src 'self'; script-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'`

The UI JavaScript is served as `/ui/aponi.js` to remain CSP-compatible without inline script execution.

## Determinism Invariants

1. Intelligence endpoints never mutate lineage, ledger, or replay state; forensic endpoints may emit immutable export snapshots under `reports/forensics/`. Strict-gated command endpoints append validated intents to the command queue only.
2. Risk/intelligence outputs are pure functions of persisted telemetry windows.
3. Replay diff output is canonical-hash based and reproducible for identical epoch inputs.


## Operational references

- Forensic export retention automation: `docs/governance/FORENSIC_BUNDLE_LIFECYCLE.md` and `scripts/enforce_forensic_retention.py`.
- Policy artifact signing/verification workflow: `docs/governance/POLICY_ARTIFACT_SIGNING_GUIDE.md`.
- Federation divergence incident response: `docs/governance/FEDERATION_CONFLICT_RUNBOOK.md`.

Aponi governance intelligence responses are validated against draft-2020-12 schemas in `schemas/aponi_responses/`; validation failures return structured `governance_error: "response_schema_violation"` fail-closed responses.
