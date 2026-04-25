# ArchitectAgent Constitutional Specification — v3.1.0

![Governance: Fail-Closed](https://img.shields.io/badge/Governance-Fail--Closed-critical)
![ArchitectAgent: Canonical](https://img.shields.io/badge/ArchitectAgent-Canonical-a855f7)
![Version: 9.93.0](https://img.shields.io/badge/version-9.93.0-00d4ff)
![Phase: 6 — Autonomous Roadmap Self-Amendment](https://img.shields.io/badge/Phase_6-Roadmap_Self--Amendment-f59e0b)

> **Authority:** ArchitectAgent · ADAAD Constitutional Governance
> **Scope:** Phase 6 — Autonomous Roadmap Self-Amendment completion (M6-03, M6-04, M6-05)
> **Effective:** 2026-03-07
> **Supersession status:** `ARCHITECT_SPEC_v3.0.0.md` was retired and not retained in-repo; all canonical references are consolidated into `docs/governance/ARCHITECT_SPEC_v3.1.0.md`
> **Status:** CANONICAL — machine-interpretable, audit-ready, replay-verifiable
> **Authored by:** ArchitectAgent (constitutional governance role; no code generation authority)

---

## Supersession Note (Path Mapping)

- `docs/governance/ARCHITECT_SPEC_v3.0.0.md` → `docs/governance/ARCHITECT_SPEC_v3.1.0.md`

`ARCHITECT_SPEC_v3.0.0.md` is not present in repository history and is treated as permanently
superseded. All canonical references now resolve to this v3.1.0 artifact.

## Preamble

This document is the authoritative ArchitectAgent specification for ADAAD v3.1.0. It governs
the completion of Phase 6 (Autonomous Roadmap Self-Amendment) across three remaining milestones:

- **M6-03** — `RoadmapAmendmentEngine` wired into `EvolutionLoop` (prerequisite-gated)
- **M6-04** — Federated Roadmap Propagation via `FederationMutationBroker`
- **M6-05** — Free Android Distribution pipeline (CI-governed APK signing + multi-track delivery)

Shipped milestones M6-01 (`RoadmapAmendmentEngine`) and M6-02 (`ProposalDiffRenderer`) are
covered by this canonical v3.1.0 artifact. Earlier references to `ARCHITECT_SPEC_v3.0.0.md` have
been superseded to this document to keep governance links live and deterministic.
This document remains the canonical source for both inherited and Phase 6 completion gates.

**Constitutional principle governing all Phase 6 work:**
> ADAAD proposes. Humans approve. No mutation to ROADMAP.md, governance policy, or distribution
> pipeline occurs without a human governor sign-off recorded in the evidence ledger.

---

## 1. Constitutional Invariants — Phase 6 Additions

### 1.1 Amendment Proposal Authority Invariant (Non-Negotiable)

```
INVARIANT PHASE6-AUTH-0: authority_level for any RoadmapAmendmentProposal is
hardcoded to "governor-review". No agent, orchestrator, environment variable,
or runtime injection may assign a different value.

Enforcement: RoadmapAmendmentEngine.__init__ sets authority_level as a class
constant. Any runtime attempt to override raises GovernanceViolation immediately.
Replay: authority_level value is included in lineage_chain_hash computation.
```

### 1.2 Amendment Storm Prevention Invariant

```
INVARIANT PHASE6-STORM-0: At most ONE RoadmapAmendmentProposal may exist in
PENDING state at any point in time across any single ADAAD node.

EvolutionLoop MUST check for pending proposals before calling
RoadmapAmendmentEngine.propose(). If a pending proposal exists, the epoch
completes normally but no new proposal is emitted.

Failure mode: PHASE6_AMENDMENT_STORM_BLOCKED (logged, non-fatal)
```

### 1.3 Human Sign-Off Invariant (Non-Delegatable)

```
INVARIANT PHASE6-HUMAN-0: No RoadmapAmendmentProposal may transition to APPROVED
status without a recorded human governor sign-off in the evidence ledger.

Auto-approval paths are constitutionally prohibited.
GovernanceGate.approve_mutation() for amendment-type proposals MUST require
human_signoff_token before acceptance.
```

### 1.4 Federated Amendment Authority Invariant

```
INVARIANT PHASE6-FED-0: A roadmap amendment propagated via FederationMutationBroker
to a destination node is treated as a NEW PROPOSAL by that node's GovernanceGate.
Source approval does NOT bind the destination.
Destination GovernanceGate evaluates the proposal as if it originated locally.
Each participating node requires its own human governor sign-off.
```

---

## 2. M6-03 — EvolutionLoop Integration Specification

### 2.1 Component Identity

| Field | Value |
|---|---|
| Milestone | M6-03 |
| Target PR | `PR-PHASE6-02` |
| Branch | `feat/phase6-m603-evolution-loop-wire` |
| Status | 🔵 proposed — specification active |
| CI Tier | `critical` |
| Depends on | M6-01 (shipped), M6-02 (shipped), v3.0.0 tagged |
| Human sign-off | **REQUIRED** — non-delegatable |
| Blocks | M6-04 (PR-PHASE6-03) |

### 2.2 Purpose

Wire `RoadmapAmendmentEngine.propose()` into the Phase 5 epoch orchestrator
(`runtime/autonomy/loop.py` / `EvolutionRuntime`) so that after every Nth successful
epoch (N configurable, default 10), ArchitectAgent evaluates prerequisite gates and
emits a governed roadmap amendment proposal if all gates pass.

### 2.3 Inputs

| Input | Source | Required |
|---|---|---|
| `epoch_count` | `EpochTelemetry.epoch_count` | Yes |
| `health_score` | `EpochTelemetry.health_score` (rolling last-10 average) | Yes |
| `divergence_count` | `FederatedEvidenceMatrix.divergence_count` | Yes (if federation enabled) |
| `prediction_accuracy` | `WeightAdaptor.prediction_accuracy` | Yes |
| `pending_amendments` | `RoadmapAmendmentEngine.list_pending()` count | Yes |
| `amendment_trigger_interval` | env `ADAAD_ROADMAP_AMENDMENT_TRIGGER_INTERVAL`, default `10` | No |
| `roadmap_content` | Current `ROADMAP.md` SHA-256 hash | Yes |
| `epoch_id` | Current epoch identifier (seeded RNG anchor) | Yes |

### 2.4 Prerequisite Gate Checks (All Must Pass)

All checks are evaluated deterministically in the order listed. Any failing check
halts evaluation and logs the specific gate identifier. No gate result is inferred;
all must be explicitly evaluated.

| Gate ID | Condition | Failure Mode |
|---|---|---|
| `GATE-M603-01` | `epoch_count % amendment_trigger_interval == 0` | `PHASE6_AMENDMENT_NOT_TRIGGERED` (non-fatal, normal) |
| `GATE-M603-02` | `EpochTelemetry.health_score(last_10) >= 0.80` | `PHASE6_HEALTH_GATE_FAIL` |
| `GATE-M603-03` | `FederatedEvidenceMatrix.divergence_count == 0` (if federation enabled) | `PHASE6_FEDERATION_DIVERGENCE_BLOCKS_AMENDMENT` |
| `GATE-M603-04` | `WeightAdaptor.prediction_accuracy > 0.60` | `PHASE6_PREDICTION_ACCURACY_GATE_FAIL` |
| `GATE-M603-05` | `len(RoadmapAmendmentEngine.list_pending()) == 0` | `PHASE6_AMENDMENT_STORM_BLOCKED` |
| `GATE-M603-06` | `amendment_trigger_interval >= 5` (misconfiguration guard) | `PHASE6_TRIGGER_INTERVAL_MISCONFIGURED` |

### 2.5 Pass Conditions

All six gates pass → `RoadmapAmendmentEngine.propose(...)` is called with:
- `rationale`: derived from `EpochTelemetry` summary (minimum 10 words enforced by engine)
- `proposed_milestone_updates`: list of milestone status transitions warranted by telemetry
- `lineage_chain_hash`: SHA-256(`prior_roadmap_hash` + `content_hash`)
- `epoch_id`: current epoch identifier (determinism anchor)

Proposal is appended to evidence ledger via `journal.append_tx("roadmap_amendment_proposed", payload)`.
`EpochResult` extended with `amendment_proposed: bool`, `amendment_id: Optional[str]`.

### 2.6 Fail Conditions

| Failure Mode | Severity | Behavior |
|---|---|---|
| `PHASE6_AMENDMENT_NOT_TRIGGERED` | INFO | Normal epoch continuation; no proposal emitted |
| `PHASE6_HEALTH_GATE_FAIL` | WARN | Log gate result; epoch continues; no proposal |
| `PHASE6_FEDERATION_DIVERGENCE_BLOCKS_AMENDMENT` | WARN | Log divergence count; epoch continues; no proposal |
| `PHASE6_PREDICTION_ACCURACY_GATE_FAIL` | WARN | Log current accuracy; epoch continues; no proposal |
| `PHASE6_AMENDMENT_STORM_BLOCKED` | WARN | Log pending amendment ID; epoch continues; no new proposal |
| `PHASE6_TRIGGER_INTERVAL_MISCONFIGURED` | ERROR | Halt amendment evaluation; raise `GovernanceViolation` |
| `DeterminismViolation` | BLOCKING | Proposal immediately halted; no ledger write; replay hash mismatch logged |
| `GovernanceViolation` | BLOCKING | Proposal rejected at source; logged to evidence ledger |

**Fail-closed rule:** Any unclassified exception during amendment evaluation halts the
amendment path only. The epoch continues normally. The exception is logged as
`PHASE6_AMENDMENT_EVAL_ERROR` with full traceback in the evidence ledger.

### 2.7 Acceptance Criteria

All criteria must be verifiable by deterministic replay:

1. `EpochResult.amendment_proposed == True` only when all 6 gates pass
2. `EpochResult.amendment_id` is set and matches the proposal's `proposal_id` in the ledger
3. Amendment evaluation failure (any gate) does NOT abort the epoch
4. Gate results are logged to evidence ledger for every trigger evaluation (pass or fail)
5. `amendment_trigger_interval` is configurable via environment without code change
6. At most 1 proposal emitted per trigger (storm invariant enforced)
7. Identical epoch inputs produce identical gate verdicts (determinism CI job)

### 2.8 Dependencies

| Component | Direction | Note |
|---|---|---|
| `runtime/autonomy/loop.py` | Modified | Insert gate evaluation at post-epoch-N checkpoint |
| `runtime/autonomy/roadmap_amendment_engine.py` | Called | Proposal emitter; M6-01 contract |
| `runtime/autonomy/epoch_telemetry.py` | Read | Health score source |
| `runtime/autonomy/weight_adaptor.py` | Read | Prediction accuracy source |
| `runtime/governance/federation/federated_evidence_matrix.py` | Read (conditional) | Divergence count; skip if `ADAAD_FEDERATION_ENABLED != true` |
| `runtime/governance/governance_gate.py` | Called | Constitutional gate for the amendment proposal itself |
| `runtime/ledger/cryovant_journal.py` | Write | Gate results + proposal ledger entries |

### 2.9 Notes for Other Agents

**MutationAgent:** The amendment proposal itself is a mutation of type `roadmap_amendment`.
GovernanceGate evaluates it identically to code mutations. The `no_banned_tokens` rule
applies to the proposal rationale text. The `signature_required` rule applies to the
proposal payload.

**IntegrationAgent:** `EpochResult` gains two new optional fields (`amendment_proposed: bool`,
`amendment_id: Optional[str]`). All existing consumers of `EpochResult` must handle these
fields as optional with safe defaults (`False`, `None`). No breaking change to existing
deserialization paths.

**AnalysisAgent:** Gate result events (`PHASE6_HEALTH_GATE_FAIL`, etc.) must be registered
in `docs/governance/ledger_event_contract.md` before this PR merges. Six new event types.

---

## 3. M6-04 — Federated Roadmap Propagation Specification

### 3.1 Component Identity

| Field | Value |
|---|---|
| Milestone | M6-04 |
| Target PR | `PR-PHASE6-03` |
| Branch | `feat/phase6-m604-federated-amendment` |
| Status | 🔵 proposed — specification active |
| CI Tier | `critical` |
| Depends on | M6-03 (PR-PHASE6-02 merged), `ADAAD_FEDERATION_ENABLED=true` runtime |
| Human sign-off | **REQUIRED** per node — non-delegatable |
| Blocks | v3.1.0 tag |

### 3.2 Purpose

When a federation node's `EvolutionLoop` (M6-03) generates a `RoadmapAmendmentProposal`,
`FederationMutationBroker` propagates it to all registered peer nodes for independent
governance review. Each peer's `GovernanceGate` evaluates the proposal autonomously.
No peer is bound by another peer's approval decision.

### 3.3 Inputs

| Input | Source | Required |
|---|---|---|
| `amendment_proposal` | `RoadmapAmendmentProposal` from source node M6-03 | Yes |
| `federation_origin` | Source node identifier (included in proposal lineage) | Yes |
| `hmac_key` | `ADAAD_FEDERATION_HMAC_KEY` (must pass `key_registry.py` validation) | Yes |
| `peer_node_list` | `FederationMutationBroker.registered_peers()` | Yes |
| `source_evidence_bundle_hash` | SHA-256 of source node evidence bundle at proposal time | Yes |

### 3.4 Checks

Evaluated in order. Any failure halts propagation fail-closed.

| Gate ID | Condition | Failure Mode |
|---|---|---|
| `GATE-M604-01` | HMAC key valid (length >= minimum per `key_registry.py`) | `FederationKeyError` — halt at boot |
| `GATE-M604-02` | `FederatedEvidenceMatrix.divergence_count == 0` across ALL nodes | `PHASE6_FEDERATED_AMENDMENT_DIVERGENCE_BLOCKED` |
| `GATE-M604-03` | `amendment_proposal.authority_level == "governor-review"` | `PHASE6_FEDERATED_AUTHORITY_VIOLATION` |
| `GATE-M604-04` | `amendment_proposal.lineage_chain_hash` is cryptographically valid | `PHASE6_FEDERATED_LINEAGE_INVALID` |
| `GATE-M604-05` | No pending amendments on ANY peer node | `PHASE6_FEDERATED_AMENDMENT_STORM_BLOCKED` |
| `GATE-M604-06` | `proposal.verify_replay()` returns determinism match | `DeterminismViolation` |

### 3.5 Pass Conditions

All six gates pass → `FederationMutationBroker.propagate_amendment(proposal)` is called:

1. Proposal is transmitted to each peer node via governed transport
2. Each peer receives proposal with `federation_origin` field set to source node identifier
3. Each peer's `GovernanceGate` evaluates independently (Invariant PHASE6-FED-0)
4. Each peer's evidence ledger records the propagated proposal as a new intake event
5. `federated_roadmap_evidence` section added to each peer's evidence bundle before any merge

### 3.6 Fail Conditions

| Failure Mode | Severity | Behavior |
|---|---|---|
| `FederationKeyError` | BLOCKING (boot) | Node does not start; entire federation halted at boot |
| `PHASE6_FEDERATED_AMENDMENT_DIVERGENCE_BLOCKED` | BLOCKING | Propagation halted; source amendment remains PENDING |
| `PHASE6_FEDERATED_AUTHORITY_VIOLATION` | BLOCKING | Proposal rejected; logged to source + destination ledgers |
| `PHASE6_FEDERATED_LINEAGE_INVALID` | BLOCKING | Proposal rejected; `LINEAGE_CHAIN_BROKEN` error emitted |
| `PHASE6_FEDERATED_AMENDMENT_STORM_BLOCKED` | WARN | Propagation deferred; retried next epoch |
| `DeterminismViolation` | BLOCKING | Propagation halted; replay hash divergence logged |

**Partial propagation rule:** If propagation to peer A succeeds but peer B fails, peer A's
intake is rolled back (proposal status reverts to `PENDING` at source). All-or-nothing
propagation is required to prevent constitutional asymmetry across nodes.

### 3.7 Acceptance Criteria

1. Amendment propagation leaves a `federation_origin` field in lineage chain on all peer nodes
2. Any single node may reject without blocking its own local roadmap evaluation
3. Evidence bundle includes `federated_roadmap_evidence` section before any merge
4. Partial propagation roll-back is deterministic and replay-verifiable
5. `divergence_count == 0` across ALL nodes is enforced before any propagation attempt
6. Same HMAC key rotation runbook (`docs/runbooks/hmac_key_rotation.md`) applies without modification

### 3.8 Dependencies

| Component | Direction | Note |
|---|---|---|
| `runtime/governance/federation/mutation_broker.py` | Modified | Add `propagate_amendment()` method |
| `runtime/governance/federation/federated_evidence_matrix.py` | Read | Pre-propagation divergence gate |
| `runtime/autonomy/roadmap_amendment_engine.py` | Read | Source proposal contract |
| `runtime/governance/governance_gate.py` | Called (per peer) | Destination-side constitutional gate |
| `runtime/governance/federation/key_registry.py` | Validated | HMAC key check; existing contract unchanged |
| `runtime/ledger/cryovant_journal.py` | Write (all nodes) | `federated_amendment_propagated` event |

### 3.9 Notes for Other Agents

**MutationAgent:** `propagate_amendment()` is a new method on `FederationMutationBroker`.
It must not modify the existing `propagate()` method signature or behavior. Additive only.
The `federation_dual_gate` constitutional rule (Phase 5, BLOCKING) applies to amendment
proposals propagated via this path without exception.

**IntegrationAgent:** A new ledger event type `federated_amendment_propagated` must be
registered in `docs/governance/ledger_event_contract.md` before this PR merges. Schema:
`{proposal_id, source_node, destination_nodes[], propagation_timestamp, evidence_bundle_hash}`.

**AnalysisAgent:** Cross-node divergence must be evaluated and logged before every
propagation attempt. If `FederatedEvidenceMatrix` is not available (non-federated node),
this milestone is a no-op and must not error.

---

## 4. M6-05 — Free Android Distribution Governance Specification

### 4.1 Component Identity

| Field | Value |
|---|---|
| Milestone | M6-05 |
| Target PR | `PR-PHASE6-04` |
| Branch | `feat/phase6-m605-android-distribution-complete` |
| Status | 🟡 active — CI partially shipped; F-Droid MR pending |
| CI Tier | `standard` |
| Depends on | `android-free-release.yml` shipped (v3.1.0-dev) |
| Human sign-off | Required for F-Droid MR submission only |
| Blocks | v3.1.0 tag |

### 4.2 Governance Invariant

```
INVARIANT PHASE6-APK-0: Every distributed APK must be produced by the
android-free-release.yml CI workflow and must pass the full governance gate
(constitutional lint + Android lint) before signing. No APK may be distributed
that has not passed the governance gate.

APK signing key must be stored in GitHub Secrets only; never in repository.
SHA-256 integrity hash must accompany every release asset.
```

### 4.3 Distribution Acceptance Gate

Before v3.1.0 tag: all four distribution tracks must satisfy their respective evidence criteria:

| Track | Acceptance Criterion | Evidence Artifact |
|---|---|---|
| Track 1 (GitHub Releases + Obtainium) | `free-v*` tag triggers pipeline in < 15 min; SHA-256 hash present | CI run evidence in release notes |
| Track 2A (F-Droid Official) | `fdroid lint` passes without errors; MR submitted | F-Droid MR URL in CHANGELOG |
| Track 2B (Self-hosted F-Droid) | GitHub Pages deployment green; repo.xml valid | CI deployment log |
| Track 3 (PWA) | Manifest has `standalone` display mode; installable on Android Chrome | Lighthouse CI score |

### 4.4 Failure Modes

| Failure Mode | Severity | Behavior |
|---|---|---|
| `APK_GOVERNANCE_GATE_FAIL` | BLOCKING | CI rejects build; no release asset produced |
| `APK_SIGNING_KEY_ABSENT` | BLOCKING | Pipeline halts; `distribution_blocked` logged |
| `FDROID_LINT_FAIL` | BLOCKING (for 2A track) | MR cannot be submitted; track 2A blocked |
| `PWA_MANIFEST_INVALID` | WARN | Track 3 degraded; other tracks unaffected |

### 4.5 Notes for Other Agents

**IntegrationAgent:** No changes to mutation pipeline required. Distribution pipeline is
orthogonal to mutation governance. The `android-free-release.yml` workflow is Tier 1 (docs/CI).
Changes to that workflow require only standard PR review, not Tier 0 human sign-off.

---

## 5. PR Procession — Phase 6 Completion

### 5.1 Sequence

```
[v3.0.0 tagged — DONE]
       ↓
[M6-01 + M6-02 shipped in v3.1.0-dev — DONE]
       ↓
PR-PHASE6-02  →  PR-PHASE6-03  →  PR-PHASE6-04  →  v3.1.0 tag
 (M6-03)          (M6-04)          (M6-05 close)
```

### 5.2 PR Summary Table (Phase 6 Completion)

| PR | Milestone | Branch | CI Tier | Depends On | Human Sign-off |
|---|---|---|---|---|---|
| `PR-PHASE6-02` | M6-03 EvolutionLoop wire | `feat/phase6-m603-evolution-loop-wire` | critical | M6-01, M6-02 shipped | **REQUIRED** |
| `PR-PHASE6-03` | M6-04 Federated propagation | `feat/phase6-m604-federated-amendment` | critical | PR-PHASE6-02 merged | **REQUIRED** per node |
| `PR-PHASE6-04` | M6-05 Distribution complete | `feat/phase6-m605-android-distribution-complete` | standard | `android-free-release.yml` passing | Required (F-Droid MR) |
| **v3.1.0 tag** | Phase 6 GA | — | — | All above merged | **REQUIRED** |

### 5.3 Governance Invariants for All Phase 6 PRs

- Every new Python file carries `SPDX-License-Identifier: Apache-2.0`
- Every new ledger event type registered in `docs/governance/ledger_event_contract.md` before merge
- No PR may weaken or remove existing constitutional blocking rules
- `amendment_trigger_interval` environment variable must appear in `docs/ENVIRONMENT_VARIABLES.md`
- All new failure modes must be registered in `tools/error_dictionary.py`
- Determinism lint must pass: `python tools/lint_determinism.py` exits zero
- Import lint must pass: `python tools/lint_import_paths.py` exits zero

---

## 6. Security Invariants — Phase 6 Additions

These invariants extend `docs/governance/SECURITY_INVARIANTS_MATRIX.md`:

| ID | Invariant | Enforcement |
|---|---|---|
| `SEC-P6-01` | `authority_level` for amendment proposals is immutable after construction | `RoadmapAmendmentEngine` constructor; `GovernanceViolation` on deviation |
| `SEC-P6-02` | Amendment rationale text passes `no_banned_tokens` constitutional rule | `GovernanceGate` evaluation; blocked if eval/exec/exec-like tokens present |
| `SEC-P6-03` | Federated amendment HMAC validation uses same key registry as Phase 5 | `key_registry.py`; unchanged contract |
| `SEC-P6-04` | No amendment may modify constitutional rule severity downward | `CONSTITUTION.md` severity escalation framework; downgrade attempts ignored |
| `SEC-P6-05` | APK signing key never committed to repository | CI secret scan workflow; `secret_scan.yml` enforced |

---

## 7. Determinism Contract — Phase 6 Extensions

All Phase 6 additions must satisfy the determinism contract defined in
`docs/governance/DETERMINISM_CONTRACT_SPEC.md`. Specific extensions:

1. **Gate evaluation is deterministic:** All six M6-03 and six M6-04 gate checks produce
   identical results given identical inputs. Telemetry values are snapshotted at gate
   evaluation time and stored in the ledger entry for replay.

2. **Proposal content hash is deterministic:** `lineage_chain_hash = SHA-256(prior_roadmap_hash + content_hash)`
   is computed from immutable inputs. Any source of non-determinism in proposal content
   raises `DeterminismViolation` before the proposal is written to the ledger.

3. **Amendment trigger interval is config-bound:** `amendment_trigger_interval` is read
   from environment at epoch start and is constant for the duration of that epoch. It
   cannot be modified mid-epoch.

4. **Federated propagation is all-or-nothing:** Partial propagation states are never
   persisted. The ledger either records successful propagation to all peers or records
   a rollback event. Intermediate states are transient only.

---

## 8. Evidence Requirements — v3.1.0 Release Gate

Before v3.1.0 may be tagged, the following evidence artifacts must exist and be
linked in the release notes:

| Artifact | Source | Required For |
|---|---|---|
| M6-03 gate evaluation test coverage (≥ 10 test cases) | `tests/autonomy/test_evolution_loop_amendment.py` | PR-PHASE6-02 |
| M6-04 federated propagation test coverage (≥ 8 test cases) | `tests/governance/federation/test_federated_amendment.py` | PR-PHASE6-03 |
| Amendment storm invariant test | Included in above | Both PRs |
| Determinism CI job passing for M6-03 gate logic | `.github/workflows/ci.yml` | PR-PHASE6-02 |
| All 6 new ledger event types registered | `docs/governance/ledger_event_contract.md` | PR-PHASE6-02 |
| `amendment_trigger_interval` in environment docs | `docs/ENVIRONMENT_VARIABLES.md` | PR-PHASE6-02 |
| All new failure modes in error dictionary | `tools/error_dictionary.py` | Both PRs |
| F-Droid MR submitted (URL in CHANGELOG) | F-Droid repo | PR-PHASE6-04 |
| v3.1.0 release evidence matrix complete | `docs/comms/claims_evidence_matrix.md` | v3.1.0 tag gate |

---

## 9. What Will Not Be Built (Phase 6)

Constitutional clarity requires explicit exclusions:

- **No auto-merge path for roadmap amendments** — `GovernanceGate` cannot approve
  roadmap amendments without human sign-off. This cannot be delegated or bypassed.
- **No cross-node auto-approval** — Source node approval of an amendment NEVER
  binds destination nodes (Invariant PHASE6-FED-0).
- **No retroactive amendment rationale** — Rationale must be present at proposal time.
  Post-hoc rationale amendments are constitutionally prohibited.
- **No amendment to constitutional blocking rules via roadmap mutation** — ROADMAP.md
  mutations cannot modify `CONSTITUTION.md`. Constitutional changes remain a separate
  governance pathway (Tier 0, human review required).

---

## 10. Amendment History

| Version | Date | Change |
|---|---|---|
| v3.1.0 | 2026-03-07 | Initial Phase 6 completion specification (M6-03, M6-04, M6-05) |

---

*This document is governed by `docs/CONSTITUTION.md`. Any amendment to this specification
requires ArchitectAgent review and a CHANGELOG entry. All rules are authoritative for
MutationAgent, IntegrationAgent, AnalysisAgent, and all LLM proposal agents operating
within ADAAD v3.1.0.*
