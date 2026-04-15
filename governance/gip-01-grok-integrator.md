# SPDX-License-Identifier: Apache-2.0
# GIP-01 — Grok Integrator Proposal Mediation

## Status

- **ID:** GIP-01
- **State:** Draft
- **Lane:** governance-runtime
- **Scope:** Governed mediation for Grok-originated proposal payloads

## Motivation

The repository already supports governed proposal execution for DORK via:

- `runtime.governance.dork_proposal_adapter.execute_dork_proposal`
- API entrypoint `app/api/ui.py` route `POST /api/dork/proposals/execute`

This GIP introduces the equivalent governed mediation surface for Grok proposals while preserving the same fail-closed lifecycle:

1. governance approval (`GovernanceGate.approve_mutation`)
2. schema + constitutional pre-check (`runtime.mcp.proposal_validator.validate_proposal`)
3. append-only queue write (`runtime.mcp.proposal_queue.append_proposal`)

## Canonical implementation paths

- Runtime mediator module: `runtime/governance/grok_proposal_mediator.py`
- App-layer runtime facade entrypoint: `runtime/api/app_layer.py::mediate_grok_proposal`
- Validation contract: `runtime/mcp/proposal_validator.py`
- Queue contract: `runtime/mcp/proposal_queue.py`

## Public entrypoint contract

Primary entrypoint:

- `runtime.governance.grok_proposal_mediator.mediate_grok_proposal(...)`

App-layer facade entrypoint:

- `runtime.api.app_layer.mediate_grok_proposal(...)`

Both entrypoints are deterministic in identity generation and fail closed on governance block or validation errors.

## Result contract

`GrokProposalMediationResult` returns:

- `proposal_id`
- `gate_decision_id`
- `governance_decision`
- `queued_event_type`
- `queue_hash`

## Non-goals

- No bypass path around `GovernanceGate`
- No direct queue writes without `validate_proposal`
- No ad-hoc integration under deprecated `app/agents/*` or side-effect import surfaces
