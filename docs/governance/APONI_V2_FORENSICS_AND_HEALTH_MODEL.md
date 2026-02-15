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
- bundle count

The endpoint performs read-only epoch reconstruction and does not trigger mutation execution.

## Governance Health Model (`v1.0.0`)

Inputs:

- rolling determinism score (`window=200`)
- mutation rate limiter state (`ok`)
- mutation aggression index (`rate_per_hour / max_mutations_per_hour`)
- entropy trend slope (linear slope over observed entropy in last 100 events)
- constitution escalations in last 100 events

Thresholds:

- `PASS`: `determinism_score >= 0.98` and `rate_limiter_ok`
- `WARN`: `determinism_score >= 0.90`
- `BLOCK`: otherwise

Constitution escalation count uses exact structured event matching first (`constitution_escalation`, `constitution_escalated`), then deterministic fallback heuristic matching for backward compatibility.

## Security Headers

Aponi HTML responses enforce:

- `Cache-Control: no-store`
- `Content-Security-Policy: default-src 'self'; script-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'`

The UI JavaScript is served as `/ui/aponi.js` to remain CSP-compatible without inline script execution.

## Determinism Invariants

1. UI endpoints never mutate lineage, ledger, or replay state.
2. Risk/intelligence outputs are pure functions of persisted telemetry windows.
3. Replay diff output is canonical-hash based and reproducible for identical epoch inputs.
