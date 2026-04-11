# ADAAD Phase 95 — Oracle × Dork Alignment Specification

**Document class:** ARCHITECT_SPEC  
**Phase target:** 95  
**Subsystems:** Oracle (`ui/aponi/innovations_panel.js`) × Dork (`ui/developer/ADAADdev/whaledic.html`)  
**Author:** ArchitectAgent — Dustin L. Reid · InnovativeAI LLC  
**Repository:** https://github.com/InnovativeAI-adaad/adaad.git  
**Base ref:** v9.27.0 · phase94_complete  
**HUMAN-0 Gate:** Dustin L. Reid — ratified 2026-03-29  
**Status:** APPROVED — implementation complete

---

## 0. Executive Summary

Phase 95 aligns, enhances, and optimizes ADAAD's two AI intelligence surfaces — Oracle (Aponi) and Dork (Whale.Dic). The implementation eliminates paid API dependencies, establishes a shared ADAAD_STATE_BUS, introduces real LLM streaming via Groq's free tier with Ollama fallback, upgrades Oracle to a 12-chip structured answer surface, and creates a bidirectional Oracle↔Dork intelligence bridge.

**HUMAN-0 Statement:** "Approved Phase 95 Oracle×Dork alignment plan. All signed: Dustin L. Reid."

---

## 1. Layers Implemented

| Layer | Description | Status |
|-------|-------------|--------|
| L1 | `window.ADAAD_STATE_BUS` shared state object | ✅ COMPLETE |
| L2 | Constitutional Grounding — CCB injected in all prompts | ✅ COMPLETE |
| L3 | Streaming Pipeline — Groq SSE + Ollama fallback + word-reveal | ✅ COMPLETE |
| L4 | Oracle Intelligence Lift — 12 chips, 5-section renderer | ✅ COMPLETE |
| L5 | Dork Intelligence Lift — free LLM, DorkEngine, enhanced markdown | ✅ COMPLETE |
| L6 | Bidirectional Bridge — Oracle→Dork relay, Dork→Oracle intent | ✅ COMPLETE |

---

## 2. Free LLM Architecture (Phase 95 ADR — supersedes ADR-whaledic-llm-direct.md)

**Decision:** Replace direct Anthropic API calls in Dork with a tiered free provider system.

**Priority chain:**
1. **Groq API** (free tier, `llama-3.3-70b-versatile`, 30 req/min, 14,400 req/day) — primary
2. **Ollama** (local, user-configured model, completely free) — secondary
3. **DorkEngine** (deterministic constitutional intelligence, zero cost) — always-available fallback

### Dispatch/Fallback Semantics (current runtime alignment)

- DORK fleet dispatch is priority-ordered and deterministic per request.
- Provider dispatch failures trigger immediate unhealthy marking and probe recording in `ProviderHealthRegistry`.
- Query-time failover excludes already-attempted providers and retries with a bounded sequence (`max_attempts = min(3, total_providers)`).
- If all attempts fail:
  - fail-closed behavior is preserved by default (error status + structured metadata),
  - deterministic fallback text is used only when `ADAAD_DORK_FLEET_ALLOW_DETERMINISTIC_FALLBACK` is explicitly enabled.
- Error metadata includes attempted provider order and the terminal failure reason for post-incident auditability.

**Rationale:** Groq's free tier provides real LLM power at zero cost. Ollama enables fully local operation. DorkEngine guarantees governance intelligence even without any network connectivity. Oracle calls the Groq/Dork bridge via ADAAD_STATE_BUS — no separate API needed.

---

## 3. Invariants Asserted

| ID | Invariant |
|----|-----------|
| ORACLE-CONTEXT-0 | Every Oracle query carries epoch_id and gate_ok at call time |
| ORACLE-RENDER-0 | Oracle never renders raw JSON as primary output |
| ORACLE-STREAM-0 | Oracle result display begins within 400ms via word-reveal |
| ORACLE-AUDIT-0 | Oracle queries write to ADAAD_STATE_BUS for audit trail |
| DORK-CONST-0 | Every Dork system prompt contains CCB with gate_ok and active_phase |
| DORK-FREE-0 | Dork never requires a paid API key to produce governance intelligence |
| DORK-STREAM-0 | First Dork token visible within 400ms via Groq SSE or word-reveal |
| DORK-AUDIT-0 | Dork turns produce event bus entries |
| BRIDGE-STATE-0 | Oracle answer visible in Dork STATE_BUS context within one query cycle |
| BRIDGE-FREE-0 | Oracle→Dork bridge requires zero additional API cost |

---

## 4. Files Modified

- `ui/developer/ADAADdev/whaledic.html` — Phase 95 Dork lift
- `ui/aponi/innovations_panel.js` — Phase 95 Oracle lift
- `docs/plans/PHASE_95_ORACLE_DORK_ALIGNMENT_SPEC.md` — this document
- `artifacts/governance/phase95/identity_ledger_attestation.json` — governance record
- `CHANGELOG.md` — phase entry
- `VERSION` — 9.28.0

---

## 5. Governance Ledger Entry

```json
{
  "event_type": "HUMAN_0_GATE",
  "gate_id": "PHASE_95_ORACLE_DORK_ALIGNMENT",
  "description": "Phase 95 Oracle×Dork alignment complete. Free LLM tier, state bus, bridge, streaming all implemented.",
  "produced_by": "ArchitectAgent",
  "spec_doc": "docs/plans/PHASE_95_ORACLE_DORK_ALIGNMENT_SPEC.md",
  "layers": 6,
  "invariants_asserted": 10,
  "human_0": "Dustin L. Reid",
  "ts_iso": "2026-03-29T00:00:00Z"
}
```

---

*End of PHASE_95_ORACLE_DORK_ALIGNMENT_SPEC.md*  
*ArchitectAgent · InnovativeAI LLC · Blackwell, Oklahoma*
