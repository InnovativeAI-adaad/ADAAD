

## [9.59.0] — 2026-04-06 · Phase 126 · Red-Team Challenge

### Added
- `runtime/red_team/constitutional_attacker.py` — adversarial invariant probe engine; probes all Hard-class gates with typed attack scenarios; fail-closed on every gate miss
- `runtime/red_team/attack_manifest.json` — canonical 20-scenario attack registry; append-only; covers REDTEAM-* and all prior Hard-class invariant families
- `tests/test_phase126_red_team.py` — 30/30 acceptance tests T126-RTEAM-01..30 (ATCK, DFNS, AUDIT, REPT categories)
- `artifacts/governance/phase126/` — sign-off JSON, IP patent specification, invariant registry, test manifest (ILA-126-2026-04-06-001)
- `pytest.ini` — registered `phase126` marker

### Constitutional Invariants
- `REDTEAM-IMMUT-0` (Hard-class) — attack ledger is append-only; post-write mutation raises `LedgerMutationError`; tamper detected via `hmac.compare_digest`
- `REDTEAM-AUDIT-0` (Hard-class) — every attack attempt persisted with chain-linked `prev_digest` before next attempt begins; ledger write failure raises `ConstitutionalBreachError`
- `REDTEAM-SCOPE-0` (Hard-class) — attacker may only target invariants in canonical manifest; unlisted targets raise `OutOfScopeAttackError`
- `REDTEAM-HALT-0` (Hard-class) — any gate miss raises `ConstitutionalBreachError` immediately; silent pass-through is categorically prohibited
- `REDTEAM-DETERM-0` (Hard-class) — `run_digest` is a pure function of (campaign_id, attack_ids, outcomes); no clock or random in digest computation
- `REDTEAM-CHAIN-0` (Hard-class) — each `AttackRecord` carries `prev_digest` linking to prior record; first record carries `prev_digest="genesis"`
- **Cumulative Hard-class invariants: 167 → 173**

### Changed
- `VERSION` → `9.59.0`
- `pyproject.toml` → `9.59.0`
- `pytest.ini` — registered `phase126` marker

### Sync Remediation (committed to main at 99defff)
- FINDING-SYNC-126-001 (P1): `pyproject.toml` frozen at 9.57.0 — resolved
- FINDING-SYNC-126-002 (P1): `agent_state.json` phase/version fields stale — resolved
- FINDING-SYNC-126-003 (P1): autosync false attestation of AUTOSYNC-0 — resolved
- FINDING-SYNC-126-004 (P2): dual invariant count fields unified at 167 — resolved

## [9.58.0] — 2026-04-05 · Phase 125 · Community Governance Infrastructure

### Added
- `CONSTITUTION_PROPOSALS.md` — canonical registry and lifecycle documentation for community constitutional amendment proposals
- `.github/ISSUE_TEMPLATE/constitution_amendment.md` — structured GitHub Issue template for amendment proposals; machine-validated by CI
- `.github/workflows/constitution_amendment_validation.yml` — CI gate: validates proposal structure, enforces FGCON quorum, rejects auto-ratification claims
- `docs/GOVERNANCE_PARTICIPATION.md` — contributor guide covering the full amendment lifecycle, governance hierarchy, and constitutional constraints
- `scripts/validate_amendment_proposal.py` — local and CI amendment validator: ID format, rationale word count (≥50), class selection, FGCON checkboxes, conflict analysis
- `artifacts/governance/phase125/` — sign-off JSON, IP patent specification, invariant registry, test manifest (ILA-125-2026-04-05-001)
- `tests/test_phase125_community_governance.py` — 30/30 acceptance tests T125-COMM-01..30 (COMM, TMPL, WFLOW, DOCS, INV categories)

### Constitutional Invariants
- `COMMUNITY-FGCON-0` (Hard-class) — community amendments subject to FGCON-QUORUM-0; single contributor cannot ratify
- `COMMUNITY-HUMAN0-0` (Hard-class) — HUMAN-0 ratification cannot be delegated or automated via any workflow
- **Cumulative Hard-class invariants: 167**

### Changed
- `VERSION` → `9.58.0`
- `pytest.ini` — registered `phase125` marker
- `ROADMAP.md` — Phase 125 marked ✅ shipped
- `README.md` — stat update: 167 invariants, Phase 125, 37 innovations

---

## [9.57.0] — 2026-04-05 · Phase 124 · adaad-core Extraction

### Added
- `adaad_core/` package — constitutional governance kernel as standalone importable surface
- `adaad_core/__init__.py` — six semver-governed exports: `GovernanceGate`, `ConstitutionalRollbackEngine`, `InvariantDiscoveryEngine`, `MirrorTestEngine`, `EpochMemoryStore`, `verify_ledger`
- `adaad_core/pyproject.toml` — independent semver line; `adaad-core` PyPI target
- `docs/ADAAD_CORE_API.md` — stable API reference, semver-governed from v9.57.0
- `.github/workflows/adaad-core-api-stability.yml` — CI enforces CORE-EXPORT-0, CORE-IMPORT-0, CORE-SEMVER-0 on every PR touching `adaad_core/`
- `GET /api/core/info` — REST endpoint returning package metadata and export inventory
- `tests/test_phase124_adaad_core.py` — 30/30 acceptance tests (T124-CORE-01..30)

### Constitutional invariants introduced (Hard-class)
- `CORE-EXPORT-0` — All six public symbols importable from `adaad_core`
- `CORE-IMPORT-0` — Import must not trigger Aponi UI, SPIE, or federation module init
- `CORE-SEMVER-0` — Breaking API changes require major version bump and HUMAN-0 ratification

**Cumulative Hard-class invariants: 165**

### Governance
- Attestation: ILA-124-2026-04-05-001 · Governor: DUSTIN L REID
- World-first: first governed constitutional kernel extraction as independently semver-managed package

## [9.56.0] — 2026-04-05 · Phase 123 · CLI Entry Point

### Added
- **adaad/__main__.py** — formal CLI entry point with `demo`, `inspect-ledger`, and `propose` commands
- **scripts/adaad** — POSIX shim for direct CLI invocation
- **ARCHITECTURE.md** — new file; documents CLI data flow, module map, and Phase 123 governance invariants

### Changed
- **README.md** — added CLI section; renamed innovations to "Shipped capabilities"; aligned invariant count to 162; updated hero to v9.56.0
- **QUICKSTART.md** — updated with 5-minute CLI path and architecture diagram link
- **ROADMAP.md** — marked Phase 122 and 123 as ✅ shipped; updated Current State to v9.56.0/Phase 123
- **VERSION** — `9.55.0` → `9.56.0`
- **pyproject.toml** — version `9.56.0`
- **.adaad_agent_state.json** — version `9.56.0`, current_phase `123`
- **governance/report_version.json** — version `9.56.0`, phase `123`

### Tests
- `tests/test_phase123_cli.py` — T123-CLI-01..30 (30/30 PASS)

### Governance
- **CLI-SANDBOX-0** — CLI initiated mutations default to dry-run mode
- **CLI-GATE-0** — All CLI proposals must traverse the 16-step CEL pipeline
- Cumulative Hard-class invariants: **162**

## [9.55.0] — 2026-04-05 · Phase 122 · README Credibility + ROADMAP Sync

### Changed
- **README.md** — removed all `world-first` claims; replaced "30/35 innovations" internal batch grouping with a clean 36-module capability index; updated invariant count to 162; hero alt text updated to v9.55.0/122 phases; Roadmap section updated with post-pipeline horizon links
- **docs/VERIFIABLE_CLAIMS.md** — new file; maps every shipped capability to module path, test file, governance artifact, and runnable verification command; includes explicit "What is not claimed" section
- **ROADMAP.md** — Current State updated to v9.55.0/Phase 122; Phase 121 marked ✅ shipped; Phase 122 marked 🔄 in-progress; invariant count updated to 162
- **VERSION** — `9.54.0` → `9.55.0`
- **pyproject.toml** — `9.53.0` → `9.55.0`
- **.adaad_agent_state.json** — version `9.55.0`, current_phase `122`
- **governance/report_version.json** — version `9.55.0`, phase `122`

### Tests
- `tests/test_phase122_readme_credibility.py` — T122-CRED-01..30 (30/30 PASS)

### Governance
- `artifacts/governance/phase122/` — phase122_sign_off.json, track_a_sign_off.json, replay_digest.txt, tier_summary.json (ILA-122-2026-04-05-001)
- Cumulative Hard-class invariants: **162** (no new invariants — documentation phase)

## [9.54.0] — 2026-04-04 · Phase 121 · INNOV-36 DAS

### Added
- **INNOV-36 Deterministic Audit Sandbox (DAS)** — hermetic, reproducible CEL epoch sandbox with HMAC-SHA256 JSONL chain-verified audit ledger; any external observer can clone → `docker-compose up das-demo` → verify in <60 seconds; 7 new Hard-class invariants (DAS-0, DAS-DETERM-0, DAS-CHAIN-0, DAS-REPLAY-0, DAS-GATE-0, DAS-VERIFY-0, DAS-DOCKER-0)
- `runtime/innovations30/deterministic_audit_sandbox.py` — DeterministicAuditSandbox, EpochRecord, RuntimeDeterminismProvider, das_guard; DAS-VERIFY-0 fix: dual tamper detection via stored prev_digest field validation and computed[:24] hash comparison
- `tests/test_phase121_das.py` — T121-DAS-01..30 (30/30 passing)
- `scripts/demo_runner.py` — full pipeline orchestrator; 8-record epoch, chain verify, replay; exit 0 on all-clear
- `scripts/verify_ledger.py` — standalone chain verifier with --verbose per-record output; exit 1 on first broken link
- `scripts/replay_epoch.py` — epoch replay tool; re-derives all record_hash values from stored JSONL; exit 0 on digest match
- `Dockerfile.demo` — pinned Python 3.12.3-slim with exact image digest (DAS-DOCKER-0: :latest constitutionally prohibited)
- `docker-compose.yml` — 4 services: das-demo, das-verify, das-replay, das-test; shared das_ledger_data volume
- `DEMO.md` — external-auditor documentation; includes ledger format spec, chain verification algorithm, quick start
- `ui/aponi/das_panel.js` — Aponi dashboard: live epoch runner, chain integrity banner, per-record table, JSONL export
- `artifacts/governance/phase121/` — phase121_sign_off.json, tier_summary.json (ILA-121-2026-04-04-001)
- Cumulative Hard-class invariants: 162

## [9.53.0] — 2026-04-04 · Phase 120 · INNOV-35 SPIE

### Added
- **INNOV-35 Self-Proposing Innovation Engine (SPIE)** — system proposes its own next innovations from FailureSignal, ConstitutionalGapSignal, and MirrorAccuracySignal inputs; HUMAN-0 still ratifies; 7 new Hard-class invariants (SPIE-0, SPIE-DETERM-0, SPIE-PERSIST-0, SPIE-CHAIN-0, SPIE-GATE-0, SPIE-SOURCE-0, SPIE-HUMAN0-0)
- `runtime/innovations30/self_proposing_innovation_engine.py` — SelfProposingInnovationEngine, InnovationProposal, FailureSignal, ConstitutionalGapSignal, MirrorAccuracySignal, spie_guard
- `tests/test_phase120_spie.py` — T120-SPIE-01..30 (30/30 passing)
- `artifacts/governance/phase120/` — phase120_sign_off.json, tier_summary.json
- Cumulative Hard-class invariants: 155

## [9.52.0] — 2026-04-04 · Phase 119 · INNOV-34 FGCON

### Added
- **INNOV-34 Federation Governance Consensus (FGCON)** — formal consensus protocol for federation-wide constitutional amendments; strict majority quorum enforcement (floor(N/2)+1); no single instance can amend federation-level invariants unilaterally; 7 new Hard-class invariants (FGCON-0, FGCON-DETERM-0, FGCON-PERSIST-0, FGCON-CHAIN-0, FGCON-GATE-0, FGCON-UNILATERAL-0, FGCON-QUORUM-0)
- `runtime/innovations30/federation_governance_consensus.py` — FederationGovernanceConsensus, AmendmentProposal, FederationMember, VoteRecord, fgcon_guard
- `tests/test_phase119_fgcon.py` — T119-FGCON-01..30 (30/30 passing)
- `artifacts/governance/phase119/` — phase119_sign_off.json, tier_summary.json
- Cumulative Hard-class invariants: 148

## [9.51.0] — 2026-04-04 · Phase 118 · INNOV-33 KBEP

### Added
- **INNOV-33 Knowledge Bundle Exchange Protocol (KBEP)** — standardized, cryptographically verified knowledge bundle format for sharing institutional memory across federation members; extends INNOV-13 (IMT) to the multi-instance case; 6 new Hard-class invariants (KBEP-0, KBEP-DETERM-0, KBEP-PERSIST-0, KBEP-CHAIN-0, KBEP-GATE-0, KBEP-VERIFY-0)
- `runtime/innovations30/knowledge_bundle_exchange.py` — KnowledgeBundleExchangeProtocol, FederationBundle, KnowledgeBundleItem, ExchangeRecord, kbep_guard
- `tests/test_phase118_kbep.py` — T118-KBEP-01..30 (30/30 PASS)
- `artifacts/governance/phase118/` — phase118_sign_off.json, track_a_sign_off.json, tier_summary.json

### Constitutional Invariants (6 new · cumulative: 141 Hard-class)
`KBEP-0` · `KBEP-DETERM-0` · `KBEP-PERSIST-0` · `KBEP-CHAIN-0` · `KBEP-GATE-0` · `KBEP-VERIFY-0`

### Architecture
- `FederationBundle.create()` — KBEP-DETERM-0: deterministic bundle_id = sha256(epoch_id + instance_id)[:16]; bundle_digest = sha256(canonical-JSON(items))
- `KnowledgeBundleExchangeProtocol.import_bundle()` — KBEP-0/KBEP-VERIFY-0: recompute_digest() must match before any state write; fail-closed KBEPVerificationError
- `KnowledgeBundleExchangeProtocol.create_bundle()` — KBEP-GATE-0: federation_amendment=True requires human0_acknowledged=True
- `ExchangeRecord` — KBEP-CHAIN-0: HMAC-SHA256 chain linked via (record_id + prev_digest + bundle_id)
- `_flush_record()` — KBEP-PERSIST-0: append-only JSONL flush before method return
- `verify_chain()` — HMAC tamper detection across full ledger replay; KBEPChainError on break
- `export_snapshot()` — aggregates all imported peer bundles into single exportable snapshot
- `kbep_guard()` — fail-closed enforcement helper for all 6 Hard-class invariants

### IP Claims
- World-first: multi-instance federated knowledge bundle exchange with HMAC-chain-linked ledger and HUMAN-0 gated federation amendments in a constitutionally governed autonomous system
- Extends IMT (INNOV-13) to the federation domain with cryptographic provenance across instance boundaries
- KBEP-DETERM-0: no datetime/random in any ID derivation — all deterministic from epoch_id + instance_id
- Fail-closed KBEP-VERIFY-0: partial/approximate digest matching explicitly prohibited

### Metrics
- Hard-class invariants: **135 → 141** (+6 KBEP)
- ILA: ILA-118-2026-04-04-001
- Governor: DUSTIN L REID

## [9.50.0] — 2026-04-04 · Phase 117 · INNOV-32 CRTV

### Added
- **INNOV-32 Constitutional Rollback & Temporal Versioning (CRTV)** — append-only, chain-linked snapshot ledger for the constitution itself; governed rollback to any prior state under HUMAN-0 gate; semantic diff between any two constitutional versions; persistence + reload from JSONL ledger; 5 new Hard-class invariants (CRTV-0, CRTV-CHAIN-0, CRTV-DETERM-0, CRTV-GATE-0, CRTV-AUDIT-0)
- `runtime/innovations30/constitutional_rollback.py` — ConstitutionalRollbackEngine, ConstitutionalSnapshot, ConstitutionalDiff, RollbackEvent
- `tests/test_phase117_crtv.py` — T117-CRTV-01..30 (30/30 PASS)
- `artifacts/governance/phase117/` — governance sign-off, track A, tier summary, replay digest
- **PyPI publication**: v9.50.0 published to PyPI — closes critical distribution gap (prior: v9.11.0)

### Metrics
- Hard-class invariants: **130 → 135** (+5 CRTV)
- ILA: ILA-117-2026-04-04-001
- Governor: DUSTIN L REID

## [9.49.0] — 2026-04-04 — Phase 116 · INNOV-31 Invariant Discovery Engine (IDE)

**Branch:** `feature/phase116-ide-impl`
**HUMAN-0 Gate:** Dustin L. Reid — ratified 2026-04-04
**Tests:** T116-IDE-01..30 (30/30 PASS)
**Evidence:** `artifacts/governance/phase116/phase116_sign_off.json` · ILA-116-2026-04-04-001

### Deliverables
- `runtime/innovations30/invariant_discovery.py` — INNOV-31 full constitutional implementation
- `tests/test_phase116_ide.py` — T116-IDE-01..30 (30/30 PASS)
- `artifacts/governance/phase116/` — 4 governance artifacts

### Constitutional Invariants (5 new · cumulative: 130 Hard-class)
`IDE-0` · `IDE-DETERM-0` · `IDE-PERSIST-0` · `IDE-AUDIT-0` · `IDE-GATE-0`

### Findings Resolved
- **FINDING-115-001**: `agent_state` nested fields backfilled to Phase 115 / v9.48.0
- **FINDING-115-002**: CHANGELOG v9.48.0 Phase 115 MIRROR entry prepended
- **FINDING-115-003**: ROADMAP Phase 115 section appended

### IP Claims
- First governed autonomous constitutional self-discovery engine: system mines its own governance failure history to propose new constitutional invariants
- HMAC-chain-linked append-only JSONL ledger with tamper detection via `verify_chain()`
- Deterministic `rule_id` derived solely from `epoch_id` + pattern index — no datetime/random (IDE-DETERM-0)
- Fail-closed `IDE-GATE-0` deduplication preventing re-proposal of already-known patterns
- `ide_guard()` fail-closed enforcement helper for all 5 Hard-class invariants

---

## [9.48.0] — 2026-04-03 — Phase 115 · INNOV-30 The Mirror Test (MIRROR)

**Branch:** `feature/phase115-mirror-test-impl`
**HUMAN-0 Gate:** Dustin L. Reid — ratified 2026-04-03
**Tests:** T115-MIRROR-01..30 (30/30 PASS)
**Evidence:** `artifacts/governance/phase115/phase115_sign_off.json` · ILA-115-2026-04-03-001

### Deliverables
- `runtime/innovations30/mirror_test.py` — INNOV-30 The Mirror Test full constitutional implementation
- `tests/test_phase115_mirror.py` — T115-MIRROR-01..30 (30/30 PASS)
- `artifacts/governance/phase115/` — 4 governance artifacts

### Constitutional Invariants (3 new · cumulative: 125 Hard-class)
`MIRROR-0` · `MIRROR-DETERM-0` · `MIRROR-AUDIT-0`

### IP Claims
- First constitutional self-calibration test measuring governance prediction accuracy
- Deterministic scoring with tamper-evident result_digest on every MirrorTestResult
- CalibrationEpoch enforcement when overall_score below CALIBRATION_THRESHOLD
- Fail-closed mirror_guard() enforcement helper for all three Hard-class invariants

### Pipeline Milestone
**INNOV-01 through INNOV-30 — 30/30 innovations shipped** across Phases 87–115

---

## [9.47.0] — 2026-04-03 — Phase 114 · INNOV-29 Curiosity-Driven Exploration

**Branch:** `feature/phase114-curiosity-impl`
**HUMAN-0 Ratification:** `[slot reserved]`
**Tests:** T114-CURIOSITY-01..30 (30/30 PASS)
**Evidence Artifacts:** `artifacts/governance/phase114/phase114_sign_off.json` · ILA-114-2026-04-03-001

### Constitutional Invariants Introduced
- **CURIOSITY-0** — `invert_fitness()` returns `1.0 - base_fitness` when active; `base_fitness` in [0.0,1.0] enforced
- **CURIOSITY-STOP-0** — `tick()` MUST exit immediately on `health < 0.50` or protected file match
- **CURIOSITY-AUDIT-0** — all transitions append to `discoveries` and persist state

### Deliverables
- `runtime/innovations30/curiosity_engine.py` — INNOV-29 full constitutional implementation
- `tests/test_phase114_curiosity.py` — T114-CURIOSITY-01..30 (30/30 PASS)
- `artifacts/governance/phase114/` — 4-artifact evidence bundle

---

## [9.42.0] — 2026-04-03 — Phase 109 · INNOV-24 SVP

**Branch:** `feature/phase109-svp-impl`
**HUMAN-0 Ratification:** `[slot reserved]`
**Tests:** T109-SVP-01..30 (30/30 PASS)
**Evidence Artifacts:** `artifacts/governance/phase109/phase109_sign_off.json` · `artifacts/governance/phase109/phase109_replay_digest.json` · ILA-109-2026-04-03-001

### Server Endpoint Additions
- `GET /governance/svp/{epoch_id}`
- `POST /governance/svp/ratify`

### Deliverables
- `runtime/innovations30/sovereign_validation_plane.py` — INNOV-24 SVP implementation
- `tests/test_phase109_svp.py` — T109-SVP-01..30 (30/30 PASS)
- `artifacts/governance/phase109/` — release evidence bundle

---

## [9.41.0] — 2026-04-03 — Phase 108 · INNOV-23 Constitutional Epoch Sentinel

**Branch:** `feature/phase108-ces-impl`
**HUMAN-0 Gate:** Dustin L. Reid — ratified 2026-04-03
**Tests:** T108-CES-01..30 (30/30 PASS)
**Evidence:** `artifacts/governance/phase108/phase108_sign_off.json` · ILA-108-2026-04-03-001

### Deliverables
- `runtime/innovations30/constitutional_epoch_sentinel.py` — INNOV-23 Constitutional Epoch Sentinel
- `tests/test_phase108_ces.py` — T108-CES-01..30 (30/30 PASS)
- `server.py` — `GET /governance/sentinel/{epoch_id}`
- `artifacts/governance/phase108/` — 4 governance artifacts

### Constitutional Invariants (8 new · cumulative: 107 Hard-class)
`CES-0` · `CES-WATCH-0` · `CES-THRESH-0` · `CES-EMIT-0` · `CES-PERSIST-0` · `CES-CHAIN-0` · `CES-GATE-0` · `CES-DETERM-0`

### IP Claims
- First anticipatory constitutional primitive: governed early-warning emission before Hard-class invariant breach
- Warning corridor detection with margin_remaining telemetry enabling pre-violation governance intervention
- Multi-channel atomic tick architecture: all SentinelChannels evaluated per tick (CES-WATCH-0)
- Chain-linked advisory ledger with hmac.compare_digest tamper detection

---

## [9.40.0] — 2026-04-03 — Phase 107 · INNOV-22 Mutation Conflict Framework

**Branch:** `feature/phase107-mcf-impl`
**HUMAN-0 Gate:** Dustin L. Reid — ratified 2026-04-03
**Tests:** T107-MCF-01..30 (30/30 PASS)
**Evidence:** `artifacts/governance/phase107/phase107_sign_off.json` · ILA-107-2026-04-03-001

### Deliverables
- `runtime/innovations30/mutation_conflict_framework.py` — INNOV-22 Mutation Conflict Framework
- `tests/test_phase107_mcf.py` — T107-MCF-01..30 (30/30 PASS)
- `server.py` — `GET /governance/conflict/{mutation_id}`
- `artifacts/governance/phase107/` — 4 governance artifacts

### Constitutional Invariants (8 new · cumulative: 99 Hard-class)
`MCF-0` · `MCF-DETECT-0` · `MCF-SEVERITY-0` · `MCF-PERSIST-0` · `MCF-CHAIN-0` · `MCF-RESOLVE-0` · `MCF-GATE-0` · `MCF-DETERM-0`

### IP Claims
- Constitutional mutation conflict detection via deterministic frozenset intersection with HMAC-chain-linked tamper-evident JSONL ledger
- Severity-stratified conflict resolution: auto-resolve for low/medium, mandatory HUMAN-0 escalation advisory for high/critical
- Stable conflict_digest over sorted mutation_id pair and overlap paths enabling deterministic cross-epoch replay verification
- EscalationAdvisory emission and acknowledgement lifecycle enforcing HUMAN-0 gate before high/critical conflict resolution

---

## [9.39.0] — 2026-04-03 — Phase 106 · INNOV-21 Governance Bankruptcy Protocol

**Branch:** `feature/phase106-gbp-impl`
**HUMAN-0 Gate:** Dustin L. Reid — ratified 2026-04-03
**Tests:** T106-GBP-01..30 (30/30 PASS)
**Evidence:** `artifacts/governance/phase106/phase106_sign_off.json` · ILA-106-2026-04-03-001

### Deliverables
- `runtime/innovations30/governance_bankruptcy.py` — promoted from scaffold to full constitutional implementation
- `tests/test_phase106_gbp.py` — T106-GBP-01..30 (30/30 PASS)
- `server.py` — `GET /governance/bankruptcy/{epoch_id}`
- `artifacts/governance/phase106/` — 4 governance artifacts

### Findings Resolved
- `FINDING-GBP-SCAFFOLD-01` (P1): governance_bankruptcy.py scaffold missing typed exception, chain-link, and discharge supersession — all closed

### Constitutional Invariants (8 new · cumulative: 91 Hard-class)
`GBP-0` · `GBP-THRESH-0` · `GBP-HEALTH-0` · `GBP-PERSIST-0` · `GBP-CHAIN-0` · `GBP-DISCHARGE-0` · `GBP-GATE-0` · `GBP-IMMUT-0`

### IP Claims
- Governance debt bankruptcy state machine with bounded entry/exit criteria and monotonic discharge progression
- Chain-linked append-only JSONL ledger with SHA-256 digest chain and `hmac.compare_digest` tamper detection
- Discharge supersession protocol: last ledger entry per epoch_id is authoritative; stale re-activation is constitutionally blocked
- Constitutional gate: blank-intent mutation bypass during bankruptcy is a `GBPViolation`, not a pass

---

## [9.38.0] — 2026-04-03 — Phase 105 · INNOV-20 Constitutional Stress Testing

**Branch:** `feature/phase105-cst-impl`
**HUMAN-0 Gate:** Dustin L. Reid — ratified 2026-04-03
**Tests:** T105-CST-01..30 (30/30 PASS)
**Evidence:** `artifacts/governance/phase105/phase105_sign_off.json` · ILA-105-2026-04-03-001

### Deliverables
- `runtime/innovations30/constitutional_stress_test.py` — promoted from scaffold to full constitutional implementation
- `tests/test_phase105_cst.py` — T105-CST-01..30 (30/30 PASS)
- `server.py` — `GET /governance/stress-test/{epoch_id}`
- `ui/aponi/cst_panel.js` — scenario catalogue browser + gap explorer panel
- `artifacts/governance/phase105/` — 4 governance artifacts

### Constitutional Invariants (8 new · cumulative: 83 Hard-class)
`CST-0` · `CST-PERSIST-0` · `CST-GAP-0` · `CST-DIGEST-0` · `CST-FEED-0` · `CST-SCENARIO-0` · `CST-HALT-0` · `CST-DETERM-0`

### IP Claims
- Adversarial constitutional stress testing with margin-calibrated scenario catalogue for autonomous AI governance gap detection
- Append-only gap ledger with InvariantDiscovery feed emission enabling self-reinforcing constitutional rule discovery
- Deterministic SHA-256 digest chain over stress report records providing tamper-evident governance coverage audit trail

---

## [9.37.0] — 2026-04-03 — Phase 104 · INNOV-19 Governance Archaeology Mode

**Branch:** `feature/phase104-gam-impl`
**HUMAN-0 Gate:** Dustin L. Reid — ratified 2026-04-03
**Tests:** T104-GAM-01..30 (30/30 PASS)
**Evidence:** `artifacts/governance/phase104/phase104_sign_off.json` · ILA-104-2026-04-03-001

### Phase 104: INNOV-19 — Governance Archaeology Mode (GAM)

World-first cryptographically-verified mutation decision timeline reconstruction.
`GovernanceArchaeologist.excavate()` scans all distributed ledgers and assembles
a complete chronological `DecisionEvent` list for any mutation_id — from first
`proposed` event through every governance gate to final `approved`/`rejected`/
`promoted`/`rolled_back` outcome.

#### Module: `runtime/innovations30/governance_archaeology.py` (promoted from scaffold)

- `DecisionEvent` — carries event_type, timestamp, epoch_id, mutation_id, actor,
  outcome, details, ledger_hash; `to_dict()` is JSON-serializable
- `MutationTimeline` — carries timeline_digest (GAM-CHAIN-0), chain_verified,
  final_outcome (GAM-OUTCOME-0); accessors: proposal_event, governance_events,
  human_events, terminal_event
- `GovernanceArchaeologist` — `excavate()` sole entry point (GAM-0); scans `.jsonl`
  files across all ledger_roots; `_parse_event()` returns None for non-matching
  records (GAM-PARSE-0); fail-open throughout (GAM-FAIL-OPEN-0); events sorted
  ascending by timestamp, empty timestamp sorts first (GAM-SORT-0);
  `verify_chain()` re-computes digest for tamper detection (GAM-VERIFY-0);
  `export_timeline()` emits innovation=19 metadata (GAM-EXPORT-0)
- `_TERMINAL_EVENT_TYPES` — frozenset{approved, rejected, promoted, rolled_back}

#### New REST endpoint: `GET /governance/archaeology/{mutation_id}`

Returns timeline, final_outcome, timeline_digest, chain_verified, event_count, export.

#### New Aponi panel: `ui/aponi/gam_panel.js`

Interactive mutation_id search, outcome badge, SHA-256 chain indicator, chronological
event list, JSON export download. INNOV-19 · Phase 104.

#### Constitutional invariants introduced (9 new — Hard-class cumulative: 75)

- **GAM-0** — excavate() is the sole entry point; never raises on absent/empty ledger
- **GAM-CHAIN-0** — timeline_digest = "sha256:" + sha256(json.dumps(event_types)); prefixed
- **GAM-DETERM-0** — identical ledger state + mutation_id → identical digest; no RNG
- **GAM-SORT-0** — events sorted ascending by timestamp; empty timestamp sorts first
- **GAM-FAIL-OPEN-0** — corrupt JSONL lines silently skipped; no exception from excavate()
- **GAM-PARSE-0** — _parse_event() returns None for non-matching records; never raises
- **GAM-OUTCOME-0** — final_outcome from last terminal event; defaults "unknown"
- **GAM-EXPORT-0** — export_timeline() always carries innovation=19 and timeline_digest
- **GAM-VERIFY-0** — verify_chain() re-computes digest; returns bool; never raises


## [9.36.0] — 2026-04-03 — Phase 103 · INNOV-18 Temporal Governance Windows

**Branch:** `feature/phase103-tgov-impl`
**HUMAN-0 Gate:** Dustin L. Reid — ratified 2026-04-03
**Tests:** T103-TGOV-01..32 (32/32 PASS)
**Evidence:** `artifacts/governance/phase103/phase103_sign_off.json` · ILA-103-2026-04-03-001

### Phase 103: INNOV-18 — Temporal Governance Windows (TGOV)

World-first health-adaptive constitutional governance engine.
`TemporalGovernanceEngine.get_adjusted_ruleset()` dynamically modulates rule severity
based on live system health — softening non-critical rules during high-health epochs and
hardening all rules during system degradation. `ast_validity` is permanently `blocking`
regardless of health state (fail-safe anchor).

#### Module: `runtime/innovations30/temporal_governance.py` (extended)

- `GovernanceWindow` — dataclass carrying `baseline_severity`, `high_health_severity`,
  `low_health_severity`, and configurable `high_health_threshold` (0.85) / `low_health_threshold` (0.60)
- `TemporalGovernanceEngine` — `get_adjusted_ruleset(health_score)` sole entry point for
  severity resolution; `log_adjustment()` appends SHA-256-chained entries (TGOV-CHAIN-0);
  `audit_trail()` is fail-open — corrupt JSONL lines silently skipped (TGOV-CORRUPT-SKIP-0);
  `health_trend()` returns "improving" | "degrading" | "stable" from log history (TGOV-HEALTH-0);
  `export_window_config()` exports structured window metadata with `innovation=18` (TGOV-EXPORT-0)
- `DEFAULT_WINDOWS` — five constitutional rules: lineage_continuity, single_file_scope,
  ast_validity, entropy_budget, replay_determinism

#### New REST endpoint: `GET /governance/temporal/windows`

Returns `adjusted_ruleset`, `window_config`, `health_trend`, and last 10 chained audit entries.

#### New Aponi panel: `ui/aponi/tgov_panel.js`

Live health bar, severity table, GovernanceWindow configuration cards, SHA-256 chain audit trail.
Auto-refresh every 10 s. INNOV-18 · Phase 103.

#### Constitutional invariants introduced (9 new — Hard-class cumulative: 66)

- **TGOV-0** — effective_severity() never raises; unknown rules return "blocking"
- **TGOV-CHAIN-0** — log entries carry SHA-256 digest linked to prev entry; genesis anchor = "genesis"
- **TGOV-CORRUPT-SKIP-0** — audit_trail() silently skips corrupt JSONL lines; never raises
- **TGOV-FAIL-0** — unregistered rule → "blocking" (fail-closed gate, no exceptions)
- **TGOV-DETERM-0** — identical health score → identical adjusted ruleset (no RNG)
- **TGOV-PERSIST-0** — log_adjustment() uses Path.open("a") append mode; parent auto-created
- **TGOV-HEALTH-0** — health_trend() returns exactly one of "improving" | "degrading" | "stable"
- **TGOV-EXPORT-0** — export_window_config() always carries innovation=18 and window_count
- **TGOV-WINDOW-0** — GovernanceWindow: score ≥ high_threshold → high_sev; score < low_threshold → low_sev; else baseline

# CHANGELOG

## [9.35.0] — 2026-04-01 — Phase 102 · INNOV-17 Agent Post-Mortem Interviews (APM)

**Branch:** `feature/phase102-apm-impl`
**HUMAN-0 Gate:** Dustin L. Reid — ratified 2026-04-01
**Tests:** T102-APM-01..30 (30/30 PASS)
**Evidence:** `artifacts/governance/phase102/phase102_sign_off.json` · ILA-102-2026-04-01-001

### Phase 102: INNOV-17 — Agent Post-Mortem Interviews (APM)

World-first constitutional-governed post-mortem interviews for autonomous mutation agents.
`AgentPostMortemSystem.conduct_interview()` forces agents to articulate why they believed
a rejected mutation would pass, what constitutional gap they missed, and what correction
they would apply next time. These interviews are persisted to an append-only JSONL ledger
and fed back via `agent_recurring_gaps()` as calibration inputs to agent selection pressure.

#### New module: `runtime/innovations30/agent_postmortem.py`

- `AgentPostMortemSystem` — `conduct_interview()` sole entry point (APM-0); synthesizes
  `agent_self_assessment` from intent+strategy; maps `rejection_reasons` to structured
  `identified_gap` strings (APM-GAP-0); `_persist()` Path.open append-only (APM-PERSIST-0);
  `agent_recurring_gaps()` fail-open on missing/corrupt ledger (APM-LOAD-0)
- `AgentReasoningEntry` — `entry_digest` = `sha256:` + sha256(agent_id:mutation_id:
  identified_gap)[:16]; no RNG/datetime/uuid4 (APM-DETERM-0); carries agent_id, mutation_id,
  epoch_id, rejection_reasons, entry_digest (APM-CHAIN-0)
- Gap taxonomy: lineage → "Insufficient lineage chain verification"; entropy → "Entropy budget
  miscalculated"; scope → "Mutation scope exceeded single-file boundary"; ast → "AST validity
  issues not caught pre-submission"; replay → "Replay determinism requirements not met";
  other → "Constitutional rule violated: {reason}"

#### Constitutional invariants introduced

- **APM-0** — conduct_interview() is the sole entry point for post-mortem creation
- **APM-DETERM-0** — entry_digest is sha256(agent_id:mutation_id:identified_gap)[:16], prefixed "sha256:"; no RNG/datetime/uuid4
- **APM-PERSIST-0** — _persist() uses Path.open("a") append mode; builtins.open() forbidden; parent mkdir precedes every write
- **APM-GAP-0** — identified_gap MUST be a non-empty string; empty/whitespace is a Hard failure before persist
- **APM-LOAD-0** — agent_recurring_gaps() is fail-open; corrupt JSONL lines silently skipped; never raises on partial ledger corruption
- **APM-CHAIN-0** — every entry MUST carry agent_id, mutation_id, epoch_id, rejection_reasons (non-empty), entry_digest; missing any field is a Hard failure

- Hard-class invariants cumulative: **57** (APM-0 through APM-CHAIN-0 introduced)


## [9.34.0] — 2026-04-01 — Phase 101 · INNOV-16 Emergent Role Specialization (ERS)

**Branch:** `feature/phase101-ers-impl`
**HUMAN-0 Gate:** Dustin L. Reid — ratified 2026-04-01
**Tests:** T101-ERS-01..30 (30/30 PASS)
**Evidence:** `artifacts/governance/phase101/phase101_sign_off.json` · ILA-101-2026-04-01-001

### Phase 101: INNOV-16 — Emergent Role Specialization (ERS)

World-first data-driven emergent role discovery for autonomous code evolution agents.
`EmergentRoleSpecializer.discover_roles()` classifies agents into named archetypes
purely from accumulated behavioral evidence — no manual assignment. Two evidence gates
enforce quality: agents must accumulate >= 50 epochs (ERS-WINDOW-0) and achieve >= 0.65
target-type dominance (ERS-THRESHOLD-0) before a role is emitted.

#### New module: `runtime/innovations30/emergent_roles.py`

- `EmergentRoleSpecializer` — `record_behavior()` accumulates observations;
  `discover_roles()` sole assignment authority (ERS-0), window + threshold gated
  (ERS-WINDOW-0/ERS-THRESHOLD-0), sorted iteration (ERS-DETERM-0); `_save()` / `_load()`
  fail-open (ERS-PERSIST-0)
- `AgentBehaviorProfile` — `dominant_target` / `dominant_strategy` deterministic
  max (alphabetic tie-break); `specialization_score` = max_count/total; `avg_risk`;
  `avg_fitness_delta` — all pure properties, no entropy (ERS-DETERM-0)
- `EmergentRole` — 5 named archetypes: structural_architect, test_coverage_guardian,
  performance_optimizer, safety_hardener, adaptive_explorer; fallback: emergent_{strategy}

#### Constitutional invariants introduced

- **ERS-0** — discover_roles() is sole role-assignment authority; no manual assignment
- **ERS-WINDOW-0** — role not emitted before SPECIALIZATION_WINDOW (50) epochs
- **ERS-THRESHOLD-0** — role not emitted below SPECIALIZATION_THRESHOLD (0.65) score
- **ERS-DETERM-0** — classification deterministic; no datetime.now()/random/uuid4
- **ERS-PERSIST-0** — _save() Path.open("w") sort_keys=True; _load() fail-open

- Hard-class invariants cumulative: **56** (ERS-0 through ERS-PERSIST-0 introduced)


## [9.33.0] — 2026-04-01 — Phase 100 · INNOV-15 Agent Reputation Staking (ARS)

**Branch:** `feature/phase100-ars-impl`
**HUMAN-0 Gate:** Dustin L. Reid — ratified 2026-04-01
**Tests:** T100-ARS-01..30 (30/30 PASS)
**Evidence:** `artifacts/governance/phase100/phase100_sign_off.json` · ILA-100-2026-04-01-001

### Phase 100: INNOV-15 — Agent Reputation Staking (ARS)

World-first skin-in-the-game economics for autonomous code evolution agents.
`ReputationStakingLedger` converts hollow proposals into costly commitments: agents
stake credits before mutation promotion; governance failure burns the full stake
(STAKE-BURN-0); pass with measured fitness improvement rewards with a 1.5x multiplier.
Accumulated win-rate shapes agent selection pressure over time.

#### New module: `runtime/innovations30/reputation_staking.py`

- `ReputationStakingLedger` — `register_agent()`, `stake()` with balance gate and cap
  (STAKE-0/STAKE-CAP-0); `resolve()` with burn-or-reward logic (STAKE-BURN-0);
  `_persist()` Path.open append-only (STAKE-PERSIST-0); `_load()` fail-open
- `StakeRecord` — `stake_digest` = full sha256(agent_id:mutation_id:epoch_id:staked_amount)
  (STAKE-DETERM-0); `outcome` transitions: pending → passed | failed
- `InsufficientStakeError` — raised when balance < MIN_STAKE (STAKE-0)
- `StakeAlreadyResolvedError` — raised on double-resolution (STAKE-BURN-0)

#### Constitutional invariants introduced

- **STAKE-0** — agent balance must be >= MIN_STAKE before stake() commits
- **STAKE-CAP-0** — staked amount capped at 20% of pre-stake balance per proposal
- **STAKE-BURN-0** — resolve(passed=False) burns 100% of stake; no return path
- **STAKE-DETERM-0** — stake_digest is full sha256, no datetime/random/uuid4
- **STAKE-PERSIST-0** — Path.open("a") append-only; wallet writes use sort_keys=True

- Hard-class invariants cumulative: **51** (STAKE-0 through STAKE-PERSIST-0 introduced)


## [9.32.0] — 2026-04-01 — Phase 99 · INNOV-14 Constitutional Jury System (CJS)

**Branch:** `feature/phase99-cjs-impl`
**HUMAN-0 Gate:** Dustin L. Reid — ratified 2026-04-01
**Tests:** T99-CJS-01..30 (30/30 PASS)
**Evidence:** `artifacts/governance/phase99/phase99_sign_off.json` · ILA-99-2026-04-01-001

### Phase 99: INNOV-14 — Constitutional Jury System (CJS)

World-first governed multi-agent jury deliberation for autonomous mutation promotion
decisions. `ConstitutionalJury.deliberate()` convenes 3 independent evaluators with
deterministic seeds derived from mutation_id only. 2-of-3 quorum determines
`majority_verdict`. Dissenting verdicts are ledgered before return, feeding
`InvariantDiscoveryEngine` for ongoing constitutional rule derivation.

#### New module: `runtime/innovations30/constitutional_jury.py`

- `ConstitutionalJury` — `deliberate()` sole evaluation authority (CJS-0); quorum guard
  at construction (CJS-QUORUM-0); `_persist()` / `_record_dissent()` Path.open
  append-only (CJS-PERSIST-0); `dissent_records()` / `verdict_ledger()` fail-open
- `JuryDecision` — `decision_digest` = sha256(mutation_id:majority_verdict:
  approve_count:jury_size) (CJS-DETERM-0); stores `jury_size` for replay fidelity
- `JurorVerdict` — per-juror evaluation with deterministic `random_seed` (CJS-DETERM-0)
- `ConstitutionalJuryConfigError` — raised when jury_size < JURY_SIZE at construction
- `is_high_stakes(changed_files)` — CJS-0 routing predicate over HIGH_STAKES_PATHS

#### Constitutional invariants introduced

- **CJS-0** — deliberate() is sole authority for HIGH_STAKES_PATHS mutation evaluation
- **CJS-QUORUM-0** — majority requires >= 2-of-3 approve; ties default to reject
- **CJS-DETERM-0** — decision_digest and seeds are fully deterministic from mutation_id
- **CJS-DISSENT-0** — dissenting verdicts written to dissent ledger before return
- **CJS-PERSIST-0** — _persist() and _record_dissent() use Path.open append-only

- Hard-class invariants cumulative: **46** (CJS-0 through CJS-PERSIST-0 introduced)


Generated deterministically from merged governance metadata.

## [9.30.0] — 2026-03-31 — Phase 97 · INNOV-12 Mutation Genealogy Visualization (MGV)

**Branch:** `feature/phase97-mgv-impl`
**HUMAN-0 Gate:** Dustin L. Reid — ratified 2026-03-31
**Tests:** T97-MGV-01..30 (30/30 PASS)
**Evidence:** `artifacts/governance/phase97/phase97_sign_off.json` · ILA-97-2026-03-31-001

### Phase 97: INNOV-12 — Mutation Genealogy Visualization (MGV)

World-first evolutionary fitness tracking at the lineage level, not the individual mutation level.
`MutationGenealogyAnalyzer` annotates every edge in the mutation lineage graph with a
`PropertyInheritanceVector` — four orthogonal fitness deltas (correctness, efficiency, governance,
fitness) plus a deterministic sha256 digest — enabling population-genetics-level analysis of
software mutation history: productive lineages, evolutionary dead-ends, and cumulative directional
drift across any ancestry path.

#### New module: `runtime/innovations30/mutation_genealogy.py`

- `PropertyInheritanceVector` — immutable edge annotation; four fitness deltas; deterministic
  `digest` property (sha256, no RNG/datetime/uuid4); `net_improvement` four-axis average;
  `is_dead_end` threshold gate at -0.05
- `MutationGenealogyAnalyzer` — append-only JSONL ledger (Path.open); `record_inheritance()`;
  `productive_lineages(min_improvement=0.05)`; `dead_end_epochs()`; `evolutionary_direction()`
- `_load()` — fail-open: corrupt lines silently skipped, analyzer never blocked (MGV-0)
- `_persist()` — Path.open append mode, never builtins.open (MGV-PERSIST-0)

#### Invariants introduced (3 new Hard-class)
- `MGV-0` — _load() MUST never raise; any parse failure silently skipped; analyzer always available
- `MGV-DETERM-0` — digest MUST be deterministic: sha256(parent:child:net_improvement:.4f)[:16]; no RNG/datetime/uuid4
- `MGV-PERSIST-0` — _persist() MUST use Path.open append mode; no direct builtins.open call; append-only

**Total Hard-class invariants (cumulative):** 37

#### Findings resolved
- FINDING-97-001 (P2): T97-MGV-04 mock target — corrected from `builtins.open` to
  `runtime.innovations30.mutation_genealogy.Path.open` (module uses `Path.open`, not builtins)

- PR ID: `PR-PHASE97-01`
- Title: Phase 97 — INNOV-12 Mutation Genealogy Visualization (MGV)
- Lane/Tier: `innovations` / `constitutional`
- Evidence refs: `phase97-innov12-mgv-shipped` · `ILA-97-2026-03-31-001`


## [9.29.0] — 2026-03-30 — Phase 96 · INNOV-11 Cross-Epoch Dream State Engine (DSTE)

**Branch:** `feature/phase96-dste-impl`
**HUMAN-0 Gate:** Dustin L. Reid — ratified 2026-03-30
**Tests:** T96-DSTE-01..30 (30/30 PASS)
**Evidence:** `artifacts/governance/phase96/identity_ledger_attestation.json` · ILA-96-2026-03-30-001

### Phase 96: INNOV-11 — Cross-Epoch Dream State Engine (DSTE)

World-first constitutionally-governed cross-epoch mutation memory consolidation. Between active
epochs, the DreamStateEngine replays successful past mutations in novel cross-epoch combinations
to surface improvement candidates not discoverable within any single epoch — memory consolidation
for autonomous software evolution.

#### New module: `runtime/innovations30/dream_state.py` (full constitutional upgrade from scaffold)

- `DreamStateEngine.dream(epoch_memory, epoch_id, seed)` — full pipeline: gate-0 → seed-rng →
  novelty filter → ceiling cap → ledger commit → gate-1 → DreamStateReport
- `DreamCandidate` — immutable; genesis_digest is sha256(sorted source_epochs + id)
- `DreamLedgerEvent` — chained governance record; committed before candidates returned (DSTE-0)
- `DreamStateReport` — HUMAN-0 evidence artifact; structurally incapable of verdict='APPROVED'
- `evaluate_dream_gate_0()` — pre-execution: seed check (DSTE-1) + quorum check (DSTE-3)
- `evaluate_dream_gate_1()` — post-execution: ledger-first (DSTE-0) + ceiling (DSTE-6)
- `DreamGateViolation` — Hard-class violation exception; epoch aborts on this

#### Invariants introduced (7 new Hard-class)
DSTE-0 (ledger-first), DSTE-1 (determinism/seed), DSTE-2 (novelty floor ≥ 0.30),
DSTE-3 (pool quorum ≥ 3), DSTE-4 (chain integrity), DSTE-5 (no-write between epochs),
DSTE-6 (candidate ceiling ≤ 5)

**Total Hard-class invariants (cumulative):** 34

#### Findings resolved
- FINDING-96-001 (P1): agent state drift — corrected from `phase94_complete/9.27.0`
  to `phase95_complete/9.28.0` as branch initialization step

- PR ID: `PR-PHASE96-01`
- Title: Phase 96 — INNOV-11 Cross-Epoch Dream State Engine (DSTE)
- Lane/Tier: `innovations` / `constitutional`
- Evidence refs: `phase96-dste-impl-v9.29.0`


## [9.28.0] — 2026-03-29 — Phase 95 · Oracle×Dork Alignment · Free LLM · State Bus

**Branch:** `feature/phase95-oracle-dork-alignment`
**HUMAN-0 Gate:** Dustin L. Reid — ratified 2026-03-29
**Evidence:** `artifacts/governance/phase95/identity_ledger_attestation.json` · ILA-95-2026-03-29-001

### Phase 95: Oracle x Dork — Free LLM, Constitutional Intelligence, Bidirectional Bridge

ADAAD's two AI operator surfaces fully aligned. All paid API dependencies eliminated.
dork powered by Groq free tier + Ollama local + DorkEngine deterministic fallback.
Oracle lifted to 12-chip, 5-section structured intelligence surface with state bus relay.

#### dork (Whale.Dic) — Phase 95 Lift
- **Groq free tier** primary: llama-3.3-70b-versatile, real SSE streaming, 14,400 req/day
- **Ollama local** secondary: localhost:11434, full streaming, zero cost, configurable model
- **DorkEngine** fallback: deterministic constitutional rule engine, instant, always-available
- **Provider config modal**: switch Groq / Ollama / DorkEngine at runtime with key entry
- **Constitutional system prompt (CCB)**: gate, epoch, replay, agents, oracle context every query
- **Enhanced markdown (fmtMd)**: tables, headings, SHA/epoch refs, gate status coloring
- **Dynamic state-aware chips**: reflect live gate locks, blockers, open findings
- **Oracle bridge chip**: one-click Oracle context relay via ADAAD_STATE_BUS
- **ADAAD_STATE_BUS (L1)**: frozen shared state, updated every refreshAll()
- **Streaming cursor + word-reveal**: animated block cursor, 16ms/word DorkEngine fallback

#### Oracle (Aponi) — Phase 95 Lift
- **12 chips in 3 groups**: Evolution History, Governance Signal, Strategic Intelligence
- **5-section structured renderer**: Classification, Primary Signal (word-reveal), Constitutional Assessment, Vision Projection, Send-to-Dork button
- **Governance context injection (ORACLE-CONTEXT-0)**: epoch_id + gate_ok on every API call
- **ADAAD_STATE_BUS relay (BRIDGE-STATE-0)**: Oracle answer written to shared bus for Dork
- **Send-to-Dork button**: one-click Oracle-to-Dork handoff
- **Click-to-replay history**: restore answer from cache without re-fetch
- **Severity dot coloring**: divergence=amber, gate-violations=red, others=cyan

#### Invariants Asserted (10 new)
ORACLE-CONTEXT-0, ORACLE-RENDER-0, ORACLE-STREAM-0, ORACLE-AUDIT-0,
DORK-CONST-0, DORK-FREE-0, DORK-STREAM-0, DORK-AUDIT-0, BRIDGE-STATE-0, BRIDGE-FREE-0

---

## [9.27.0] — 2026-03-28 — Phase 94 · INNOV-10 Morphogenetic Memory (MMEM)

**Branch:** `feature/phase94-mmem-impl`
**HUMAN-0 Gate:** Dustin L. Reid — ratified 2026-03-28
**Tests:** T94-MMEM-01..33 (33/33 PASS)
**Evidence:** `artifacts/governance/phase94/identity_ledger_attestation.json` · ILA-94-2026-03-28-001

### World-First: Formally Encoded Architectural Self-Model as a Pre-Proposal Governance Primitive

ADAAD is the first autonomous AI evolution system to consult a formally encoded,
cryptographically anchored, human-authored self-model as a pre-proposal governance
surface in its evolution loop.

The problem MMEM solves is distinct from anything GovernanceGate or FitnessEngineV2
addresses: *identity drift* — the gradual erosion of a system's founding purpose through
a sequence of individually governance-approved but collectively identity-eroding mutations.
A mutation can pass every correctness test, score highly on all fitness dimensions, survive
adversarial red-teaming, and still violate what the system believes itself to be.

MMEM answers the question no prior gate could ask: **is this mutation consistent with
what this system believes itself to be?**

### New Module: `runtime/memory/identity_ledger.py`

- `IdentityLedger` — hash-chained, HUMAN-0-gated, append-only store of `IdentityStatement` objects
- `IdentityStatement` — dataclass with deterministic `statement_hash` computed via `_compute_hash`
  on `__post_init__`; fields: `statement_id`, `category`, `statement`, `author`, `epoch_id`,
  `predecessor_hash`, `statement_hash`, `human_signoff_token`, `rationale`
- `IdentityLedger.check()` — MMEM-0 outer guard; read-only (MMEM-READONLY-0); never raises
- `IdentityLedger.append()` — MMEM-LEDGER-0: validates `attestation_token` before any state mutation
- `IdentityLedger.verify_chain()` — O(n) chain integrity; raises `ChainIntegrityError` on discontinuity
- `IdentityLedger.load_genesis()` — classmethod; deserialises genesis seed; builds internal chain from scratch
- `_compute_hash()` — deterministic SHA-256: `sha256(json.dumps({id, predecessor, statement}, sort_keys=True))`;
  result prefixed `sha256:`; no datetime/random/uuid4 (MMEM-DETERM-0)
- `_score_consistency()` — keyword/anti-pattern heuristic scoring per category; returns `(score, violated_ids)`
- 9 statement categories: `purpose`, `architectural_intent`, `human_authority`, `lineage`,
  `failure_mode`, `active_goal`, `value`, `capability`, `boundary`
- 3 exception types: `ChainIntegrityError`, `IdentityAppendWithoutAttestationError`, `IdentityLedgerLoadError`

### New Module: `runtime/memory/identity_context_injector.py`

- `IdentityContextInjector.inject()` — MMEM-WIRE-0: never raises; sets `context.identity_consistency_score`
  and `context.identity_violated_statements` on `CodebaseContext` before Phase 1
- `_build_intent()` — derives `mutation_intent` from context fields (`file_path`, `description`, `mutation_type`)
- `_build_diff()` — derives `diff_summary` from `before_source`/`after_source`
- `InjectionResult` — dataclass with `consistency_score`, `violated_statements`, `fallback_used`, `notes`

### New Module: `runtime/lineage/lineage_ledger_v2.py`

- `LineageLedgerV2` — second-generation hash-chained lineage store
- `record_proposal()`, `record_approval()`, `record_deployment()` — typed event recording
- `attach_identity_result()` — Phase 94 MMEM enrichment: co-commits `IdentityConsistencyResult`
  to an existing lineage event, making the identity signal part of the immutable audit trail
- `semantic_proximity_score()` — Phase 94 stub; semantic embedding deferred to Phase 95
- `verify_chain()` — O(n) chain integrity for lineage events
- `LineageEvent` — includes `identity_consistency_score` and `identity_violated_statements` fields

### Modified: `runtime/evolution/evolution_loop.py`

- Phase 0d wiring added: `IdentityContextInjector.inject()` called before Phase 1 (propose)
- `self._identity_injector = None` slot added to `__init__` (MMEM-WIRE-0: optional, fail-open)
- Outer try/except around Phase 0d ensures epoch never blocked by MMEM error

### Governance Artifact: `artifacts/governance/phase94/identity_ledger_seed.json`

- 8 genesis IdentityStatements (IS-001..IS-008) authored by ArchitectAgent, attested by HUMAN-0
- Terminal chain hash: `3f570614801293539bfa8d2ff4ae17e6eb65ab7adfc38e0110c0badcce84e5b4`
- Attestation: ILA-94-2026-03-28-001 · Dustin L. Reid · 2026-03-28

| ID | Category | Statement (condensed) |
|---|---|---|
| IS-001 | purpose | ADAAD exists to demonstrate autonomous AI evolution is safe, auditable, and governable. |
| IS-002 | architectural_intent | ADAAD is a governed evolution engine, not a code generator. The pipeline is the product. |
| IS-003 | human_authority | HUMAN-0 holds inviolable authority over constitutional evolution, identity statements, release promotion. |
| IS-004 | lineage | Every mutation has a traceable cryptographic proof chain from proposal to deployment. |
| IS-005 | failure_mode | ADAAD fails closed. Governance errors are never silent. |
| IS-006 | active_goal | ADAAD is completing 30 world-first innovations in governed autonomous evolution. |
| IS-007 | architectural_intent | Constitution = rules. GovernanceGate = enforcement. IdentityLedger = identity. Non-substitutable. |
| IS-008 | active_goal | ADAAD targets enterprise-grade trust: SOC 2 auditability, patent-grade novelty, cryptographic evidence chains. |

### Constitutional Invariants Introduced (6 new Hard-class invariants)

| Invariant | Rule |
|---|---|
| `MMEM-0` | `IdentityLedger.check()` MUST never raise. Any failure MUST return `fallback_used=True`. Epoch is never blocked. |
| `MMEM-CHAIN-0` | Every `IdentityStatement` MUST carry the SHA-256 hash of its predecessor. Discontinuity raises `ChainIntegrityError`. |
| `MMEM-READONLY-0` | `check()` is READ-ONLY. No append, modify, or delete of ledger state in the check path. |
| `MMEM-WIRE-0` | `run_epoch()` MUST call `IdentityContextInjector` before Phase 1. Failure never blocks the epoch. |
| `MMEM-LEDGER-0` | `append()` without `attestation_token` raises `IdentityAppendWithoutAttestationError` before any state mutation. |
| `MMEM-DETERM-0` | Identical `(statement_id, statement, predecessor_hash)` → identical `statement_hash`. No datetime/random/uuid4. |

**Total Hard-class invariants (cumulative):** CSAP-0/1, ACSE-0/1, TIFE-0, SCDD-0, AOEP-0,
CEPD-0/1, LSME-0/1, AFRT-0/GATE-0/INTEL-0/LEDGER-0/CASES-0/DETERM-0,
AFIT-0/DETERM-0/BOUND-0/WEIGHT-0,
MMEM-0/CHAIN-0/READONLY-0/WIRE-0/LEDGER-0/DETERM-0 — **27 invariants**

---

## [9.26.0] — 2026-03-27 — Phase 93 · INNOV-09 Aesthetic Fitness Signal (AFIT)

**Branch:** `feature/phase93-afit-engine`
**HUMAN-0 Gate:** Dustin L. Reid — ratified 2026-03-27
**Tests:** T93-AFIT-01..33 (33/33 PASS)
**Evidence:** `artifacts/governance/phase93/phase93_sign_off.json`

### World-First: Code Aesthetics as a Constitutionally-Bounded Fitness Signal

ADAAD now evaluates code readability, naming quality, and structural clarity as a
first-class fitness dimension — the first autonomous evolution system to treat code
aesthetics as a constitutionally-governed, weighted signal in its fitness engine.

Technical debt is measurable. A system optimising only for test coverage and performance
will systematically accumulate cognitive complexity that makes future mutations harder and
audit trails less readable. AFIT captures this with five orthogonal AST dimensions.

### New Module: `runtime/evolution/aesthetic_fitness.py`

- `AestheticFitnessScorer.score(source)` — full scoring pipeline: AST parse →
  5 sub-signal computation → composite → `AestheticFitnessReport`; never raises (AFIT-0)
- `AestheticSubScores` — frozen breakdown of all five dimensions, each in [0.0, 1.0]
- `AestheticFitnessReport` — deterministic output with `algorithm_version` for replay
- Five sub-signals:
  - `function_length_score` — shorter functions score higher; ideal ≤ 15 lines
  - `name_entropy_score` — fraction of identifiers meeting min-length threshold (≥ 3 chars)
  - `nesting_depth_score` — lower average max-nesting-depth scores higher; cap at depth 6
  - `comment_ratio_score` — comment density relative to cyclomatic complexity
  - `cyclomatic_score` — inverse of average McCabe complexity per function

### Modified: `runtime/evolution/fitness_v2.py`

- `aesthetic_fitness` added as 7th signal in `_SIGNAL_KEYS` (canonical order preserved)
- `_DEFAULT_WEIGHTS` rebalanced — `aesthetic_fitness: 0.05`; six prior signals
  proportionally adjusted; weights sum exactly to 1.0
- `FitnessContext.aesthetic_fitness: float = 0.5` — neutral default (AFIT-0 fallback semantics)
- `FitnessScores.aesthetic_fitness` — output field + `to_dict()` inclusion
- `FitnessEngineV2.score()` — `aesthetic_fitness` wired into `raw_signals` dict

### Constitutional Invariants Introduced (4 new Hard-class invariants)

| Invariant | Rule |
|---|---|
| `AFIT-0` | `AestheticFitnessScorer.score()` MUST never raise. Any failure MUST return fallback report with `score=0.5` and `fallback_used=True`. |
| `AFIT-DETERM-0` | Identical source string → identical `AestheticFitnessReport`. No `datetime.now()`, `random`, or `uuid4()` in the scoring path. |
| `AFIT-BOUND-0` | All sub-scores MUST be in [0.0, 1.0] before composite weighting. Composite score MUST be in [0.0, 1.0]. |
| `AFIT-WEIGHT-0` | `aesthetic_fitness` weight in `FitnessConfig` MUST be in [0.05, 0.30]. Below 0.05 is noise; above 0.30 over-weights style over correctness. |

**Total Hard-class invariants (cumulative):** CSAP-0/1, ACSE-0/1, TIFE-0, SCDD-0, AOEP-0,
CEPD-0/1, LSME-0/1, AFRT-0/GATE-0/INTEL-0/LEDGER-0/CASES-0/DETERM-0,
AFIT-0/DETERM-0/BOUND-0/WEIGHT-0 — **21 invariants**

---

## [9.25.0] — 2026-03-27 — Phase 92 · INNOV-08 Adversarial Fitness Red Team (AFRT)

**Branch:** `feature/phase92-afrt-engine` + `feature/phase92-afrt-cel-integration` + `feature/phase92-release-sweep`
**HUMAN-0 Gate:** Dustin L. Reid — ratified 2026-03-27
**PRs merged:** #567 (CEL integration), #568 (AFRT engine core)
**Tests:** T92-AFRT-01..23 (23/23 PASS) + T92-CEL-01..07 (7/7 PASS) = **30/30 PASS**

### World-First: Constitutionally-Governed Adversarial Peer-Review as a CEL Gate

ADAAD now subjects every mutation proposal to targeted adversarial falsification by a
dedicated Red Team Agent *before* GovernanceGateV2 scoring — the first governed autonomous
evolution system to embed adversarial peer-review as a constitutional gate in its evolution loop.

Where LSME (Phase 91) validates *behaviour under execution*, AFRT generates *targeted
adversarial test cases* against proposals, specifically probing coverage paths the proposing
agent did not exercise. A mutation that survives the Red Team has been stress-tested beyond
its own suite.

### New — Track A: Core AFRT Engine (`runtime/evolution/afrt_engine.py`)

- `AdversarialRedTeamAgent.evaluate()` — full red-team pipeline: CodeIntel query →
  adversarial case generation → sandbox execution → verdict → ledger commit → report return
- `AdversarialCaseGenerator` — deterministic 1–5 adversarial cases per proposal, derived
  from CodeIntelModel uncovered path surfaces (AFRT-INTEL-0 / AFRT-DETERM-0)
- `RedTeamFindingsReport` — structured falsification result: PASS or RETURNED verdict,
  adversarial case set, failure cases, report hash, trace_committed flag
- `RedTeamLedgerEvent` — LineageLedgerV2 event committed *before* result returned (AFRT-LEDGER-0)
- `_DefaultSandboxRunner` — read-only sandbox executor with deterministic outcome seam
- `CELStepOrderViolation` / `AFRTEngineError` — constitutional exception types
- `_compute_report_hash()` / `_deterministic_case_id()` — AFRT-DETERM-0 compliant hash helpers

### New — Track B: Aponi AFRT Dashboard (`ui/aponi/afrt_panel.js`)

- Real-time `AFRT_VERDICT` WebSocket subscription with 5s reconnect + 8s poll fallback
- Rolling 30-finding feed: PASS/RETURNED verdict badges, per-finding adversarial case expansion
- Ledger commit status badges (AFRT-LEDGER-0 trace_committed indicator)
- AFRT-0 constitutional violation alert: any `approval_emitted=true` triggers hard alert
- Stats bar: total evaluated, PASS count, RETURNED count, live pass-rate %
- All 6 AFRT invariants rendered in constitutional footer

### CEL Wiring (Track A — `runtime/evolution/constitutional_evolution_loop.py`)

- AFRT-GATE inserted as **CEL Step 10** in the 16-step dispatch table (CEL-ORDER-0)
- Executes after PARETO-SELECT (Step 9) and before GOVERNANCE-GATE (Step 11)
- Graceful degradation: `afrt_agent=None` logs warning and passes — preserves pre-Phase-92 test compatibility

### Constitutional Invariants Introduced (6 new Hard-class invariants)

| Invariant | Rule |
|---|---|
| `AFRT-0` | Red Team NEVER emits approval. `approval_emitted` is structurally False on every report. |
| `AFRT-GATE-0` | AFRT evaluates after LSME (Step 6) and before GovernanceGateV2. Any other ordering raises `CELStepOrderViolation`. |
| `AFRT-INTEL-0` | Adversarial cases MUST be sourced from `CodeIntelModel.get_uncovered_paths()`. Cases without CodeIntel data are inadmissible. |
| `AFRT-LEDGER-0` | `RedTeamLedgerEvent` MUST be committed to `LineageLedgerV2` before the report is returned (ledger-first principle). |
| `AFRT-CASES-0` | Generator MUST produce 1–5 cases per proposal. Zero cases = engine failure, abort epoch. |
| `AFRT-DETERM-0` | Identical proposal + CodeIntel snapshot → identical adversarial case set. No `datetime.now()`, `random`, or `uuid4()` in case-generation path. |

### Governance Artifacts

- `artifacts/governance/phase92/phase92_sign_off.json` — HUMAN-0 ratification record

### IP Claim (INNOV-08)

World-first: constitutionally-governed adversarial peer-review gate in an autonomous AI
evolution loop. A dedicated Red Team Agent performs targeted falsification of mutation
proposals — probing coverage gaps the proposing agent did not exercise — before governance
scoring. Constitutionally incapable of approving mutations (AFRT-0 structural invariant).

---

## [9.24.1] — 2026-03-24 — Phase 91 Audit Hardening · Senior Audit Pass

**Branch:** `fix/phase91-audit-5patch`
**Audit basis:** Senior Audit Thesis v9.24.0 (2026-03-24)

### Fixed — P1

- **FINDING-91-001 / LINEAGE-CACHE-01** (`runtime/evolution/lineage_v2.py`): `verify_integrity(max_lines=N)` early-return path now advances `_verified_tail_hash` to the last verified prefix entry before returning. Previously the pointer was left `None`, causing every subsequent `_last_hash()` call to trigger a full O(n) re-scan — an O(n²) total cost at ledger scale. Postcondition contract annotated inline.
- **FINDING-91-002 / CI-DUPE-01** (`.github/workflows/ci.yml`): Renamed the first (dead) `semantic-diff-determinism` job definition to `semantic-diff-determinism-baseline`. Added to `ci-gating-summary` `needs:` chain and summary table. Both fixture sets now run and gate independently.
- **FINDING-91-003 / PYPROJECT-VER-01** (`pyproject.toml`): `version` aligned from `9.15.0` to `9.24.0` (9 minor-version drift). `pip`, PyPI, and GitHub Packages now report correct package metadata.

### Fixed — P2

- **FINDING-91-004 / PHONE-LIBCST-01** (`requirements.phone.txt`): Added `libcst>=1.1.0,<2.0`. The omission silently disabled the full constitutional AST validation subsystem on mobile (Pydroid3/Termux path). `libcst` is pure-Python and installs on armv8l without issue.
- **FINDING-91-005 / AUDIT-TEL-01** (`runtime/audit_auth.py`): `load_audit_tokens()` now emits structured log events on all three failure modes (absent env var: DEBUG; malformed JSON: WARNING; wrong type: WARNING). Scope checks in `require_audit_read_scope` and `require_audit_write_scope` replaced with `hmac.compare_digest` for constant-time comparison.

### Tests Added

- `tests/test_lineage_v2_cache_coherence.py` — 4 `@autonomous_critical` tests (CACHE-01/02/03/04)
- `tests/test_audit_auth_telemetry.py` — 6 `@autonomous_critical` tests (AUDIT-TEL-01)

### Still Open (GA-blocking)

- **FINDING-66-003**: Patent filing — awaiting provisional application number from IP counsel.
- **FINDING-66-004**: Ed25519 2-of-3 key ceremony — runbook delivered; ceremony execution deferred to key holders.


### World-First: Constitutionally-Governed Shadow Execution Against Live Traffic

ADAAD now executes proposed mutations in a zero-write, read-only shadow against its
own live production request traffic before governance approval — the first governed
autonomous evolution system to use live traffic as a fitness signal while maintaining
all constitutional guarantees through an enforced zero-write shadow contract.

**New module:** `runtime/evolution/lsme_engine.py`

- `ShadowContract` — constitutional zero-write contract; `is_zero_write()` enforces
  LSME-0: all three fields (write, egress, db) MUST be False before any shadow runs
- `ShadowBudget` — resource bounds: wall-clock ms, CPU ms, memory MB, max requests
- `TrafficRequest` / `BaselineResponse` / `ShadowResponse` — request/response data types
- `ShadowFitnessReport` — complete evidence artifact: divergence_rate, error_delta,
  P99 latency delta, invariant_failures, shadow_responses; hash-chained; ledger-ready
- `evaluate_lsme_gate_0()` — pre-execution gate: contract checks (1-3), AST write/egress
  scan (4-5), budget advisory (6); only LSME_BUDGET_EXCEEDED is non-blocking
- `evaluate_lsme_gate_1()` — post-execution gate: divergence rate, error regression,
  P99 latency regression, invariant failures, trace archival (LSME-1)

**Invariants introduced:**
- `LSME-0`: Shadow execution MUST be zero-write. Write or egress detection (AST or
  runtime) is a hard block and HUMAN-0 alert. LSME_BUDGET_EXCEEDED is the only
  non-blocking failure — mutation proceeds on synthetic fitness only.
- `LSME-1`: ShadowFitnessReport MUST be committed to the evidence ledger BEFORE any
  divergence comparison begins. trace_committed=False → LSME_SHADOW_ABORTED always.

**Failure modes:** `LSME_WRITE_DETECTED`, `LSME_EGRESS_DETECTED`, `LSME_BUDGET_EXCEEDED`,
`LSME_ERROR_REGRESSION`, `LSME_LATENCY_REGRESSION`, `LSME_TRACE_INCOMPLETE`,
`LSME_CONTRACT_VIOLATION`, `LSME_INVARIANT_FAILURE`, `LSME_DIVERGENCE_EXCEEDED`

**Tests:** `tests/test_phase91_lsme.py` — T91-LSME-01..20 (20/20 PASS)

---

### 🏁 Phase 87 Innovation Sequence — COMPLETE

All 7 innovations from the HUMAN-0 ratified Phase 87 Innovation Architecture Plan
have been implemented, tested, and shipped:

| ID | Name | Abbr | Version | Tests | Invariants |
|----|------|------|---------|-------|------------|
| INNOV-01 | Constitutional Self-Amendment Protocol | CSAP | v9.18.0 | 20/20 | CSAP-0, CSAP-1 |
| INNOV-02 | Adversarial Constitutional Stress Engine | ACSE | v9.19.0 | 20/20 | ACSE-0, ACSE-1 |
| INNOV-03 | Temporal Invariant Forecasting Engine | TIFE | v9.20.0 | 20/20 | TIFE-0 |
| INNOV-04 | Semantic Constitutional Drift Detector | SCDD | v9.21.0 | 40/40 | SCDD-0 |
| INNOV-05 | Autonomous Organ Emergence Protocol | AOEP | v9.22.0 | 20/20 | AOEP-0 |
| INNOV-06 | Cryptographic Evolution Proof DAG | CEPD | v9.23.0 | 20/20 | CEPD-0, CEPD-1 |
| INNOV-07 | Live Shadow Mutation Execution | LSME | v9.24.0 | 20/20 | LSME-0, LSME-1 |

**Total new tests (this sequence):** 160  
**New Hard-class invariants:** CSAP-0, CSAP-1, ACSE-0, ACSE-1, TIFE-0, SCDD-0, AOEP-0, CEPD-0, CEPD-1, LSME-0, LSME-1

---

## [9.23.0] — 2026-03-23 — Phase 90 INNOV-06 · Cryptographic Evolution Proof DAG (CEPD)

### World-First: Cryptographic DAG Proof of Evolutionary Lineage

ADAAD now produces an unbreakable, tamper-evident proof of evolutionary lineage from
genesis to current state — the first autonomous evolution system to generate a
cryptographic DAG linking every mutation to ALL of its causal ancestors via Merkle
root.  CryptographicProofBundle is independently verifiable by third parties without
system access, and is structured for legal admissibility (FINDING-66-003).

**New module:** `runtime/evolution/cepd_engine.py`

- `CEPDDagNode` — DAG node: mutation_id, epoch_id, parent_node_ids, ancestor_merkle_root,
  payload_hash, HMAC/Ed25519 signature, cepd_version
- `CryptographicProofBundle` — self-contained proof: dag_node + complete ancestor_set +
  merkle_root + lineage_depth + genesis_traceable + bundle_hash; primary patent artifact
- `CEPDDagStore` — append-only in-memory DAG; genesis pre-seeded; BFS genesis traceability
- `compute_ancestor_merkle_root()` — deterministic SHA-256 Merkle over sorted ancestor IDs
- `verify_merkle_determinism()` — CEPD-0 self-check; two independent computations
- `evaluate_cepd_gate_0()` — 5-check DAG integrity gate; fail-closed; appends node on pass
- `verify_proof_bundle()` — independent verifier surface (no system access required)
- `sign_node()` / `verify_signature()` — HMAC-SHA256 (offline) or Ed25519 (PyNaCl)

**Invariants introduced:**
- `CEPD-0`: Every DAG node MUST carry an ancestor_merkle_root that is deterministically
  reproducible from its causal ancestor set alone (CEPD_MERKLE_NONDETERMINISTIC → rejected).
- `CEPD-1`: Every DAG node MUST be traceable to the genesis node by following parent edges
  (CEPD_GENESIS_UNTRACEABLE is a constitutional integrity failure; HUMAN-0 alert required).

**Failure modes:** `CEPD_ANCESTOR_INCOMPLETE`, `CEPD_SIGNATURE_INVALID`,
`CEPD_MERKLE_NONDETERMINISTIC`, `CEPD_GENESIS_UNTRACEABLE`, `CEPD_DEPTH_EXCEEDED`,
`CEPD_NODE_INCOMPLETE`, `CEPD_NODE_REJECTED`

**Tests:** `tests/test_phase90_cepd.py` — T90-CEPD-01..20 (20/20 PASS)

**Next:** INNOV-07 LSME (v9.24.0) — Live Shadow Mutation Execution

---

## [9.22.0] — 2026-03-23 — Phase 89 INNOV-05 · Autonomous Organ Emergence Protocol (AOEP)

### World-First: Constitutionally-Governed Autonomous Architectural Self-Extension

ADAAD can now autonomously identify behavioral gaps in its capability surface and
propose entirely new organs — new architectural subsystems — to address those gaps.
All proposals require HUMAN-0 ratification; no organ constitutionally exists until
the ratification event is appended to governance_events.jsonl.

**New module:** `runtime/evolution/aoep_protocol.py`

- `CapabilityGapSignal` — detected capability gap: sustained_epochs, affected mutation
  classes, candidate_organ_purpose, deterministic gap_id + gap_hash
- `FailurePatternSummary` — recurring failure patterns attributed to a structural gap
- `OrganManifestEntry` — single organ in the current organ manifest (capability surface)
- `OrganProposal` — formal proposal for a new organ; always status PENDING_HUMAN_0 on
  GATE-0 pass; human_0_required is unconditionally True
- `Human0RatificationPayload` — HUMAN-0 sign-off bundle: proposal_id, ratification_hash,
  operator_id, timestamp, human_0_signature, predecessor_hash
- `RatificationRecord` — hash-chained ledger-ready record of GATE-1 outcome
- `AOEPCooldownTracker` — per-gap re-evaluation cooldown (AOEP_REEVAL_COOLDOWN_EPOCHS=5)
- `evaluate_aoep_gate_0()` — 5-check gap qualification gate; fail-closed
- `evaluate_aoep_gate_1()` — HUMAN-0 ratification gate; AOEP-0 non-bypassable

**Invariant introduced:**
- `AOEP-0`: Every OrganProposal MUST be submitted to HUMAN-0 before implementation.
  AOEP-GATE-1 has NO automated bypass — empty human_0_signature ALWAYS produces
  AOEP_HUMAN_0_BLOCKED; the organ does not constitutionally exist until ratification
  event is appended to governance_events.jsonl.

**Failure modes:** `AOEP_GAP_UNQUALIFIED`, `AOEP_GAP_ADDRESSABLE`, `AOEP_HUMAN_0_BLOCKED`,
`AOEP_PROPOSAL_INCOMPLETE`, `AOEP_MANIFEST_CONFLICT`, `AOEP_INSUFFICIENT_MEMORY`,
`AOEP_INSUFFICIENT_PATTERNS`, `AOEP_SIGNATURE_MISSING`, `AOEP_RATIFICATION_HASH_MISMATCH`

**Tests:** `tests/test_phase89_aoep.py` — T89-AOEP-01..20 (20/20 PASS)

**Next:** INNOV-06 CEPD (v9.23.0) — Cryptographic Evolution Proof DAG

---

## [9.21.0] — 2026-03-23 — Phase 87 INNOV-04 · Semantic Constitutional Drift Detector (SCDD)

### World-First: Semantic Drift Detection for Constitutional Invariants

ADAAD now detects when constitutional invariants have drifted semantically — when the
same rule text begins governing a different behavioral surface due to system substrate
evolution — the first autonomous evolution system to distinguish rule text stability
from behavioral coverage drift across epochs.

**New module:** `runtime/evolution/scdd_engine.py`

- `BehavioralSurfaceSnapshot` — per-epoch empirical statistics of how a rule fires:
  evaluations, blocks, block_rate, mean_fitness_delta_blocked, touched_mutation_classes
- `SemanticInvariantFingerprint` — deterministic fingerprint composed of statement_hash
  + surface_hash + composite_hash; basis for cross-epoch drift comparison
- `DriftVector` — per-invariant drift measurement: coverage_delta (40%), precision_delta
  (30%), class_surface_delta (30%); statement change adds 0.10 bonus; clamped to [0, 1]
- `ConstitutionalDriftReport` — full output; hash-chained; produced on ALL outcomes
  (STABLE, REVIEW_REQUIRED, BLOCKED); contains all DriftVectors + max_drift_score
- `SCDDEvaluationInput` — input bundle: baseline fingerprints, current fingerprints,
  rule statements, predecessor_hash
- `compute_semantic_fingerprint()` — deterministic; SHA-256(statement) + SHA-256(surface
  JSON) → SHA-256(statement_hash + surface_hash); replay-verified
- `compute_drift_vector()` — weighted composite of coverage, precision, class-surface
  delta + statement change bonus; `_classify_drift()` maps score → DriftClass
- `evaluate_scdd_gate_0()` — 7-check gate; fail-closed; full report on all outcomes

**Invariant introduced:**
- `SCDD-0`: SCDD MUST run every N epochs; any invariant with semantic drift score ≥
  SCDD_CRITICAL_THRESHOLD (0.75) MUST produce SCDD_BLOCKED outcome, blocking further
  mutation progress until the drifted invariant is reviewed through CSAP.

**Failure modes covered:** `SCDD_CRITICAL_DRIFT_FOUND`, `SCDD_FINGERPRINT_NONDETERMINISTIC`,
`SCDD_BASELINE_MISSING`, `SCDD_EMPTY_INVARIANT_SET`, `SCDD_SURFACE_HASH_CONFLICT`

**Drift classification thresholds:** STABLE < 0.30 ≤ MINOR < 0.55 ≤ MAJOR < 0.75 ≤ CRITICAL

**Tests:** `tests/test_phase87_innov04_scdd.py` — T87-SCDD-01..20 (20/20 PASS)

**Next:** INNOV-05 AOEP (v9.22.0) — Autonomous Organ Emergence Protocol

---

## [9.20.0] — 2026-03-23 — Phase 87 INNOV-03 · Temporal Invariant Forecasting Engine (TIFE)

### World-First: Multi-Epoch Constitutional Pre-Validation

ADAAD now evaluates proposed mutations against simulated *future* system states before
governance approval — the first autonomous evolution system to implement multi-epoch
constitutional pre-validation.  Governance transforms from reactive to predictive.

**New module:** `runtime/evolution/tife_engine.py`

- `TIFEMutationInput` — mutation projection enriched with capability deltas, governance debt, trajectory flags
- `VisionProjection` — trajectory forecast baseline (dead-end paths, debt trajectory, capability deltas)
- `CapabilityGraphSnapshot` — CapabilityGraphV2 projection; `non_redundant_ids()` for regression detection
- `InvariantEvaluationReport` — per-epoch invariant status, projected debt, ISI contribution
- `TemporalViabilityReport` — full output; hash-chained; specifies first_violation_epoch on BLOCKED
- `evaluate_tife_gate_0()` — 5-check temporal viability gate; fail-closed; report on both outcomes
- `analyse_isi_trend()` — rolling ISI health signal for AnalysisAgent; degrading/stable/improving + alert

**Invariant introduced:**
- `TIFE-0`: Every mutation MUST pass TIFE-GATE-0 (ISI ≥ 0.85, no debt breach, no dead-end,
  no capability regression) before GovernanceGate v2.  Failed mutations enter `temporal_hold`;
  TemporalViabilityReport specifies the remediation epoch.

**Failure modes covered:** `TIFE_ISI_BELOW_THRESHOLD`, `TIFE_DEBT_HORIZON_BREACH`,
`TIFE_TRAJECTORY_DEAD_END`, `TIFE_CAPABILITY_REGRESSION`, `TIFE_SIMULATION_NONDETERMINISTIC`

**Tests:** `tests/test_phase87_innov03_tife.py` — T87-TIFE-01..20 (20/20 PASS)

**Next:** INNOV-04 SCDD (v9.21.0) — Semantic Constitutional Drift Detector

---

## [9.19.0] — 2026-03-23 — Phase 87 INNOV-02 · Adversarial Constitutional Stress Engine (ACSE)

### World-First: Governed Constitutional Adversarial Red-Teaming

ADAAD now red-teams its own mutation proposals and constitutional amendments before they
advance to GovernanceGate v2.  ACSE is the immune system's attack function — the system
stress-tests itself constitutionally before anything merges.

**New module:** `runtime/evolution/acse_engine.py`

- `MutationCandidate` — minimal projection of a mutation fed to ACSE; decoupled from full mutation model
- `AdversarialBudget` — resource envelope: wall-clock ms, LLM call quota, max vector count
- `AdversarialTestVector` — single deterministic adversarial probe; class, verdict, violation detail, seed audit
- `AdversarialEvidenceBundle` — full output package; hash-chained; mandatory GovernanceGate v2 input
- `derive_adversarial_seed()` — `SHA-256(lineage_digest + epoch_id)`; determinism-verified on every run
- `_generate_invariant_probe_vectors()` — ≥ 5 canonical vectors per touched invariant class (ACSE-0)
- `_generate_boundary_stress_vectors()` — one probe per claimed fitness threshold at 1% boundary delta
- `_generate_replay_interference_vectors()` — 3 isolation-context replay probes
- `evaluate_acse_gate_0()` — 8-check gate; fail-closed; full `AdversarialEvidenceBundle` on all outcomes
- `acse_csap_gate1_check()` — **hardened CSAP-GATE-1 check 3**: advisory → hard FAIL; `ACSE_CLEAR` bundle required

**Invariants introduced:**
- `ACSE-0`: ACSE MUST produce ≥ 5 deterministic adversarial test vectors per invariant class touched
  before any mutation proceeds to GovernanceGate v2
- `ACSE-1`: `AdversarialEvidenceBundle` MUST be hash-chained and archived before mutation state advances

**Failure modes covered:** `ACSE_BOUNDARY_BREACH`, `ACSE_VIOLATION_FOUND`, `ACSE_BUDGET_EXCEEDED`,
`ACSE_SEED_NONDETERMINISTIC`, `ACSE_COUNTER_EVIDENCE_UNSIGNED`

## [9.27.0] — 2026-03-28 — Phase 94 · INNOV-10 Morphogenetic Memory (MMEM)
