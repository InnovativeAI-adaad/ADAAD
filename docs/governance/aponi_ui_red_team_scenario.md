# Aponi UI Red-Team Pressure Scenario (Read-only Governance Surface)

## Scenario

An attacker attempts to use the governance UI as a covert mutation channel by:

1. Injecting script payloads into browser state.
2. Forcing stale cached governance decisions.
3. Amplifying replay workload through uncontrolled epoch query fan-out.
4. Spoofing escalation visibility by crafting ambiguous event names.

## Attack Goals

- Obtain mutation authority from the observer surface.
- Hide replay divergence from operators.
- Trigger non-deterministic UI output.

## Defensive Controls (Current)

- `GET`-only surface in Aponi; no mutation POST routes.
- HTML hardening headers:
  - `Cache-Control: no-store`
  - CSP locked to self-hosted script path (`/ui/aponi.js`), no inline scripts.
- Replay forensics endpoints are read-only projections over existing replay/metrics data.
- Governance health model has deterministic thresholds and explicit model version.
- Structured constitution escalation event matching reduces ambiguity risk.

## Simulated Pressure Steps

1. Attempt inline script injection in URL/query.
   - Expected: browser blocks execution under CSP.
2. Attempt stale-page replay after governance-state changes.
   - Expected: no-store policy prevents cached governance pages.
3. Flood `/replay/diff` with missing `epoch_id`.
   - Expected: deterministic `missing_epoch_id` response, no state mutation.
4. Submit noisy metric events with near-match names.
   - Expected: exact event-type matches prioritized; fallback heuristic only for compatibility.

## Expected Invariants

- No ledger writes originate from UI path.
- No replay mode changes originate from UI path.
- No mutation state transitions originate from UI path.
- Same telemetry window => same governance/risk output.

## Next Hardening Ideas

- Add rate limiting for replay forensics endpoints.
- Add explicit schema-validated governance event taxonomy in metrics writer path.
- Add signed replay-proof bundle viewer once proof export format is finalized.
