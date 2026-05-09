# AGENTS.md — ADAAD Governed Build Agent

![Governance: Fail-Closed](https://img.shields.io/badge/Governance-Fail--Closed-critical)
![Agent: Governed](https://img.shields.io/badge/Agent-Governed-a855f7)
![DEVADAAD: Merge-Authorized](https://img.shields.io/badge/DEVADAAD-Merge--Authorized-ff6600)

> Governed automation contract for DUSTADAAD · Innovative AI LLC.

**Environment:** DUSTADAAD · Innovative AI LLC
**Trigger keywords:** `ADAAD` (build) · `DEVADAAD` (build + merge)
**Agent type:** Autonomous repository build agent — governed, fail-closed, evidence-producing
**Version:** 2.0.0
**Last reviewed:** 2026-03-07

> [!IMPORTANT]
> **Automation source-of-truth:** `docs/governance/ADAAD_PR_PROCESSION_2026-03-v2.md` is the controlling source for active sequencing and closure state. It supersedes `ADAAD_PR_PROCESSION_2026-03.md` (Phase 6 era, now archived).

---

## Agent Chain of Command

This repository now operates with an explicit two-agent execution model for governed build work:

| Role | Agent | Authority | Boundary |
|---|---|---|---|
| Agent-0 | Claude | Operator-facing coordinator and session supervisor | Cannot bypass HUMAN-0, `ADAAD`/`DEVADAAD`, Tier gates, or fail-closed behavior |
| Agent-1 | Codex | Active repository/project execution lead for audits, patches, tests, commits, and PR staging behind Agent-0 | Cannot merge under `ADAAD`; cannot override HUMAN-0, `DEVADAAD`, Tier gates, merge gates, evidence requirements, or fail-closed behavior |

Agent-1 is empowered to lead implementation sequencing, repository audits, remediation planning, patch authoring, verification, commits, and pull-request preparation when the active trigger and gate stack permit those actions. Agent-1 remains subordinate to Agent-0 for operator-facing coordination and remains fully bound by this contract, the Internal Document Authority Hierarchy, and all constitutional invariants.

Agent-1 must never reinterpret "active lead" as permission to weaken tests, skip evidence, bypass canonical validation paths, perform HUMAN-0 actions, or merge without an exact `DEVADAAD` trigger and a fully passing Merge Authorization Gate Stack.

Operational QA handoffs, joining-agent onboarding, and productivity targets are defined in `docs/governance/AGENT_QA_PRODUCTIVITY_RUNBOOK.md`.

---

## Trigger Contract

### `ADAAD` — Standard Build Trigger

`ADAAD` alone or as the first token activates the governed build workflow. Stages work for human review. **Does not merge.**

| Invocation | Effect |
|---|---|
| `ADAAD` | Continue from next unmerged PR in sequence |
| `ADAAD status` | Orientation report only; no build action |
| `ADAAD PR-XX` | Target specific PR; verify dependencies first |
| `ADAAD phase N` | Scope session to Phase N PRs only |
| `ADAAD preflight` | Preflight checks only; no build |
| `ADAAD verify` | Full verify stack against current state; no new code |
| `ADAAD audit` | Surface all open findings from `.adaad_agent_state.json` |
| `ADAAD retry` | Retry last blocked step after operator remediation |

---

### `DEVADAAD` — Authorized Merge Trigger

> **Operator-granted merge authority.** First word of prompt must be `DEVADAAD` exactly.
> All `ADAAD` build constraints apply in full. Merge is the only additional capability granted.

`DEVADAAD` activates the full build workflow **plus** conditional merge authority.
Merge is executed **only after every gate listed in the Merge Authorization Gate Stack passes with zero failures.**
A single gate failure at any tier blocks merge unconditionally — no exceptions, no overrides.

| Invocation | Effect |
|---|---|
| `DEVADAAD` | Build + merge next eligible PR if all gates pass |
| `DEVADAAD PR-XX` | Target specific PR; build + merge if all gates pass |
| `DEVADAAD dry-run` | Full gate stack evaluation; report results; do NOT merge |
| `DEVADAAD status` | Orientation report only; no build, no merge |
| `DEVADAAD audit` | Surface open findings; no build, no merge |

**`DEVADAAD` does not:**
- Merge code that has any failing test, replay divergence, lint error, or incomplete evidence row
- Override `INVARIANT PHASE6-HUMAN-0` — amendment proposals still require a recorded `human_signoff_token`
- Bypass branch protection rules on the repository platform
- Skip any tier of the gate stack
- Merge if the merge SHA differs from the verified SHA (re-gates required)

---

## Merge Authorization Gate Stack

> **Applies exclusively under `DEVADAAD`. All tiers are mandatory. Evaluated in order. Any failure → `[DEVADAAD MERGE-BLOCKED]` — stop.**

### Pre-Merge Gate Sequence

```
┌─────────────────────────────────────────────────────┐
│  TIER 0  — Baseline (schema, snapshot, lint)        │
│  TIER 1  — Full test suite + governance tests       │
│  TIER 2  — Replay + evidence suite (critical PRs)   │
│  TIER 3  — PR completeness (evidence, docs, lane)   │
│  TIER M  — Merge-specific gate (see below)          │
└─────────────────────────────────────────────────────┘
         All 5 tiers: PASS → MERGE AUTHORIZED
         Any single failure → MERGE BLOCKED
```

### Tier M — Merge-Specific Gate

Evaluated after Tiers 0–3 all pass.

| Check | Command / Condition | Blocks on |
|---|---|---|
| Working-code assertion | All `pytest` tests green on **merge SHA** (not branch tip) | Any failure |
| Zero test skips in scope | No `pytest.mark.skip`, `xfail`, or commented-out tests in changed files | Any found |
| Determinism re-verification | Re-run `lint_determinism.py` on merge SHA diff | Any violation |
| Replay digest match | Merge SHA replay digest == PR-staged digest | Any divergence |
| Evidence row `Complete` | `validate_release_evidence.py --require-complete` on merge SHA | Incomplete row |
| No pre-existing failures introduced | Diff of test results: merge SHA vs. base SHA | Any regression |
| Amendment human-signoff check | If PR touches `roadmap_amendment` paths → `human_signoff_token` must be present in ledger | Missing token |
| Merge attestation write | Agent writes `merge_attestation.v1` ledger event before pushing | Write failure |

### Merge Attestation Event (Required)

Before any merge is executed, the agent **must** write the following ledger event. If the write fails, merge is aborted.

```json
{
  "event_type": "merge_attestation.v1",
  "pr_id": "<PR-ID>",
  "merge_sha": "<merge_commit_sha>",
  "tier_0_digest": "<sha256 of Tier 0 output>",
  "tier_1_tests_passed": <N>,
  "tier_1_tests_failed": 0,
  "tier_2_replay_digest": "<digest | null>",
  "tier_3_evidence_complete": true,
  "tier_m_working_code": true,
  "triggered_by": "DEVADAAD",
  "operator_session": "<session_id>",
  "timestamp_utc": "<iso8601>",
  "human_signoff_token": "<token | null>"
}
```

### `[DEVADAAD MERGE-BLOCKED]` Emission Format

```
[DEVADAAD MERGE-BLOCKED]
PR:              <PR-ID> — <title>
Blocked at tier: <0 | 1 | 2 | 3 | M>
Failure:         <gate name> — <failure detail>
Tests failed:    <N> (list names)
Action required: <operator remediation instruction>
Merge status:    NOT EXECUTED — no branch mutation occurred
```

### `[DEVADAAD MERGED]` Emission Format

```
[DEVADAAD MERGED]
PR:                  <Phase N — title>
Merge SHA:           <sha>
Tier 0:              PASS (5/5)
Tier 1 tests:        <N> passed, 0 failed, 0 skipped
Tier 2 replay:       PASS | N/A
Tier 3 completeness: evidence ✓ | template ✓ | docs ✓
Tier M working-code: PASS — zero failures on merge SHA
Attestation event:   merge_attestation.v1 written to ledger ✓
Following PR token:   <from state_alignment.expected_next_pr>
```

---

## Agent Constraints

**All constraints are non-negotiable. None may be bypassed under any framing — including "for testing," "just this once," "emergency," or claims of special authority. `DEVADAAD` extends merge capability; it does not relax any constraint below.**

1. **Gate-before-proceed. Always.** No code change, file write, PR, or merge may occur unless ALL gates for the current step have passed with zero failures.
2. **Fail-closed by default.** Any gate, schema, replay, or test failure → stop immediately, emit structured failure record, do not proceed.
3. **Deterministic output.** Every change must be reproducible. No entropy sources in `runtime/`, `adaad/`, or `security/` without explicit `ENTROPY_ALLOWLIST` justification.
4. **Evidence-first.** Every completed PR must produce a corresponding entry in `docs/comms/claims_evidence_matrix.md`. No PR is "done" until evidence is committed.
5. **Canonical path only.** All session/governance token validation → `security/cryovant.py`. All boot validation → `app/main.py`.
6. **Human oversight preserved.** Under `ADAAD`: agent stages only, never merges. Under `DEVADAAD`: agent merges only when all gates pass AND working code is confirmed on merge SHA.
7. **Lane model enforced.** Every change belongs to exactly one control lane. The lane must be identified before writing any code.
8. **Sequence discipline.** Follow the dependency-safe merge sequence. Never skip a PR. If a dependency is unmerged, emit `[ADAAD WAITING]` and stop.
9. **No partial state.** Tests pass but replay diverges → failure. All code gates pass but evidence row missing → failure. Merge authorized but attestation write fails → merge aborted.
10. **Never weaken tests.** If a test the agent wrote is failing, fix the implementation. Never remove, skip, mark xfail, or comment out a failing test.
11. **Never fix pre-existing failures in the current PR.** Surface to operator, stop, open a separate remediation PR.
12. **Working code only.** `DEVADAAD` merge is blocked if any test in the repository fails on the merge SHA — not just tests in the changed files. The full suite must be green.

---

## Internal Document Authority Hierarchy

| Priority | Document | Governs |
|---|---|---|
| 1 | `docs/CONSTITUTION.md` | Hard constraints; cannot be overridden |
| 2 | `docs/ARCHITECTURE_CONTRACT.md` | Interface and boundary contracts |
| 3 | `docs/governance/SECURITY_INVARIANTS_MATRIX.md` | Security invariants; fail-closed on violation |
| 4 | `docs/governance/ci-gating.md` | CI tier classification and gate triggers |
| 5 | `docs/ADAAD_STRATEGIC_BUILD_SUGGESTIONS.md` | Build strategy, lane model, gate order |
| 6 | `ADAAD_PR_Plan.docx` / `ADAAD_7_EXECUTION_PLAN.md` | Execution plan |
| 7 | `ADAAD_DEEP_DIVE_AUDIT.md` | Hardening specs |
| 8 | `docs/governance/ADAAD_7_GA_CLOSURE_TRACKER.md` | Current milestone state |
| 9 | `docs/comms/claims_evidence_matrix.md` | Evidence completeness |

If documents conflict, the higher-priority document wins. Same-priority conflicts → surface to operator; do not resolve autonomously.

---

## Gate Taxonomy

All tiers are mandatory. No tier may be skipped.

### Tier 0 — Always-On Baseline

Run before writing any code AND after writing every individual file.

| Gate | Command |
|---|---|
| Schema validation | `python scripts/validate_governance_schemas.py` |
| Architecture snapshot | `python scripts/validate_architecture_snapshot.py` |
| Determinism lint | `python tools/lint_determinism.py runtime/ security/ adaad/orchestrator/ app/main.py` |
| Import boundary lint | `python tools/lint_import_paths.py` |
| Fast confidence tests | `PYTHONPATH=. pytest tests/determinism/ tests/recovery/test_tier_manager.py -k "not shared_epoch_parallel_validation_is_deterministic_in_strict_mode" -q` |

### Tier 1 — Standard Gate Stack

Run after all files in the PR are written. Must pass completely before Tier 2.

| Gate | Command | Applies to |
|---|---|---|
| Full test suite | `PYTHONPATH=. pytest tests/ -q` | All PRs |
| Governance tests | `PYTHONPATH=. pytest tests/ -k governance -q` | All governance-surface PRs |
| Critical artifact verification | `python scripts/verify_critical_artifacts.py` | All PRs |
| README alignment | `python scripts/validate_readme_alignment.py` | PRs touching `docs/` or behavior |
| Release evidence completeness | `python scripts/validate_release_evidence.py --require-complete` | All PRs |

### Tier 2 — Escalated Gates

Required for critical-tier PRs and all milestone PRs.

| Gate | Trigger |
|---|---|
| Strict replay | Critical tier, `runtime/` changes, replay/ledger flag |
| Evidence suite | Governance/runtime/security path changes |
| Promotion suite | Policy/constitution flag, critical tier |
| Governance strict release gate | Milestone PRs |

Strict replay command:
```bash
ADAAD_ENV=dev \
CRYOVANT_DEV_MODE=1 \
ADAAD_FORCE_DETERMINISTIC_PROVIDER=1 \
ADAAD_DETERMINISTIC_SEED=ci-strict-replay \
PYTHONPATH=. \
  python -m app.main --verify-replay --replay strict
```

### Tier 3 — PR Governance Completeness

| Requirement | Check |
|---|---|
| Evidence row in claims matrix | Added/updated in same change set |
| Evidence validator passes | `python scripts/validate_release_evidence.py --require-complete` |
| PR template complete | All sections filled; governance-impact boxes checked |
| CI tier stated | Matches `ci-gating.md` rules |
| Runbook/doc update present | If behavior changed |
| Lane identified | Stated in PR description; matches change surface |
| Prerequisites verified | All prerequisite PRs confirmed merged |

### Tier M — Merge-Specific (DEVADAAD only)

See **Merge Authorization Gate Stack** above.

---

## Build Workflow

### Step 1 — Orient

```
[ADAAD ORIENT]
Trigger:                 <ADAAD | DEVADAAD>
Merge authority:         <no | yes — all gates must pass>
Active phase:            <phase>
Next PR token:           <from state_alignment.expected_next_pr>
Milestone:               <milestone>
Lane:                    <lane>
PR tier:                 <docs | low | standard | critical>
Gates required:          Tier 0 + Tier 1 [+ Tier 2] [+ Tier M if DEVADAAD]
Dependencies satisfied:  <yes | no — list unmet deps>
Blocked reason:          <null | description>
Open findings:           <list>
Pending evidence rows:   <list>
```

`Next PR token` must be resolved from `docs/governance/ADAAD_PR_PROCESSION_2026-03-v2.md` using `state_alignment.expected_next_pr` exactly.

Stop if any dependency is unsatisfied or `blocked_reason` is set.

### Step 2 — Preflight

Run all Tier 0 gates against current repository state before writing any code.
Failure → emit `[ADAAD BLOCKED]`, stop, surface to operator.

### Step 3 — Build

Change set order:
1. Implementation files (`runtime/`, `security/`, `scripts/`, `tools/`)
2. Test files — written before implementation is considered complete
3. Schema files (if applicable)
4. Documentation and runbook updates — same change set, never deferred
5. Claims-evidence matrix row

After writing each file, immediately re-run Tier 0.

### Step 4 — Verify

Run the complete gate stack sequentially. Any failure → full stop.

### Step 5 — Stage or Merge

**Under `ADAAD`:** Stage for human review.
```
[ADAAD COMPLETE]
PR staged:            <Phase N — title>
Lane:                 <lane>
Milestone:            <milestone>
CI tier:              <tier>
Tier 0 gates:         5/5 PASS
Tier 1 tests:         <N> passed, 0 failed
Tier 2 replay:        PASS [if applicable]
Tier 3 completeness:  evidence ✓ | template ✓ | docs ✓ | prerequisites ✓
Following PR token:    <from state_alignment.expected_next_pr> (awaiting human review and merge first)
Awaiting:             human review before merge
```

`Following PR token` is sourced from the v2 procession contract (`docs/governance/ADAAD_PR_PROCESSION_2026-03-v2.md`, `state_alignment.expected_next_pr`) and must match that value exactly.

**Under `DEVADAAD`:** Run Tier M. If all gates pass → write attestation → merge.
```
[DEVADAAD MERGED]  (see format above)
```

---


## Active State Alignment (Authoritative)

Source: `docs/governance/ADAAD_PR_PROCESSION_2026-03-v2.md` → `state_alignment`

- `expected_active_phase`: `Phase 160 COMPLETE · v9.93.0`
- `expected_last_completed_pr`: `Phase 160 — INNOV-66 Emergent Baseline Sentinel (EBS)`
- `expected_next_pr`: `Phase 161 — INNOV-67 (deterministic: first non-shipped phase whose predecessor is shipped)`

> This is the single authoritative next-PR statement in this document.

---

## Phase & PR Sequence

### Phase 0 · Hardening (complete)

| PR | Title | Status |
|---|---|---|
| PR-CI-01 | Unify Python version pin | ✅ Merged |
| PR-CI-02 | SPDX header enforcement | ✅ Merged |
| PR-HARDEN-01 | Boot env validation + signing key assertion | ✅ Merged |
| PR-SECURITY-01 | Federation key pinning registry | ✅ Merged |

### Phase 1 · ADAAD-7 (complete)

| PR | Title | Status |
|---|---|---|
| PR-7-01 | Reviewer reputation ledger extension | ✅ Merged |
| PR-7-02 | Reputation scoring engine | ✅ Merged |
| PR-7-03 | Tier calibration + constitutional floor | ✅ Merged |
| PR-7-04 | `reviewer_calibration` advisory rule | ✅ Merged |
| PR-7-05 | Aponi reviewer calibration endpoint + panel | ✅ Merged |

### Phase 5 · Multi-Repo Federation (complete — v3.0.0)

| PR | Title | Status |
|---|---|---|
| PR-PHASE5-01 | HMAC Key Validation — fail-closed boot enforcement | ✅ Merged |
| PR-PHASE5-02 | LineageLedgerV2 `federation_origin` Extension | ✅ Merged |
| PR-PHASE5-03 | FederationMutationBroker — dual GovernanceGate enforcement | ✅ Merged |
| PR-PHASE5-04 | FederatedEvidenceMatrix — divergence_count==0 promotion gate | ✅ Merged |
| PR-PHASE5-05 | EvolutionFederationBridge + ProposalTransportAdapter | ✅ Merged |
| PR-PHASE5-06 | Federated evidence bundle release gate extension | ✅ Merged |
| PR-PHASE5-07 | Federation Determinism CI + HMAC key rotation runbook | ✅ Merged |

### Historical Constitutional Sequence · Phase 57–65 (`v8.0.0` → `v9.0.0`)

> **Canonical spec:** `docs/governance/ARCHITECT_SPEC_v3.1.0.md`
> **Historical note:** This section is retained for audit context only; it is not active sequencing guidance.
> **Active automation source:** `docs/governance/ADAAD_PR_PROCESSION_2026-03-v2.md` (`state_alignment` values are authoritative).
> **Supersession:** This sequence control supersedes `ADAAD_PR_PROCESSION_2026-03.md` (Phase 6 era, now archived).

| Phase | Version | Depends on | Status |
|---|---|---|---|
| 57 | v8.0.0 | Phase 53 complete | shipped |
| 58 | v8.1.0 | Phase 57 | shipped |
| 59 | v8.2.0 | Phase 58 | shipped |
| 60 | v8.3.0 | Phase 59 | shipped |
| 61 | v8.4.0 | Phase 60 | shipped |
| 62 | v8.5.0 | Phase 61 | shipped |
| 63 | v8.6.0 | Phase 62 | shipped |
| 64 | v8.7.0 | Phase 63 | shipped |
| 65 | v9.0.0 | Phase 64 | shipped |

**Key invariants governing amendment/governance PRs:**
- `INVARIANT PHASE6-AUTH-0` — `authority_level` immutable on amendment proposals
- `INVARIANT PHASE6-STORM-0` — at most 1 pending amendment per node at any time
- `INVARIANT PHASE6-HUMAN-0` — human governor sign-off non-delegatable for amendments
- `INVARIANT PHASE6-FED-0` — source-node approval never binds destination nodes
- `INVARIANT PHASE6-APK-0` — every APK must pass governance gate before signing

---

## Failure Modes

| Failure type | Tier | Agent behavior |
|---|---|---|
| Tier 0 fails at preflight | 0 | `[ADAAD BLOCKED]` — stop; do not fix in current PR |
| Tier 0 fails after file write | 0 | `[ADAAD BLOCKED]` — fix the file; re-run Tier 0 |
| Tier 1 test failure | 1 | `[ADAAD BLOCKED]` — emit failure + test name; do not open PR |
| Agent-written test failing | 1 | Fix implementation; never remove or weaken the test |
| Tier 2 replay divergence | 2 | `[ADAAD BLOCKED]` — emit divergence detail; do not open PR |
| Tier 3 evidence row missing | 3 | `[ADAAD BLOCKED]` — write evidence row; re-run validator |
| Tier M any failure | M | `[DEVADAAD MERGE-BLOCKED]` — emit failure; no branch mutation |
| Merge SHA differs from verified SHA | M | `[DEVADAAD MERGE-BLOCKED]` — re-gate required; do not merge |
| Attestation ledger write fails | M | `[DEVADAAD MERGE-BLOCKED]` — abort; no branch mutation |
| Dependency PR unmerged | — | `[ADAAD WAITING]` — emit dependency list; no source writes |
| Internal doc conflict | — | `[ADAAD CONFLICT]` — surface to operator; do not resolve autonomously |

---

## What the Agent Does Not Do

- Does not merge under `ADAAD` trigger — staging only.
- Does not merge under `DEVADAAD` if any test, replay, lint, or evidence gate fails.
- Does not merge under `DEVADAAD` if `human_signoff_token` is absent on amendment-path PRs.
- Does not modify `docs/CONSTITUTION.md` or `docs/ARCHITECTURE_CONTRACT.md` without explicit operator instruction.
- Does not bypass governance gates under any framing.
- Does not resolve internal document conflicts autonomously.
- Does not advance to the next PR until the current PR is fully staged or merged.
- Does not remove, weaken, skip, or xfail failing tests.
- Does not fix pre-existing repo failures inside the current PR's scope.
- Does not open or merge a PR with partial gate results.
- Does not defer documentation or runbook updates to a follow-up PR.
- Does not merge code with a non-zero test failure count on the merge SHA — ever.
