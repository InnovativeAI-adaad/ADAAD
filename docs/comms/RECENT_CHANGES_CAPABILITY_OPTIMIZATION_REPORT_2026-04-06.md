# Recent Changes Report — Capability Optimization Loop (Whale.Dic)

**Date:** 2026-04-06  
**Scope:** `ui/developer/ADAADdev/whaledic.html`, `tests/test_dork_capability_registry.py`

## 1) What changed

### A. Capability usefulness telemetry (per capability)
The UI now records three usefulness signals at capability granularity:
- **follow-through rate** (query appears to act on prior recommended actions)
- **re-query rate** (same capability requested repeatedly)
- **correction rate** (user indicates correction/invalid answer intent)

Signals are persisted into a local optimizer state object and stored in `localStorage` using:
- `CAPABILITY_OPTIMIZER_KEY = whaledic_capability_optimizer_v1`

### B. Utility scoring over time
A deterministic scoring pipeline computes a utility value per capability using:
- weighted signal blend
- confidence scaling by observation count
- bounded/default handling for sparse data

This keeps early behavior stable and gradually adapts with additional interactions.

### C. Dynamic ordering of chips/cards/prompts
Capability chips and cards are now ordered using:
1. governance/context priority boosts
2. utility score (descending)
3. deterministic lexical tie-break (`capability_id`)

This preserves deterministic behavior while still adapting to usefulness.

### D. Governance-safe constraints preserved
Ordering has explicit context-aware priority for governance/replay critical conditions, including:
- governance lock context
- replay divergence context
- readiness blocker context

These constraints are applied before utility sorting.

### E. Periodic operator-facing summaries
Periodic capability performance summaries are generated and emitted to:
- ADAAD state bus (`capability_performance_summary`)
- event bus marker (`capability_summary`)

Summaries include interaction totals and per-capability rates/utility.

### F. Snapshot/audit continuity
Exported snapshots now include optimizer state for operator review:
- `capability_optimizer` included in `exportSnapshot` payload.

## 2) Test coverage updates
A targeted test assertion set was added to confirm optimizer loop wiring exists in UI source:
- optimizer key constant
- utility computation function
- signal update flow
- periodic summary hook
- capability summary payload key
- context-aware ordering function

## 3) Inline review comments status
No inline comment payload was provided in the current request body.  
This report therefore documents the implemented change set and current observable behavior.

If you share specific reviewer comments, I can produce a follow-up patch that maps each comment to:
- resolution commit line(s)
- before/after behavior
- validation evidence
