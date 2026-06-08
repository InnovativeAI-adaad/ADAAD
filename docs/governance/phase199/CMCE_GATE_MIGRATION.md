# Phase 199 — CMCE Gate Migration & Deprecation Path

**Status:** Track A implementation draft (as of 2026-05-28)

## Background
Prior to Phase 199, mutation proposals primarily used `EvolutionKernel.propose_mutation(...)`.

Phase 199 introduces `propose_mutation_with_cmce(...)` as the new primary path that enforces the constitutional CMCE gate (INNOV-103 / CMCE-GATE-0) before any mutation can reach the CEL.

## Recommended Migration

### For New High-Stakes Mutations (Post-Phase 199)
```python
kernel = EvolutionKernel(...)
result = kernel.propose_mutation_with_cmce(
    agent=agent,
    mutation=mutation_payload,
    requesting_agent_id="my-agent",
    # allow_exemption=True, exemption_scope=..., exemption_rationale=...  # only when strictly needed
)
if result["approved_for_cel"]:
    # proceed to CEL
```

### For Existing Call Sites (Grace Period)
Existing calls to `propose_mutation` continue to work for backward compatibility during the Phase 199–200 transition window.

**Planned deprecation:**
- Phase 200: Add deprecation warning on `propose_mutation` when used for non-exempt scopes.
- Phase 202 (or earlier if gates close): `propose_mutation` will require an explicit `bypass_cmce=True` flag for non-exempt cases (and will log a CMCE-BYPASS-0 violation event).

## Exemption Usage (Strict)
Exemptions are only for:
- `emergency_rollback`
- `phase199_bootstrap`
- `governance_drift_closure`

All other cases must go through full CMCE consensus.

## Callers Needing Update
Search for calls to `propose_mutation` in:
- `app/`
- `dorkllm/`
- `runtime/`
- tests/

Update high-impact paths first (DORK proposals, SPIE self-proposals, etc.) in later phases.

## Rollback / Compatibility
The old path remains available until explicit deprecation is merged under full Track B authority after Phase 198 gate closure.

---
**Track A Note:** This document was prepared under Track A execution of Phase 199. Final migration timeline and enforcement will be ratified after Phase 198 GPG closure on ADAADell.