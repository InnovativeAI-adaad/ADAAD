# Phase 200 Pre-Work — DORK + CMCE Integration

**Status:** Track A preparatory scaffolding (2026-05-28)

## Objective (from Epoch A Plan)
Make high-impact DORK outputs (proposals, insights, mutations) subject to CMCE consensus before they can influence the system.

## Key Integration Points Identified
- `dorkllm/constitutional_mutation_queue.py` — already references CEL entry.
- `dorkllm/` proposal and intent model paths.
- `app/api/` constitutional mutation intent endpoints.
- DORK proposal adapters that feed into the kernel.

## Planned Deliverables for Phase 200
1. DORK proposal adapter that calls `EvolutionKernel.propose_mutation_with_cmce` (or a dedicated DORK CMCE path).
2. CMCE correlation attached to DORK ledger events (DPM, DQR, etc.).
3. New soft/hard invariants for DORK-CMCE coupling.
4. Test harness for DORK → CMCE → CEL flow.

## Immediate Pre-Work Done (this session)
- Core kernel now surfaces `cmce_decision` on every cycle.
- This gives DORK layers an obvious hook.

## Next Actions (when authorized)
- Audit all DORK proposal emission points.
- Prototype `dork_cmce_adapter.py`.
- Register Phase 200 invariants.

This document will be expanded as Phase 199 stabilizes.