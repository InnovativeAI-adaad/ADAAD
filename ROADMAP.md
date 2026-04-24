# ADAAD Roadmap

> **Constitutional principle:** Every item on this roadmap must be approved by ArchitectAgent before implementation, governed by the mutation pipeline before merge, and evidenced in the release notes before promotion.

---

## Current State — v9.84.0 · Phase 151 · INNOV-57 Governed Rollback (GRB)

**Status:** 53 innovations shipped (INNOV-01 through INNOV-53). Phase 147 complete. v9.80.0 released. 53/53 Grade-A modules hardened.
**Automation pointer:** Machine phase progression consumes `docs/governance/ADAAD_PR_PROCESSION_2026-03-v2.md` §3.0 “Active Era Contract (Phases 131–136+)”, which governs the current stream through Phase 147.
**Hard-class invariants:** 251 (cumulative, enforced)
**Constitutional Evolution Loop:** 16-step CEL, deterministic replay, wired
**Self-Proposing Innovation Engine (SPIE):** active — system proposes its own next innovations; HUMAN-0 ratifies
**Deterministic Audit Sandbox (DAS):** active — one-command external verification; `docker compose up das-demo`

| Innovation | Module | Phase | Version | Invariants |
|-----------|--------|-------|---------|------------|
| INNOV-01 · CSAP | constitutional_stress_test.py | 87 | v9.18.0 | CSAP-0, CSAP-1 |
| INNOV-02 · ACSE | self_awareness_invariant.py | 87 | v9.18.0 | ACSE-0, ACSE-1 |
| INNOV-03 · TIFE | temporal_governance.py | 87 | v9.18.0 | TIFE-0 |
| INNOV-04 · SCDD | constitutional_entropy_budget.py | 88 | v9.21.0 | SCDD-0 |
| INNOV-05 · AOEP | governance_archaeology.py | 89 | v9.22.0 | AOEP-0 |
| INNOV-06 · CEPD | counterfactual_fitness.py | 90 | v9.23.0 | CEPD-0, CEPD-1 |
| INNOV-07 · LSME | temporal_regret.py | 91 | v9.24.0 | LSME-0, LSME-1 |
| INNOV-08 · AFRT | red_team_agent.py | 92 | v9.25.0 | AFRT-0, AFRT-GATE-0, AFRT-INTEL-0, AFRT-LEDGER-0, AFRT-CASES-0, AFRT-DETERM-0 |
| INNOV-09 · AFIT | aesthetic_fitness.py | 93 | v9.26.0 | AFIT-0, AFIT-DETERM-0, AFIT-BOUND-0, AFIT-WEIGHT-0 |
| INNOV-10 · MMEM | morphogenetic_memory.py | 94 | v9.27.0 | MMEM-0..3 |
| INNOV-11 · DSTE | dream_state.py | 96 | v9.29.0 | DSTE-0..6 |
| INNOV-12 · MGV | mutation_genealogy.py | 97 | v9.30.0 | MGV-0, MGV-DETERM-0, MGV-PERSIST-0 |
| INNOV-13 · IMT | knowledge_transfer.py | 98 | v9.31.0 | IMT-0..4 |
| INNOV-14 · CEB | constitutional_entropy_budget.py | 99 | v9.32.0 | CEB-0..4 |
| INNOV-15 · CTD | constitutional_tension.py | 100 | v9.33.0 | CTD-0..4 |
| INNOV-16 · ERS | emergent_roles.py | 101 | v9.34.0 | ERS-0..ERS-PERSIST-0 |
| INNOV-17 · APM | agent_postmortem.py | 102 | v9.35.0 | APM-0..4 |
| INNOV-18 · GJR | constitutional_jury.py | 103 | v9.36.0 | GJR-0..4 |
| INNOV-19 · RST | reputation_staking.py | 104 | v9.37.0 | RST-0..4 |
| INNOV-20 · BRM | blast_radius_model.py | 105 | v9.38.0 | BRM-0..4 |
| INNOV-21 · GBP | governance_bankruptcy.py | 106 | v9.39.0 | GBP-0..7 |
| INNOV-22 · MCF | mutation_conflict_framework.py | 107 | v9.40.0 | MCF-0..DETERM-0 |
| INNOV-23 · CES | constitutional_epoch_sentinel.py | 108 | v9.41.0 | CES-0..DETERM-0 |
| INNOV-24 · SVP | semantic_version_enforcer.py | 109 | v9.42.0 | SVP-0..4 |
| INNOV-25 · HAF | hardware_adaptive_fitness.py | 110 | v9.43.0 | HAF-0..4 |
| INNOV-26 · GDA | graduated_invariants.py | 111 | v9.44.0 | GDA-0..4 |
| INNOV-27 · RCI | regulatory_compliance.py | 112 | v9.45.0 | RCI-0..4 |
| INNOV-28 · IPV | intent_preservation.py | 113 | v9.46.0 | IPV-0..4 |
| INNOV-29 · CED | curiosity_engine.py | 114 | v9.47.0 | CED-0..4 |
| INNOV-30 · MIRROR | mirror_test.py | 115 | v9.48.0 | MIRROR-0, MIRROR-DETERM-0, MIRROR-AUDIT-0 |
| INNOV-31 · IDE | invariant_discovery.py | 116 | v9.49.0 | IDE-0, IDE-DETERM-0, IDE-PERSIST-0, IDE-AUDIT-0, IDE-GATE-0 |
| INNOV-32 · CRTV | constitutional_rollback.py | 117 | v9.50.0 | CRTV-0, CRTV-CHAIN-0, CRTV-DETERM-0, CRTV-GATE-0, CRTV-AUDIT-0 |
| INNOV-33 · KBEP | knowledge_bundle_exchange.py | 118 | v9.51.0 | KBEP-0..VERIFY-0 |
| INNOV-34 · FGCON | federation_governance_consensus.py | 119 | v9.52.0 | FGCON-0..QUORUM-0 |
| INNOV-35 · SPIE | self_proposing_innovation_engine.py | 120 | v9.53.0 | SPIE-0..HUMAN0-0 |
| INNOV-36 · BIRC | break_it_challenge.py | 126 | v9.59.0 | BIRC-0..RED-0 |
| INNOV-37 · GRRP | red_team_response.py | 127 | v9.60.0 | GRRP-0..4 |
| INNOV-38 · ACSA | self_amendment_engine.py | 128 | v9.61.0 | ACSA-0..4 |
| INNOV-39 · ACF | coalition_formation.py | 129 | v9.62.0 | ACF-0..4 |
| INNOV-40 · CELT | agent_learning_transfer.py | 130 | v9.63.0 | CELT-0..4 |
| INNOV-41 · DORK-FLEET | dork_living_fleet.py | 132 | v9.64.0 | DFLEET-0..4 |
| INNOV-42 · DFSB | dork_fleet_server_bridge.py | 133 | v9.65.0 | DFSB-0..4 |
| INNOV-43 · CVR | constitution_version_ledger.py | 135 | v9.67.0 | CVR-IMMUT-0, CVR-DIGEST-0, CVR-ROLLBACK-0, CVR-HUMAN0-0, CVR-CHAIN-0 |
| INNOV-47 · LKSE | sync_dork_corpus.py | 141 | v9.74.0 | LKSE-SYNC-0, LKSE-DETERM-0, LKSE-CHAIN-0, LKSE-GATE-0, LKSE-HUMAN0-0 |
| INNOV-48 · CSS | embedder.py | 142 | v9.75.0 | CSS-DETERM-0, CSS-FALLBACK-0, CSS-DIM-0, CSS-COSINE-0, CSS-PYDROID-0 |
| INNOV-49 · CMU | model_validator.py | 143 | v9.76.0 | CMU-CTX-0, CMU-TEMP-0, CMU-BENCH-0, CMU-DETERM-0, CMU-HUMAN0-0 |
| INNOV-50 · RAGS | grounded_responder.py | 144 | v9.77.0 | RAGS-GROUND-0, RAGS-CTX-0, RAGS-DETERM-0, RAGS-CHAIN-0, RAGS-GATE-0 |

**Open GA blocker (canonical):** None — FINDING-66-004 resolved (2026-04-12). All ceremonies complete. GA track unblocked.  
**Strategic plan:** `docs/governance/POST_PIPELINE_STRATEGIC_PLAN.md`

---

## DORK Evolution Arc — Phases 131–136

**Governing strategic document:** `docs/governance/DORK_EVOLUTIONARY_ROADMAP.md`  
**Strategic Plan:** `docs/governance/DORK_STRATEGIC_PLAN.md`

The system now implements the **DORK Governance Intelligence Layer**. This arc establishes a self-deepening, permanent operator intelligence layer that ensures long-range constitutional stability and architectural foresight.

| Phase | Title | Version | Status |
|-------|-------|---------|--------|
| 131 | DORK Genesis & Data Integrity | v9.64.0 | ✅ shipped |
| 132 | INNOV-41 DORK Living Fleet | v9.64.0 | ✅ shipped |
| 133 | INNOV-42 DORK Fleet Server Bridge (DFSB) | v9.65.0 | ✅ shipped |
| 134 | REF-001–004 DFSB Post-Ship Remediation | v9.66.0 | ✅ shipped |
| 135 | INNOV-43 CVR — Constitution Versioning and Rollback | v9.67.0 | ✅ shipped |
| 136 | Phase 136 DORK Ledger + Enrichment Bridge Hardening | v9.69.0 | ✅ shipped |
| 137 | INNOV-44 DORK Intelligence Hardening & Capability Expansion | v9.70.0 | ✅ shipped |

---

## Post-Pipeline Summary Table

| Phase | Title | Version | Priority | Status |
|-------|-------|---------|----------|--------|
| 120 | INNOV-35 SPIE — Self-Proposing Innovation Engine | v9.53.0 | — | ✅ shipped |
| 121 | Demo Sandbox + Ledger Verifier | v9.54.0 | P0 | ✅ shipped |
| 122 | README Credibility + ROADMAP Sync | v9.55.0 | P0 | ✅ shipped |
| 123 | CLI Entry Point | v9.56.0 | P1 | ✅ shipped |
| 124 | adaad-core Extraction | v9.57.0 | P1 | ✅ shipped |
| 125 | Community Governance Infrastructure | v9.58.0 | P2 | ✅ shipped |
| 126 | Break It Challenge — INNOV-36 Red-Team | v9.59.0 | P2 | ✅ shipped |
| 127 | INNOV-37 GRRP — Governed Red-Team Response Protocol | v9.60.0 | P1 | ✅ shipped |
| 128 | INNOV-38 ACSA — Autonomous Constitutional Self-Amendment Engine | v9.61.0 | P1 | ✅ shipped |
| 129 | INNOV-39 ACF — Agent Coalition Formation | v9.62.0 | P1 | ✅ shipped |
| 130 | INNOV-40 CELT — Cross-Epoch Agent Learning Transfer | v9.63.0 | P1 | ✅ shipped |
| 131 | DORK Genesis & Data Integrity | v9.64.0 | P0 | ✅ shipped |
| 132 | INNOV-41 DORK Living Fleet | v9.64.0 | P1 | ✅ shipped |
| 133 | INNOV-42 DORK Fleet Server Bridge (DFSB) | v9.65.0 | P1 | ✅ shipped |
| 134 | REF-001–004 DFSB Post-Ship Remediation | v9.66.0 | P1 | ✅ shipped |
| 135 | INNOV-43 Constitution Versioning and Rollback (CVR) | v9.67.0 | P1 | ✅ shipped |
| 136 | Phase 136 DORK ConversationLedger + Enrichment Bridge Hardening | v9.69.0 | P1 | ✅ shipped |
| 137 | INNOV-44 DORK Intelligence Hardening & Capability Expansion | v9.70.0 | P0 | ✅ shipped |
| 138 | INNOV-45 IIG — Invariant Interaction Graph | v9.71.0 | P0 | ✅ shipped |
| 139 | INNOV-46 CMD — Canary Mutation Deployment | v9.72.0 | P0 | ✅ shipped |
| 140 | Constitutional P0 Sweep + P1 Hardening | v9.73.0 | P0 | ✅ shipped |
| 141 | INNOV-47 LKSE — Live Knowledge Sync Engine | v9.74.0 | P0 | ✅ shipped |
| 142 | INNOV-48 CSS — Contextual Semantic Search | v9.75.0 | P0 | ✅ shipped |
| 143 | INNOV-49 CMU — Constitutional Model Upgrade | v9.76.0 | P0 | ✅ shipped |
| GA | v1.1-GA Release | v1.1.0-GA | P0 | ✅ Published · pypi.org/project/adaad/9.78.0 · 2026-04-21 |
| 144 | INNOV-50 RAGS — Retrieval-Augmented Governance Synthesis | v9.77.0 | P0 | ✅ shipped |
| 145 | INNOV-51 DPM — DORK Persistent Memory | v9.78.0 | P0 | ✅ shipped |
| 146 | INNOV-52 DQR — Dork Query Router | v9.79.0 | P0 | ✅ shipped |
| 147 | INNOV-53 Intent Expression Schema | v9.80.0 | P0 | ✅ shipped |
| 148 | INNOV-54 LEF — Live Execution Feed | v9.81.0 | P0 | ✅ shipped |
| 149 | INNOV-55 MXE — Mutation Explainability Engine | v9.82.0 | P0 | ✅ shipped |
| 150 | INNOV-56 GCB — Governance Circuit Breaker | v9.83.0 | P0 | ✅ shipped |
| 151 | INNOV-57 GRB — Governed Rollback | v9.84.0 | P0 | ✅ shipped |
| 152 | INNOV-58 CPI — Constitutional Pressure Index | v9.85.0 | P0 | ✅ shipped |
| 153 | INNOV-59 AMT — Adaptive Mutation Throttle | v9.86.0 | P0 | ✅ shipped |
| 154 | INNOV-60 CPAG — Constitutional Pre-Admission Gate | v9.87.0 | P0 | ✅ shipped |
| 155 | INNOV-61 CGTH — Constitutional Governance Telemetry Hub | v9.88.0 | P0 | ✅ shipped |
| 156 | INNOV-62 CGAI — Constitutional Governance Anomaly Inspector | v9.89.0 | P0 | ✅ shipped |
| 157 | INNOV-63 GHI — Governance Health Index | v9.90.0 | P0 | ✅ shipped |
| 158 | INNOV-64 CSR — Constitutional Self-Repair Engine | v9.91.0 | P0 | ✅ shipped |


## Phase 140 — Constitutional P0 Sweep + P1 Hardening (v9.73.0) ✅
- Resolved 5 P0 audit findings (WL-001..WL-005) from the deepest audit in ADAAD history
- 5 new Hard-class invariants: HAPG-IDENTITY-0, HAPG-EXPIRY-0, REPLAY-ALGO-0, TEST-ATTEST-0, GRRP-KEY-0
- Total invariants: 221 | Total phases: 140 | Tests: 30/30
