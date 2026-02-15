# Metal (ui)

The Aponi dashboard provides HTTP endpoints for orchestrator state, metrics tailing, lineage entries, and mutation history. It should be started after core checks succeed and must surface health signals without external dependencies.

## User interface standard

The dashboard serves a human-readable default interface at `/` (also `/index.html`).
This page is the standard entry point for users and renders live data from read-only governance APIs:

- `/state`
- `/system/intelligence`
- `/risk/summary`
- `/risk/instability`
- `/policy/simulate`
- `/alerts/evaluate`
- `/evolution/timeline`
- `/replay/divergence`
- `/replay/diff?epoch_id=...`

## Incremental Aponi V2 path

Aponi now follows an incremental control-plane-first path inside the current server boundary:

1. Observability intelligence (`/system/intelligence`)
2. Evolution timeline (`/evolution/timeline`)
3. Replay forensics (planned)
4. Risk intelligence (`/risk/summary`)
5. Governance command surface (planned, strict-gated)

Replay forensics is now available as deterministic read-only projection endpoints.
`/replay/diff` includes a `semantic_drift` section with stable class counts and per-key class assignment across
`config_drift`, `governance_drift`, `trait_drift`, `runtime_artifact_drift`, and `uncategorized_drift`.

Current implementation is intentionally read-only and replay-neutral. Existing JSON endpoints remain unchanged for automation clients.

Dashboard risk and replay classifiers now use canonical governance event types resolved via `runtime/governance/event_taxonomy.py`. Legacy metric event strings remain supported through a strict fallback map for backward compatibility.

`/risk/instability` provides a deterministic weighted instability index for early-warning governance posture analysis, with explicit input and weight disclosure for auditability, plus additive momentum fields (`instability_velocity`, `instability_acceleration`), confidence interval bounds, and velocity-spike anomaly flags (absolute velocity deltas).
`/policy/simulate` offers read-only policy comparison using candidate governance policy artifacts and current telemetry inputs.
`/alerts/evaluate` returns deterministic severity-bucketed governance alerts for operator routing and escalation.

Policy thresholds and model metadata are sourced from `governance/governance_policy_v1.json` via deterministic runtime validation at startup. The `/system/intelligence` payload includes a `policy_fingerprint` field for audit trails.


## Browser hardening

Aponi HTML responses are sent with `Cache-Control: no-store` and a restrictive CSP.
The UI script is served from `/ui/aponi.js` to keep the page compatible with non-inline script policy.


## Enhanced static dashboard

An optional enhanced dashboard is available at `ui/enhanced/enhanced_dashboard.html` for read-only live visibility over existing Aponi APIs.
