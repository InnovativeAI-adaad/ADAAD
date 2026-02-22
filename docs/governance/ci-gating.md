# CI Gating Policy

This repository uses tiered CI gating to keep pull request feedback fast while preserving strict checks for governance-critical changes.

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

## Escalated gated suites

These jobs run only when classifier gates evaluate to `true`:

- `strict-replay`
  - Runs for `critical` tier or replay/ledger impact flag.
  - Skips for docs-only and tests-only changes.
- `evidence-suite`
  - Runs when governance/runtime/security paths changed or replay/ledger impact is flagged.
- `promotion-suite`
  - Runs when governance/runtime paths changed, policy/constitution impact is flagged, or the PR is `critical` tier.

## Auditability and CI summary

Every run emits a `CI gating summary` in the workflow summary page with:

- classifier inputs (path booleans + governance flags)
- computed tier
- each gated job's result and reason it ran or was skipped

This provides audit-ready traceability for CI escalation decisions.


## Governance-impact override guidance

CI workflow edits that change **gate logic** (for example, conditions controlling strict replay, evidence suites, promotion suites, or release evidence checks) must be treated as governance-impact changes even when file-path tiering alone would classify them below Tier-0.

For those PRs, explicitly check the governance-impact boxes in the PR template so classifier flags (`gov_policy_flag` / `gov_replay_flag`) force the stricter suites and review path.


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

The terminal `release-gate` job is fail-closed and requires each upstream job result to be `success`; any failure, cancellation, or skip state blocks release gating.


- The strict release rule-activation assertion uses the runtime constitution policy loader (`runtime.constitution.load_constitution_policy`) to avoid parser drift between CI checks and runtime governance evaluation.
