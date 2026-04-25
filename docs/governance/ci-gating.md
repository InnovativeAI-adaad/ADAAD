# CI Gating Policy

This repository uses tiered CI gating to keep pull request feedback fast while preserving strict checks for governance-critical changes.

All CI workflows that invoke `actions/setup-python` are pinned to Python `3.11.9`; version drift is fail-closed by `scripts/check_workflow_python_version.py` in CI.

## Phase progression source consumed by automation

For machine phase progression/state alignment, automation consumes only `docs/governance/ADAAD_PR_PROCESSION_2026-03-v2.md` §3.0 **Active Era Contract (Phases 131–136+)**. `ROADMAP.md` and innovation summary documents are human-facing mirrors and must remain consistent, but are not the progression authority.

## Inputs used by the CI classifier

The CI classifier computes gate decisions from three signal groups:

1. **Changed paths**
   - `docs/**` and markdown files (`**/*.md`)
   - `tests/**`
   - `governance/**` and `docs/governance/**`
   - `runtime/**`, `app/**`, and `nexus_setup.py`
   - `security/**`
   - supporting non-doc paths (`.github/**`, `scripts/**`, `tools/**`, dependency manifests)
2. **Computed PR tier**
   - `docs`: docs-only changes
   - `low`: tests-only changes
   - `standard`: default code changes without governance/runtime/security impact
   - `critical`: governance/runtime/security changes or governance-impact flags
3. **Governance-impact flags** (from PR template)
   - `Changes policy/constitution behavior`
   - `Changes replay or ledger behavior`

## Always-on baseline jobs

These jobs run for every CI execution:

- `schema-validation`: governance schema validation
- `determinism-lint`: deterministic-behavior lint checks
- `confidence-fast`: fast confidence tests (`tests/determinism` + recovery tier manager test)

### Local preflight parity notes

To reproduce Tier 0 deterministically in local environments, run commands with `PYTHONPATH=.` and install test dependencies before invoking `pytest` (for example, `fastapi` is required by `tests/conftest.py`). This keeps local preflight behavior aligned with CI job environments and avoids false-negative gate failures caused only by missing local packages.

## Escalated gated suites

## Lane → workflow → required-check source-of-truth

Use this table as the canonical mapping to prevent drift between lane ownership, workflow files, and required check names.

| Lane | Workflow file | Required check name |
|---|---|---|
| Contract | `.github/workflows/ci.yml` | `schema-validation` |
| Determinism | `.github/workflows/ci.yml` | `determinism-lint` |
| Security | `.github/workflows/ci.yml` | `artifact-trust-verification` |
| Secret-scanning | `.github/workflows/secret_scan.yml` | `Secret Scan / secret-scan` |
| Evidence | `.github/workflows/ci.yml` | `release-evidence-readiness` |
| Evidence publish | `.github/workflows/ci.yml` | `aeo-evidence-publish` |
| Documentation | `.github/workflows/ci.yml` | `docs-validation` |
| Replay (critical) | `.github/workflows/ci.yml` | `strict-replay` |
| Promotion (critical) | `.github/workflows/ci.yml` | `promotion-suite` |
| Shadow governance (policy) | `.github/workflows/ci.yml` | `shadow-governance-gate` |
| Workflow integrity | `.github/workflows/ci.yml` | `workflow-integrity-validation` |
| Release strict gate | `.github/workflows/governance_strict_release_gate.yml` | `release-gate` |
| Post-merge docs sync | `.github/workflows/post_merge_doc_sync.yml` | `post-merge-doc-sync-contract-gate` |

These jobs run only when classifier gates evaluate to `true`:

### Conditional required-check mapping

| Required check | Trigger condition | Selector scope |
|---|---|---|
| `strict-replay` | `pr_tier=critical` or replay/ledger flag from PR template | strict deterministic replay verification |
| `evidence-suite` | governance/runtime/security path changes or replay/ledger impact flag | evidence/sandbox tests |
| `promotion-suite` | governance/runtime path changes, policy/constitution flag, or `pr_tier=critical` | governance/promotion selectors |
| `shadow-governance-gate` | `policy_touch=true` (canonical set: `runtime/governance/constitution.yaml`, `governance/**`, `schemas/governance_policy*.json`, `schemas/governance_policy_artifact*.json`, `docs/schemas/constitution.v1.json`) or policy/constitution flag from PR template | replay-only policy evaluator against historical ledgers |
| `phase7-reputation-gate` | governance/server/relevant UI path changes (`governance/**`, `server.py`, `ui/**`) | reviewer reputation + ledger + pressure + constitutional-floor + reviewer panel endpoint/UI coverage |
| `pr3h-acceptance-gate` | PR-3H closure scope (`tests/acceptance/pr3h/**`, `scripts/validate_pr3h_acceptance.py`, checkpoint/entropy replay acceptance surfaces) | checkpoint tamper escalation + entropy triage replay fixtures via machine-readable audit output |
| `benchmark-regression-gate` | always-on CI promotion check | deterministic benchmark generation + category delta non-regression (`scripts/validate_benchmark_deltas.py`) |
| `post-merge-doc-sync-contract-gate` | phase-governance docs/procession/release/evidence contract changes (`docs/governance/post_merge_doc_sync_contract.yaml`, `ROADMAP.md`, `docs/governance/ADAAD_PR_PROCESSION_2026-03-v2.md`, `docs/releases/*.md`, `docs/comms/claims_evidence_matrix.md`) | post-merge docs consistency validator (`scripts/validate_post_merge_doc_sync.py`) |
| `aeo-evidence-publish` | `release-evidence-readiness` succeeded and `AEO_EVIDENCE_DESTINATION` configured in secrets | deterministic CI bundle build + schema validation + single-attempt publish (`scripts/publish_aeo_evidence_bundle.py`) |

- `strict-replay`
  - Runs for `critical` tier or replay/ledger impact flag.
  - Skips for docs-only and tests-only changes.
- `evidence-suite`
  - Runs when governance/runtime/security paths changed or replay/ledger impact is flagged.
- `promotion-suite`
  - Runs when governance/runtime paths changed, policy/constitution impact is flagged, or the PR is `critical` tier.
- `shadow-governance-gate`
  - Non-optional when either trigger is true: classifier `policy_touch=true` **or** PR template policy/constitution checkbox (`gov_policy_flag=true`).
  - Canonical `policy_touch` path set in `.github/workflows/ci.yml` (`dorny/paths-filter`):
    - `runtime/governance/constitution.yaml`
    - `governance/**`
    - `schemas/governance_policy*.json`
    - `schemas/governance_policy_artifact*.json`
    - `docs/schemas/constitution.v1.json`
  - Exact gate behavior: `run_shadow_governance_gate=true` iff `POLICY_TOUCH == true || gov_policy_flag == true`.
  - Runs `scripts/evaluate_shadow_governance.py` in replay-only mode against `tests/fixtures/governance/shadow_replay_ledger.json`.
  - Fails closed when any threshold breach occurs (`false_allow_rate > 0.05`, `false_block_rate > 0.20`, or `divergence_count > 3`).
- `phase7-reputation-gate`
  - Runs when governance/server/relevant UI paths change (`governance/**`, `server.py`, `ui/**`).
  - Executes the Phase 7 invariant selector set: reviewer reputation scoring, reviewer reputation ledger, review pressure, constitutional-floor coverage, and reviewer panel endpoint/UI coverage.

- `post-merge-doc-sync-contract-gate`
  - Required Tier 3 completeness gate for phase-governance PRs that touch roadmap/procession/release/evidence synchronization surfaces.
  - Runs `python scripts/validate_post_merge_doc_sync.py`.
  - Fails closed when contract-required docs, release note version alignment, roadmap/procession phase status consistency, or evidence completion requirements drift.

- `aeo-evidence-publish`
  - Always runs after `release-evidence-readiness` and fails closed if `AEO_EVIDENCE_DESTINATION` is unset or unreachable.
  - Uses `scripts/publish_aeo_evidence_bundle.py` to:
    1. Build deterministic CI-scoped evidence bundle.
    2. Validate bundle against `schemas/evidence_bundle.v1.json`.
    3. Publish exactly once to configured AEO destination (no retry loops, no backoff mutation).


- `pr3h-acceptance-gate`
  - Required evidence gate for PR-3H closure.
  - Runs `python scripts/validate_pr3h_acceptance.py` and requires a passing machine-readable audit artifact (`artifacts/pr3h_acceptance_audit.json`) from CI.
  - PR-3H is not considered complete until the uploaded artifact reports `"status": "pass"`.


## Benchmark regression gate (required)

A dedicated CI job, `benchmark-regression-gate`, enforces deterministic benchmark promotion controls:

1. Generate machine-readable benchmark output and scorecard via
   `python scripts/run_release_benchmarks.py --release-candidate ci-${GITHUB_SHA}`.
2. Compare candidate benchmark results against the baseline release benchmark artifact using
   `python scripts/validate_benchmark_deltas.py --baseline <baseline> --candidate <candidate>`.

Promotion is blocked on any category regression unless a signed waiver JSON is provided and passes
signature and category-consistency validation. Missing or invalid waiver input fails closed.

## Simplification contract gate (required)

A dedicated CI job, `simplification-contract-gate`, runs `python scripts/validate_simplification_targets.py`
on every CI execution and is fail-closed.

The gate enforces governance-backed simplification KPIs:

- maximum file-size and fan-in budgets for critical files
- legacy-path reduction target contract + no-regression guardrail
- 100% unified metrics-schema producer adoption coverage
- runtime cost bounds and mutation experiment caps

Any drift above contract thresholds blocks CI and must be remediated before merge.

## Auditability and CI summary

Every run emits a `CI gating summary` in the workflow summary page with:

- classifier inputs (path booleans + governance flags)
- computed tier
- each gated job's result and reason it ran or was skipped

### QA7 lint rollout flag policy and skip reporting

`QA7_LINT_ROLLOUT` is restricted to the explicit experimental lane:

- `tests/rollout/**` with `pytest -m qa7` selection.
- The flag must remain unset in baseline/full-suite lanes so default CI remains always-on for non-experimental determinism tests.
- QA7 tests skipped because `QA7_LINT_ROLLOUT` is unset are reported as **conditional experimental skips** and must be called out separately from unexpected skips in CI summaries.

This provides audit-ready traceability for CI escalation decisions.

Simplification KPI enforcement is audited as a constitutional-grade control and is included in
the CI summary table under `simplification-contract-gate`.

## Two-tier docs validation strategy

`docs-validation` in `.github/workflows/ci.yml` now resolves a deterministic tier:

- `full` mode for critical-tier PRs, `push` runs, `workflow_dispatch` runs, and any governance/runtime/security path touches.
- `scoped` mode for standard/docs-tier PRs, using changed-file input for:
  - `scripts/validate_docs_integrity.py --changed-files`
  - `scripts/lint_active_docs_dependency_refs.py --changed-files`

Fail-closed governance behavior is preserved by always running a full integrity scan over
`docs/governance`, `docs/comms`, `docs/release`, and `docs/releases`, and by expanding those
roots in scoped mode whenever one of those paths is touched.

To maintain full-repo drift detection, full docs validation also runs in:

- nightly schedule workflow: `.github/workflows/docs_nightly.yml`
- strict release workflow: `.github/workflows/governance_strict_release_gate.yml` (`full-docs-validation` job)

Each docs-validation run publishes per-step timing and total elapsed seconds in the workflow
summary for performance tracking.


## Secret scanning gate (required)

A dedicated workflow, `.github/workflows/secret_scan.yml`, runs on `pull_request` and `push` to `main` and is configured to fail on findings. It scans both:

- repository contents (`gitleaks dir --source .`)
- commit history (`gitleaks git`), including PR diff ranges via `base.sha..head.sha` when available

`Secret Scan / secret-scan` must be configured as a **required status check** in branch protection for `main`. This prevents secret-scan failures (or removal from required checks) from being bypassed silently.

## Workflow integrity gate (required)

The CI workflow includes an always-on job, `workflow-integrity-validation`, which runs `python scripts/validate_workflow_integrity.py`.

The gate is fail-closed and enforces repository-level CI control invariants:

- every workflow file in `.github/workflows` declares a top-level `name:` field
- no duplicate workflow names across workflow files
- CodeQL workflow surface is canonicalized to exactly `.github/workflows/codeql.yml`

This prevents duplicate or drifting workflow definitions from silently weakening branch-protection signal quality.

## Governance-impact override guidance

CI workflow edits that change **gate logic** (for example, conditions controlling strict replay, evidence suites, promotion suites, or release evidence checks) must be treated as governance-impact changes even when file-path tiering alone would classify them below Tier-0.

For those PRs, explicitly check the governance-impact boxes in the PR template so classifier flags (`gov_policy_flag` / `gov_replay_flag`) force the stricter suites and review path.

## Quarterly security review workflow (required)

To enforce ongoing independent assurance for API/auth/governance surfaces, CI governance includes a quarterly security-review control workflow and remediation policy integration.

### Workflow contract

- Workflow file: `.github/workflows/security_quarterly_review.yml`.
- Trigger model:
  - scheduled quarterly run (`on.schedule`) as governance evidence heartbeat;
  - manual dispatch (`workflow_dispatch`) for out-of-band reassessment;
  - optional invocation during release hardening windows.
- Minimum output artifacts:
  - current-quarter independent penetration test summary;
  - architecture review delta summary;
  - finding register with severity labels and SLA due dates;
  - attestation that unresolved Critical/High items were evaluated against release gating policy.

### Severity-based remediation deadlines

This workflow is policy-coupled to `docs/compliance/REMEDIATION_SLA.md`, which defines mandatory fix deadlines:

- Critical: remediate within 7 calendar days (containment within 24 hours).
- High: remediate within 14 calendar days.
- Medium: remediate within 45 calendar days.
- Low: remediate within 90 calendar days.

Any overdue finding must be emitted as a fail-closed governance signal in CI reporting.

### Release and governance effects

- Open Critical/High findings beyond SLA block promotion/release unless a signed risk acceptance is recorded.
- Quarterly review artifacts become required evidence for governance and compliance audits.
- Security-review workflow status should be configured as required in branch/release protection where supported.

### Public-facing disclosure policy

The quarterly review workflow and associated compliance process follow coordinated public disclosure commitments:

- acknowledge inbound vulnerability reports within 3 business days;
- provide active investigation updates at least every 7 calendar days for High/Critical issues;
- publish Critical/High advisories with a target of 30 days from confirmation (or sooner for active exploitation);
- publish Medium findings in the next scheduled security bulletin cycle (target 90 days).

Disclosure implementation details and exceptions are defined in `docs/compliance/REMEDIATION_SLA.md`.


## Local strict replay parity with CI

To reproduce CI strict replay behavior locally, run replay verification with the same deterministic provider flags used by the `strict-replay` job:

```bash
ADAAD_ENV=dev CRYOVANT_DEV_MODE=1 ADAAD_FORCE_DETERMINISTIC_PROVIDER=1 ADAAD_DETERMINISTIC_SEED=ci-strict-replay \
  python -m app.main --verify-replay --replay strict
```



## Constitutional acceptance gate

`tests/governance/inviolability/` is the constitutional acceptance gate for non-bypass governance invariants.

Required invariant coverage (positive + adversarial cases):

- mutation execution cannot proceed without constitutional/lifecycle guard pass
- strict replay divergence fail-closes, while audit mode remains observable/non-fail-closed
- nondeterministic providers are rejected on strict replay and audit-tier governance paths
- policy authority cannot expand via undeclared lifecycle jumps; only explicit classified transitions are allowed
- governance self-mutation requires explicit high-risk authority approval

The suite asserts auditable artifacts (ledger/journal event types and required payload keys) for rejection and transition paths to preserve deterministic forensic evidence in CI.

## Governance review telemetry SLO checks

For governance-impact PRs, operators should verify review-quality KPIs in addition to CI jobs:

- Query `/metrics/review-quality?limit=500&sla_seconds=86400`.
- Alert when:
  - `reviewed_within_sla_percent < 95.0`
  - `reviewer_participation_concentration.largest_reviewer_share > 0.60`
  - `review_depth_proxies.override_rate_percent > 20.0`

This endpoint is intended for dashboard ingestion and automated threshold alerting.


## Strict release gate workflow

Release-tag pushes and manual release gate runs now use `.github/workflows/governance_strict_release_gate.yml`.

Required jobs (all blocking):

- `determinism-lint`
- `entropy-discipline-checks`
- `governance-strict-mode-validation`
  - Includes a rule-activation assertion that fails when any constitution rule with baseline `severity=blocking` or a `tier_overrides` blocking severity is disabled in `runtime/governance/constitution.yaml`.
- `replay-strict-validation`
- `constitution-fingerprint-stability`
- `reviewer-calibration-validation`
  - Runs the Phase 7 reviewer calibration selector set (reputation, ledger, review pressure, constitutional-floor, and reviewer panel endpoint/UI coverage).

The terminal `release-gate` job is fail-closed and requires each upstream job result to be `success`; any failure, cancellation, or skip state blocks release gating.


- The strict release rule-activation assertion uses the runtime constitution policy loader (`runtime.constitution.load_constitution_policy`) to avoid parser drift between CI checks and runtime governance evaluation.


## Maintainer note: import-boundary fixer command

Use a single canonical entrypoint for import-boundary autofixes:

- `python fix_import_boundaries.py ...`

`tools/fix_import_boundaries.py` remains a deprecated compatibility wrapper and should not be used in new CI or documentation references.

## Generated artifact validation workflow

A dedicated workflow, `.github/workflows/ci-generated.yml`, validates deterministic outputs from `examples/single-agent-loop/run.py`.

It runs a matrix over generated fixtures and enforces fail-closed validation lanes for:

- targeted generated-artifact functional checks (`pytest` under `tests/generated/`),
- static typing checks (`mypy` on generated adapters/parsers),
- security scanning (`bandit` on generated Python artifacts),
- sandboxed execution checks using `runtime.test_sandbox` and `runtime/sandbox/*` integration.

Each matrix leg stores deterministic evidence under `tests/generated/evidence/<fixture>/` and lane reports under `tests/generated/reports/<fixture>/`, then uploads both as CI artifacts together with `metadata-summary.json` for dashboard ingestion.

## Python dependency cache policy in CI

`CI` now uses a shared composite action at `.github/actions/setup-python-env/action.yml` for all Python jobs in `.github/workflows/ci.yml`.

- `actions/setup-python@v5` is configured with `cache: pip`.
- `cache-dependency-path` includes both `requirements*.txt` and `pyproject.toml`.
- Jobs that execute tests or tooling with third-party dependencies set `install-deps: "true"` to run the same pip upgrade and requirements install logic.
- Jobs that only execute stdlib scripts still use the same cache configuration for consistency, without forcing unnecessary installs.

Cache invalidation is automatic when any file matching `requirements*.txt` or `pyproject.toml` changes, because those files are included in the dependency hash.

Expected performance impact (typical PR runs):

- First run after dependency changes: near current baseline (cache miss).
- Subsequent runs with unchanged dependency manifests: reduced setup/install wall time, typically saving ~30-60 seconds per Python job depending on runner load and wheel availability.
- Overall CI time improves most on workflows with multiple dependency-installing jobs (`schema-validation`, `full-test-suite`, `governance-tests`, `confidence-fast`, and conditional critical suites).

This optimization preserves fail-closed behavior: no mandatory gate was changed to `continue-on-error`, and existing gating semantics remain intact.


---

## Phase 6 CI Gating — Roadmap Amendment (v3.1.0)

**Authority:** `docs/governance/ARCHITECT_SPEC_v3.1.0.md` §2.7, §3.7
**Effective:** 2026-03-07

### Required CI jobs for PR-PHASE6-02 (M6-03)

All jobs below must pass before PR-PHASE6-02 may merge. These requirements extend
the standard `ci.yml` critical tier with Phase 6-specific gates.

| Job | Workflow | Gate type | Blocks |
|---|---|---|---|
| `phase6-amendment-gate-determinism` | `ci.yml` (extended) | Determinism | PR-PHASE6-02 merge |
| `phase6-storm-invariant` | `ci.yml` (extended) | Constitutional | PR-PHASE6-02 merge |
| `phase6-human-signoff-path` | `ci.yml` (extended) | Constitutional | PR-PHASE6-02 merge |
| `fl-roadmap-signoff-v1-activation` | `governance_strict_release_gate.yml` | Rule activation | v3.1.0 tag |
| `rule-applicability-v1.2.0-valid` | `ci.yml` (extended) | Schema | PR-PHASE6-02 merge |

#### `phase6-amendment-gate-determinism`

**Purpose:** Verify that all six M6-03 prerequisite gates produce identical verdicts
on identical telemetry inputs across two independent evaluation runs.

**Inputs:** Seeded `EpochTelemetry` fixture at epoch boundary; deterministic provider enabled.

**Pass condition:** Gate verdict payloads are byte-identical across both runs.

**Fail condition:** Any divergence → `DETERMINISM_VIOLATION_PHASE6_GATE` · CI blocks.

**Evidence:** Gate verdict digests uploaded as CI artifact for replay attestation.

#### `phase6-storm-invariant`

**Purpose:** Verify `INVARIANT PHASE6-STORM-0` — at most 1 pending amendment at any time.

**Test path:** `tests/autonomy/test_evolution_loop_amendment.py::test_storm_invariant_*`

**Pass condition:** Attempting a second proposal emission while one is PENDING returns
`PHASE6_AMENDMENT_STORM_BLOCKED`; no second proposal is written to ledger.

**Fail condition:** Second proposal emitted or written → Constitutional fault · CI blocks.

#### `phase6-human-signoff-path`

**Purpose:** Verify `FL-ROADMAP-SIGNOFF-V1` — no auto-approval path exists.

**Test path:** `tests/autonomy/test_evolution_loop_amendment.py::test_no_auto_approval_*`

**Pass condition:** All approval paths without `human_signoff_token` raise `GovernanceViolation`.

**Fail condition:** Any auto-approval succeeds → CI blocks; `FL-ROADMAP-SIGNOFF-V1` violation.

#### `fl-roadmap-signoff-v1-activation`

**Purpose:** Assert `fl_roadmap_signoff_v1` rule is registered and BLOCKING in the
runtime constitution policy before v3.1.0 release tag.

**Enforcement:** Extended `governance-strict-mode-validation` job in `governance_strict_release_gate.yml`.

**Pass condition:** Rule name `fl_roadmap_signoff_v1` present in policy with `severity=hard`
and `can_be_overridden=false`.

**Fail condition:** Rule absent or overridable → Release gate blocks tag promotion.

#### `rule-applicability-v1.2.0-valid`

**Purpose:** Verify `governance/rule_applicability.yaml` parses correctly and contains
`fl_roadmap_signoff_v1` with all required fields after v1.2.0 bump.

**Pass condition:** JSON valid; `version == "1.2.0"`; `fl_roadmap_signoff_v1` rule present;
`override_policy.can_be_overridden == false`.

**Fail condition:** Any parse error, version mismatch, or missing rule → CI blocks.

---

### Required CI jobs for PR-PHASE6-03 (M6-04)

| Job | Workflow | Gate type |
|---|---|---|
| `phase6-federated-amendment-dual-gate` | `federation_determinism.yml` (extended) | Constitutional |
| `phase6-federated-propagation-all-or-nothing` | `ci.yml` (extended) | Determinism |
| `phase6-federated-amendment-no-state-inheritance` | `ci.yml` (extended) | Constitutional |

#### `phase6-federated-amendment-dual-gate`

**Purpose:** Verify `INVARIANT PHASE5-GATE-0` (dual-gate) applies to amendment propagation.
Source approval must NOT bind destination.

**Test path:** `tests/governance/federation/test_federated_amendment.py::test_dual_gate_*`

**Pass condition:** Destination node evaluates proposal as PENDING regardless of source status.

**Fail condition:** Destination inherits source approval → Dual-gate violation · CI blocks.

#### `phase6-federated-propagation-all-or-nothing`

**Purpose:** Verify all-or-nothing propagation rollback — if any peer fails, all peers
revert to pre-propagation state.

**Pass condition:** Partial-failure scenario leaves all nodes in pre-propagation state;
ledger records rollback event.

**Fail condition:** Partial propagation persisted → CI blocks; `PARTIAL_PROPAGATION_FAULT`.

#### `phase6-federated-amendment-no-state-inheritance`

**Purpose:** Verify destination receives proposal at `proposed` state regardless of
source state (`pending_governor_review` or `approved`).

**Pass condition:** `federation_origin` field present; proposal state at destination is `proposed`.

**Fail condition:** Destination proposal state != `proposed` → CI blocks.

---

### v3.1.0 Release Gate Extension

The following check is added to `governance_strict_release_gate.yml` before v3.1.0 tag:

- **`phase6-evidence-matrix-complete`**: All Phase 6 evidence rows in
  `docs/comms/claims_evidence_matrix.md` must have non-empty `test_ref` and `artifact_path`
  columns. Any empty cell → release gate blocks.

- **`phase6-roadmap-m6xx-all-shipped`**: M6-01 through M6-05 must all be marked
  `✅ shipped` in `ROADMAP.md`. Any pending milestone → release gate blocks v3.1.0 tag.

---

### Phase 65 Post-Merge Documentation Sync Gate

| Job | Workflow | Gate type |
|---|---|---|
| `phase65-post-merge-sync` | `phase65_post_merge_sync.yml` | Governance state alignment |

**Purpose:** When `PR-PHASE65-01` is merged, enforce deterministic post-merge status synchronization
for `ROADMAP.md` and `docs/governance/ADAAD_PR_PROCESSION_2026-03-v2.md` using fail-closed anchors.

**Trigger condition:** `pull_request.closed` with `merged == true` and PR title or labels containing
`PR-PHASE65-01`.

**Command set:**

- `python scripts/sync_phase_status_on_merge.py`

**Pass condition:**

- `scripts/validate_release_evidence.py --require-complete` passes inside the sync script before writes.
- Phase 65 rows update from `next/pending` to `shipped/complete` (if not already synced).
- Procession `active_phase`/`milestone` and `Next` pointer update to post-65 state.
- Commit is created only when diff is non-empty.

**Fail condition:** Missing anchors, unmet dependency state, or evidence-validation failure aborts with no writes.

> Current canonical progression pointer: `PR-PHASE91-01` (Phase 91 — Post-GA Governance Hardening Sprint).

---

### Formal Amendment Model Check Gate

| Job | Workflow | Gate type |
|---|---|---|
| `amendment-formal-model-check` | `ci.yml` | Formal property check |

**Purpose:** Run bounded formal workflow checks for amendment state transitions whenever PRs touch
`runtime/`, `security/`, `governance/`, or amendment-specific logic.

**Command set:**

- `PYTHONPATH=. python tools/formal/amendment_state_model.py`
- `PYTHONPATH=. pytest tests/formal/test_amendment_state_model.py -q`

**Pass condition:** No invariant violation in bounded model exploration; formal model tests pass.

**Fail condition:** Any property violation or test failure blocks CI.
