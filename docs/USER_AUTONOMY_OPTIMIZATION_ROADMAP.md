# ADAAD User Autonomy Optimization Roadmap

**Document:** `USER_AUTONOMY_OPTIMIZATION_ROADMAP.md`
**Status:** ACTIVE
**Version:** v9.79.0
**Date:** 2026-04-21
**Author:** DEVADAAD (Track A) · Ratification: HUMAN-0
**Scope:** Phases 147–160 candidate planning · UX + Autonomy surface

---

## Purpose

This roadmap defines the ordered delivery plan for transforming ADAAD's autonomous execution capabilities into a user-accessible, feedback-rich, and operationally transparent system. All items are scoped to Track A unless otherwise noted. Each item maps to a candidate INNOV identifier, a primary file surface, governing invariants, and acceptance criteria.

Infrastructure prerequisites are already shipped: RAGS (`RAGS-CSS-0`, `RAGS-DISPATCH-0`), DORK intelligence stack (DPM/DQR, INNOV-51/52), GovernanceGate, Lineage Ledger v2, Deterministic Replay (`REPLAY-0`).

---

## Mental Model: Two-Tier Autonomy

Before each capability item, the user contract must be clear:

| Tier | Meaning | Examples |
|---|---|---|
| **Tier A — Autonomous** | DEVADAAD executes without approval | Code mutations inside scoped modules, test execution, CHANGELOG generation, version bumps, ledger writes |
| **Tier B — Human-0 Gate** | Requires HUMAN-0 attestation | Phase ratification, GPG tag ceremony, PyPI promotion, PR merge, constitutional amendments |

The roadmap below systematically widens Tier A coverage while hardening the Tier B handoff UX. No item in this roadmap reduces Tier B coverage — it only makes Tier B faster and less error-prone to execute.

---

## Roadmap Items

---

### UXO-1 — Intent Expression Schema
**Candidate:** INNOV-53
**Target Phase:** 147
**Priority:** P0 — blocks all downstream UX items

#### Problem
Users and operators have no structured way to express intent to ADAAD without writing code or governance artifacts. RAGS + DORK can route and retrieve; there is no schema binding a natural-language request to a governed CEL-safe operation.

#### Deliverables
- `dorkllm/intent_schema.py` — typed intent manifest: `IntentRecord(action, scope_path, dry_run, confidence_floor, requestor_role)`
- `dorkllm/ask_dispatcher.py` extended with a `preview_intent()` method returning a `DiffPreview` before any mutation fires
- `whaledic.html` — intent entry panel with dry-run toggle and confirmation handshake
- 30 acceptance tests covering: valid intents, scope boundary rejection, dry-run accuracy, confidence-floor enforcement

#### Governing Invariants
- `INTENT-SCHEMA-0`: every autonomous action originating from user input must carry a validated `IntentRecord`
- `INTENT-DRYRUN-0`: `dry_run=True` must never produce a ledger write or file mutation
- Existing: `RAGS-DISPATCH-0`, `GOV-SOLE-0`

#### Acceptance Criteria
1. User submits plain-language request via Whale.Dic intent panel
2. System returns structured diff preview with scope, confidence, and proposed changes before execution
3. Dry-run path produces zero ledger writes (verified by ledger hash comparison pre/post)
4. Out-of-scope requests return `SCOPE_REJECTION` with explanation, not a silent no-op

---

### UXO-2 — Live Execution Feed
**Candidate:** INNOV-54
**Target Phase:** 148
**Priority:** P0 — closes INNOV-51 Milestone B

#### Problem
The Constitutional Evolution Loop (CEL) executes across 14 steps with no user-visible progress surface. Autonomy feels opaque. Users cannot distinguish "running" from "stuck" from "pending human gate."

#### Deliverables
- `whaledic.html` — RAGS grounding audit dashboard panel (Milestone B) with CEL step tracker, active seed display, invariant check stream, and estimated next action
- `runtime/mcp/server.py` — new SSE endpoint `/events/cel-feed` emitting structured CEL step events
- Event schema: `CELStepEvent(phase, step_index, step_name, seed_id, status, timestamp)`
- 30 acceptance tests covering: event ordering, stale feed detection, reconnect behavior, no-mutation side effects from SSE subscription

#### Governing Invariants
- `CEL-FEED-0`: CEL step events are read-only — subscribing to the feed never influences execution path
- `CEL-FEED-COMPLETE-0`: every CEL cycle must emit a terminal `COMPLETE` or `BLOCKED` event; no silent exits
- Existing: `CEL-ORDER-0`, `AUDIT-0`

#### Acceptance Criteria
1. Whale.Dic panel displays current CEL step in real time during an active phase execution
2. Feed correctly differentiates `RUNNING`, `AWAITING_HUMAN_GATE`, and `BLOCKED` states
3. Panel renders within 2s of CEL step transition
4. SSE subscription produces zero entries in lineage ledger

---

### UXO-3 — Human-0 Approval UX
**Candidate:** INNOV-55
**Target Phase:** 149
**Priority:** P1 — GA readiness dependency · Track B surface

#### Problem
Track B operations (PR creation, GPG tag, phase ratification) require Dustin to run sequential CLI commands from a runbook delivered per-session. The current path has no queue, no notification, and no single-command execution wrapper. Friction increases risk of sequencing errors.

#### Deliverables
- `.github/workflows/human0-approval-request.yml` — GitHub Actions workflow triggered when DEVADAAD opens a PR; assembles attestation payload (governance hash, diff summary, invariant report) and posts as PR comment + optional webhook
- `scripts/track_b_execute.sh` — single-command Track B runner: accepts PR number + phase tag; runs `gh pr create` scaffold check, prompts for GPG passphrase, executes `git tag -s`, pushes tag
- Attestation payload schema: `AttestationRequest(phase, version, sha, invariant_count, governance_hash, isodate)`
- 30 acceptance tests covering: payload completeness, hash integrity, workflow idempotency, rejection path

#### Governing Invariants
- `HUMAN0-NOTIFY-0`: every phase reaching merge-ready state must emit an `AttestationRequest` artifact before any Track B command is issued
- `HUMAN0-NOCREEP-0`: this workflow must never execute any GPG operation autonomously — signing authority remains exclusively on ADAADell
- Existing: `GOV-SOLE-0`, `AUDIT-0`, `REPLAY-0`

#### Acceptance Criteria
1. DEVADAAD PR triggers workflow; Dustin receives structured comment containing governance hash and single runbook command
2. `track_b_execute.sh` runs end-to-end from one command with no additional lookups required
3. Workflow is idempotent — re-running on same PR produces identical payload, no duplicate events
4. GPG signing step is unreachable from any workflow action (Track B only, ADAADell only)

---

### UXO-4 — Post-Phase Narrative Summaries
**Candidate:** INNOV-56
**Target Phase:** 150
**Priority:** P1 — leverages existing CHANGELOG scaffold

#### Problem
ADAAD generates CHANGELOG entries per phase but these are engineer-formatted. There is no plain-language summary of what changed, why, which invariants were exercised, what fitness delta was recorded, and what happens next. Stakeholders and future contributors cannot quickly grasp phase outcomes.

#### Deliverables
- `scripts/generate_phase_narrative.py` — RAGS-grounded script that reads phase artifacts and emits a structured `PhaseNarrative` block: summary, invariants fired, tests passed, fitness delta, next-phase preview
- `CHANGELOG.md` — `PhaseNarrative` block appended to each phase section at merge time
- `whaledic.html` — "Phase Summary" panel in DORK console rendering latest narrative
- 30 acceptance tests covering: narrative completeness, RAGS retrieval accuracy, CHANGELOG injection idempotency, rendering in Whale.Dic

#### Governing Invariants
- `NARRATIVE-0`: every merged phase must have a `PhaseNarrative` block in CHANGELOG before ratification
- `NARRATIVE-GROUNDED-0`: all claims in the narrative must be traceable to a ledger entry or governance artifact — no hallucinated summaries
- Existing: `AUDIT-0`, `RAGS-CSS-0`

#### Acceptance Criteria
1. Phase merge triggers `generate_phase_narrative.py`; output is appended to CHANGELOG within the phase section
2. Every claim in the narrative block references a ledger entry hash or artifact path
3. Whale.Dic DORK console renders latest narrative within 3s of page load
4. Narrative generation produces zero file mutations outside `CHANGELOG.md`

---

### UXO-5 — Governed Rollback Surface
**Candidate:** INNOV-57
**Target Phase:** 151
**Priority:** P2

#### Problem
Deterministic replay (`REPLAY-0`) exists at the infrastructure level but is not user-accessible. A user who wants to revert a phase must know git internals. There is no safety-gated `rollback` operation that uses the lineage ledger as the source of truth.

#### Deliverables
- `tools/adaad_rollback.py` — CLI tool: `adaad rollback --to-phase N` reconstructs state from lineage ledger, runs acceptance test suite against reconstructed state, presents diff and invariant report before committing
- GovernanceGate preflight extension: rollback target must pass `ROLLBACK-PREFLIGHT-0` check before any file write
- 30 acceptance tests covering: valid rollback path, invariant-failing rollback rejection, diff accuracy, ledger consistency post-rollback

#### Governing Invariants
- `ROLLBACK-PREFLIGHT-0`: rollback is rejected unless the target phase state passes all currently active hard-class invariants
- `ROLLBACK-LEDGER-0`: rollback writes a `ROLLBACK_EVENT` entry to the lineage ledger with source phase, target phase, and operator identity
- Existing: `REPLAY-0`, `AUDIT-0`, `GOV-SOLE-0`

#### Acceptance Criteria
1. `adaad rollback --to-phase 144` reconstructs state, runs tests, and presents diff + invariant report before writing anything
2. Rollback to a phase that would violate a current invariant is rejected with a clear invariant reference
3. Successful rollback produces a `ROLLBACK_EVENT` ledger entry
4. Rollback is atomic — partial state writes are impossible (all-or-nothing)

---

### UXO-6 — Autonomy Scope Controls
**Candidate:** INNOV-58
**Target Phase:** 152
**Priority:** P2

#### Problem
Autonomy scope is binary at the architectural level (Track A / Track B). Users cannot dynamically scope autonomous evolution to a specific module or file tree without editing the constitution.

#### Deliverables
- `governance/autonomy_scope.json` — operator-editable scope manifest: per-path autonomy level (`FULL`, `REVIEW_REQUIRED`, `LOCKED`)
- `GovernanceGate` integration: pre-mutation path check against `autonomy_scope.json`
- `whaledic.html` — scope control panel: toggle autonomy level per module with live preview of affected paths
- 30 acceptance tests covering: scope enforcement, locked-path rejection, scope change audit trail, UI toggle accuracy

#### Governing Invariants
- `SCOPE-MANIFEST-0`: every mutation must be validated against `autonomy_scope.json` before GovernanceGate evaluation
- `SCOPE-AUDIT-0`: every scope manifest change is a ledger event with operator identity and timestamp
- `SCOPE-LOCKED-GOVERNANCE-0`: `governance/` is permanently `LOCKED` — this is not operator-configurable
- Existing: `GOV-SOLE-0`, `AUDIT-0`

#### Acceptance Criteria
1. Setting `dorkllm/` to `REVIEW_REQUIRED` causes all mutations in that path to surface an approval request before execution
2. Attempting to set `governance/` to any scope other than `LOCKED` is rejected at the manifest validation layer
3. Every scope change produces a ledger entry
4. Scope panel in Whale.Dic reflects current `autonomy_scope.json` state within 1s of load

---

### UXO-7 — Failure Mode Transparency
**Candidate:** INNOV-59
**Target Phase:** 153
**Priority:** P2

#### Problem
When ADAAD fails — invariant fires, test gate blocks, replay diverges — the error surface is CI logs and pytest output. Non-engineers see nothing actionable. There is no classified, human-readable failure taxonomy exposed in the UI.

#### Deliverables
- `runtime/failure_taxonomy.py` — failure event classifier: `INVARIANT_FIRE`, `TEST_GATE_BLOCK`, `REPLAY_DIVERGE`, `SCOPE_REJECTION`, `CEL_TIMEOUT`, each with schema, human-readable cause, and remediation suggestion
- `whaledic.html` — Failure Event panel in Aponi Dashboard: classified events, cause display, one-click remediation command copy
- GovernanceGate exception hook: all gate failures emit a classified `FailureEvent` to the ledger and the panel
- 30 acceptance tests covering: event classification accuracy, ledger write on failure, UI rendering, remediation suggestion correctness

#### Governing Invariants
- `FAILURE-CLASSIFIED-0`: every GovernanceGate rejection must produce a classified `FailureEvent` with cause and remediation
- `FAILURE-LEDGER-0`: `FailureEvent` entries are immutable ledger writes — no failure is silently swallowed
- Existing: `GOV-SOLE-0`, `AUDIT-0`

#### Acceptance Criteria
1. Invariant fire during phase execution produces a `FailureEvent` visible in Whale.Dic within 2s
2. Every failure event includes: classification, invariant ID or test name, cause string, and remediation suggestion
3. No failure produces a silent exit — all paths emit a terminal `FailureEvent` or `SUCCESS` event
4. Failure events in the ledger are retrievable by phase, date, and classification

---

### UXO-8 — Auto-Generated Capability Map
**Candidate:** INNOV-60
**Target Phase:** 154
**Priority:** P3 — docs + onboarding + marketing surface

#### Problem
The user contract for ADAAD autonomy is not machine-readable or auto-maintained. The Tier A / Tier B split is architectural knowledge, not a living artifact. New contributors, collaborators, and potential customers cannot quickly understand what ADAAD does autonomously versus what requires human approval.

#### Deliverables
- `scripts/generate_capability_map.py` — reads GovernanceGate config, `autonomy_scope.json`, and invariant registry; emits `docs/CAPABILITY_MAP.md` with auto-generated Tier A / Tier B tables
- `docs/CAPABILITY_MAP.md` — generated, not hand-maintained; updated on every phase merge
- `whaledic.html` — "Capability Map" tab in DORK console; same content, rendered interactively
- README section linking to `CAPABILITY_MAP.md`
- 30 acceptance tests covering: generation accuracy, Tier A/B correctness, staleness detection, README link validity

#### Governing Invariants
- `CAPMAP-GENERATED-0`: `CAPABILITY_MAP.md` must be auto-generated — manual edits are rejected by pre-commit hook
- `CAPMAP-SYNC-0`: capability map must be regenerated on every phase merge; stale map blocks ratification
- Existing: `AUDIT-0`, `GOV-SOLE-0`

#### Acceptance Criteria
1. `generate_capability_map.py` produces an accurate Tier A / Tier B table derived solely from governance config and invariant registry
2. Manual edit to `CAPABILITY_MAP.md` is rejected by pre-commit hook with a clear message
3. Phase merge without regenerating the capability map fails the ratification gate
4. Whale.Dic renders the capability map with module-level filtering

---

## Phase Mapping Summary

| Phase | INNOV | Item | Priority | Track | Key Deliverable |
|---|---|---|---|---|---|
| 147 | INNOV-53 | Intent Expression Schema | P0 | A | `intent_schema.py` + Whale.Dic intent panel |
| 148 | INNOV-54 | Live Execution Feed | P0 | A | CEL SSE feed + Whale.Dic step tracker |
| 149 | INNOV-55 | Human-0 Approval UX | P1 | A+B | GH Actions attestation + `track_b_execute.sh` |
| 150 | INNOV-56 | Post-Phase Narratives | P1 | A | `generate_phase_narrative.py` + CHANGELOG block |
| 151 | INNOV-57 | Governed Rollback | P2 | A | `adaad_rollback.py` + GovernanceGate preflight |
| 152 | INNOV-58 | Autonomy Scope Controls | P2 | A | `autonomy_scope.json` + Whale.Dic scope panel |
| 153 | INNOV-59 | Failure Mode Transparency | P2 | A | `failure_taxonomy.py` + Aponi failure panel |
| 154 | INNOV-60 | Auto-Generated Capability Map | P3 | A | `generate_capability_map.py` + `CAPABILITY_MAP.md` |

---

## Cross-Cutting Constraints

All items in this roadmap are bound by the following non-negotiable constraints:

1. **No autonomy creep** — no UXO item may expand the set of operations ADAAD performs without a corresponding invariant registration and GovernanceGate binding
2. **No UX bypass** — UI surfaces are observer/operator only; they carry no mutation authority
3. **Four-surface version sync** — every phase increment updates `VERSION`, `pyproject.toml`, `.adaad_agent_state.json`, and `governance/report_version.json` in lockstep
4. **30-test floor** — each INNOV phase delivers a minimum of 30 acceptance tests
5. **HUMAN-0 is permanent** — GPG signing, GA promotion, constitutional amendments remain non-delegable regardless of UX improvements delivered here
6. **Track B wrapper ≠ Track B bypass** — UXO-3 (`track_b_execute.sh`) wraps Track B ergonomics; it does not execute signing autonomously

---

## Relationship to Existing Docs

| Document | Relationship |
|---|---|
| `UX_ENHANCEMENT_PLAN.md` | Predecessor — delivered CLI, dashboard, onboarding scaffold. This roadmap extends from that baseline. |
| `ADAAD_AUTONOMY_ENHANCEMENT_PLAN.md` | Complementary — covers autonomy engine internals. This roadmap covers the user-facing surface. |
| `AUTONOMY_FEATURE_SCHEMA.md` | Consumed by UXO-1 (intent schema extends this) |
| `GOVERNANCE_ENFORCEMENT.md` | Governs all GovernanceGate extensions in UXO-3, UXO-5, UXO-6, UXO-7 |
| `ADAAD_HORIZON_FORECAST_2026.md` | Horizon alignment: UXO items 1–4 correspond to Horizon phases 147–150 |

---

*Generated by DEVADAAD · v9.79.0 · 2026-04-21 · Track A*
*Ratification pending HUMAN-0 attestation*
