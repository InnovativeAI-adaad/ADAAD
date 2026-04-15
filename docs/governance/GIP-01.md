# SPDX-License-Identifier: Apache-2.0
# GIP-01 — Grok Integrator Governed Mediation (Accepted Spec)

## Summary

GIP-01 defines a governed runtime adapter for Grok proposal mediation using existing constitutional controls and append-only evidence flow.

## Implemented components

- `runtime/governance/grok_proposal_mediator.py`
  - `GrokProposalMediationResult`
  - `mediate_grok_proposal(...)`
- `runtime/api/app_layer.py`
  - `mediate_grok_proposal(...)` facade for app-layer consumers

## Live entrypoints

- Runtime entrypoint: `runtime.governance.grok_proposal_mediator.mediate_grok_proposal`
- App-layer entrypoint: `runtime.api.app_layer.mediate_grok_proposal`

## Governance lifecycle enforced by the entrypoint

1. Generate deterministic proposal id (`runtime/governance/foundation/determinism.py`)
2. Run governance gate approval (`runtime/governance/gate.py`)
3. Run schema + constitutional proposal validation (`runtime/mcp/proposal_validator.py`)
4. Append proposal to hash-linked queue (`runtime/mcp/proposal_queue.py`)

## Error behavior

- Governance rejection => raises `PermissionError` with structured reason code list.
- Proposal contract violation => raises `ProposalValidationError`.
- Queue append failures propagate (fail-closed behavior).

## Evidence links

- Proposal record: `governance/gip-01-grok-integrator.md`
- Release note: `docs/releases/9.77.2.md`
- Claims evidence row: `docs/comms/claims_evidence_matrix.md` (`gip-01-grok-proposal-mediation-2026-04-15`)
