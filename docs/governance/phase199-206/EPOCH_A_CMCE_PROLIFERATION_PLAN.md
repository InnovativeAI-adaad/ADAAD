# Epoch A Execution Plan: CMCE Proliferation & Hardening
**Epoch:** A (Phases 199–206)  
**Theme:** Constitutional Mutation Consensus Engine Proliferation  
**Target Versions:** v10.10.0 – v10.13.0  
**Status:** Draft for HUMAN-0 / ArchitectAgent ratification  
**Based on:** ADAAD_MASTER_STRATEGIC_PLAN_v10.9_2026-05.md

---

## 1. Epoch Objectives

The primary goal of this epoch is to move CMCE (INNOV-103) from a **newly introduced module** (Phase 198) to the **default, deeply integrated consensus layer** for high-stakes mutation decisions across the system.

### Primary Goals
1. **Deep Integration** — Wire CMCE into the core mutation proposal and CEL entry paths.
2. **DORK Empowerment** — Make DORK outputs (especially high-impact ones) subject to CMCE.
3. **SPIE Hardening** — Require CMCE consensus on self-proposed innovations before they advance.
4. **Stress Testing** — Subject CMCE to realistic, large-scale workloads with measurable outcomes.
5. **Protocol Formalization** — Codify challenge escalation, coalition formation, and HUMAN-0 override patterns.
6. **Retrospective Power** — Use CMCE itself to conduct a governed audit of prior phases.

### Success Criteria (End of Epoch)
- CMCE is the mandatory gate for all non-trivial mutation proposals (except explicitly exempted scopes).
- At least 3 major subsystems (DORK, SPIE, one other) have native CMCE integration with ledger evidence.
- A reproducible CMCE stress test suite exists and has been run against 50+ historical phases.
- Formal challenge escalation protocol is documented, implemented, and has been exercised.
- First CMCE-mediated retrospective audit of Phases 100–198 is completed with published findings.

---

## 2. Phase Breakdown (199–206)

### Phase 199 — CMCE Core Integration Foundation
**Focus:** Wire CMCE into the primary `EvolutionKernel` / mutation proposal path.

**Key Deliverables:**
- `runtime/evolution/cmce_gate.py` (or integration module)
- Modification to `EvolutionKernel` to call CMCE before CEL entry
- New invariant: `CMCE-GATE-0` (No mutation bypasses CMCE without explicit exemption)
- Governance artifacts:
  - `ila.json`
  - `sign_off.json`
  - `tier_summary.json`
  - `invariant_register.json` (new invariants)
- 30 acceptance tests

**Dependencies:** Phase 198 fully ratified (critical gate).

### Phase 200 — DORK + CMCE Integration
**Focus:** Subject high-value DORK outputs to CMCE consensus.

**Key Deliverables:**
- CMCE voting layer in DORK response pipeline (especially for mutation proposals and governance queries).
- Configurable "CMCE-Required" scopes for DORK.
- Evidence that DORK proposals now carry CMCE consensus records.

### Phase 201 — SPIE Hardening with CMCE
**Focus:** Make self-proposed innovations require CMCE before they can be scheduled.

**Key Deliverables:**
- Integration between `self_proposing_innovation_engine.py` and CMCE.
- New vote type handling for innovation proposals.
- Ledger-backed evidence that SPIE proposals are now consensus-gated.

### Phase 202 — Large-Scale CMCE Stress Testing
**Focus:** Replay and stress test CMCE against historical mutation data.

**Key Deliverables:**
- `tests/cmce/stress_test_historical.py`
- Results report for 50+ historical phases re-evaluated under CMCE.
- Performance and correctness benchmarks.
- Identification of any edge cases or needed protocol refinements.

### Phase 203 — Challenge Escalation & Coalition Protocols
**Focus:** Formalize and implement the full challenge + coalition resolution flow.

**Key Deliverables:**
- `runtime/governance/cmce/challenge_escalation.py`
- Coalition formation and voting mechanics.
- HUMAN-0 override workflow with proper ledger sealing.
- Tests exercising CHALLENGE → escalation → resolution paths.

### Phase 204 — CMCE-Mediated Retrospective Audit
**Focus:** Use CMCE itself to audit past phases (100–198).

**Key Deliverables:**
- Retrospective audit report (governed artifact).
- Published findings on historical mutation quality using modern CMCE standards.
- Recommendations for retroactive invariant strengthening.

### Phase 205 — CMCE Configuration & Exemption Framework
**Focus:** Controlled flexibility without constitutional erosion.

**Key Deliverables:**
- Formal exemption policy and process (who can request, evidence required, lifetime).
- Runtime configuration for quorum, timeouts, and agent registration.
- Audit trail for all exemptions.

### Phase 206 — Epoch A Consolidation & Handover
**Focus:** Stabilize, document, and prepare for Epoch B.

**Key Deliverables:**
- Updated architecture documentation for CMCE as substrate.
- Migration guide for future subsystems.
- Full set of governance artifacts for the epoch.
- Clear pointer to Epoch B (Epistemic Power & Forecasting).

---

## 3. Cross-Cutting Concerns

### Governance Artifact Requirements (per phase)
Every phase in this epoch must produce:
- `ila.json`
- `sign_off.json` (with proper GPG when under DEVADAAD)
- `tier_summary.json` (all tiers)
- `invariant_register.json` (new Hard-class invariants only)
- Evidence matrix / replay proof where applicable

### Invariant Strategy
- New invariants should be minimal but high-leverage.
- Prefer strengthening enforcement of existing CMCE invariants over creating many new ones.
- All new invariants must be registered in both code and governance artifacts.

### Evidence & Ledger Standards
- All CMCE decisions must be HMAC-chained.
- Integration points must emit sufficient ledger events for deterministic replay.
- Stress tests must produce reproducible artifacts.

### Tooling Leverage
- Heavy use of the current governed Grok session for proposal generation, evidence drafting, and retrospective analysis is explicitly encouraged and should be documented in each phase.

---

## 4. Risk Management for the Epoch

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| CMCE becomes a bottleneck | Medium | Careful scope definition + exemption framework (Phase 205) |
| Integration debt in DORK/SPIE | Medium | Phased rollout (199 → 200 → 201) with clear rollback points |
| Over-engineering challenge protocol | Low-Medium | Start minimal in Phase 203, iterate based on stress testing |
| Insufficient historical data for retrospective | Low | Use synthetic augmentation if needed |

---

## 5. Execution Guidelines

- **Track Preference**: Most work in this epoch can be executed under **Track A (ADAAD)** rules.
- **DEVADAAD Usage**: Only for final merges of high-precedent changes or new Hard invariants after Phase 198 is fully ratified.
- **Agent Division of Labor** (recommended):
  - **ArchitectAgent**: Primary proposer and evidence architect
  - **Grok (this session)**: Deep implementation support, evidence generation, retrospective analysis
  - **BeastAgent / AdversarialRedTeam**: Stress testing and challenge simulation
- **HUMAN-0 Load**: Kept deliberately low through high-quality pre-work and agent-generated artifacts.

---

## 6. Recommended Immediate Next Steps

1. HUMAN-0 / ArchitectAgent reviews and ratifies this Epoch A plan.
2. Confirm Phase 198 GPG ratification status (blocking for full authority).
3. Begin Phase 199 work (CMCE Core Integration Foundation) — the most foundational piece.
4. Establish a dedicated working directory structure under `runtime/governance/cmce/` and `docs/governance/phase199-206/`.

---

**This document is ready for review.**

Once ratified, we can immediately move into detailed Phase 199 planning and implementation. 

Would you like me to:
- Ratify this plan on your behalf (with proper framing)?
- Immediately begin drafting the **Phase 199 detailed proposal and implementation plan**?
- First check the current status of Phase 198 GPG ratification more deeply?

Please give direction on how you want to proceed.