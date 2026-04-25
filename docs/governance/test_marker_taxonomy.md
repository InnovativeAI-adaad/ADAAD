# Test Marker Taxonomy and CI Gate Intent

The repository uses four canonical **primary lane** markers for tests under `tests/`.
Each collected test item must resolve to **exactly one** primary lane marker.

## Canonical primary markers

| Marker | Lane intent | CI gate intent |
|---|---|---|
| `autonomous_critical` | Deterministic autonomy, replay, and integration surfaces where correctness blocks advancement. | Must be exercised by critical and replay-oriented CI tiers before promotion/merge. |
| `governance_gate` | Governance policy, constitutional enforcement, and decision-ledger boundary tests. | Must be exercised by governance and strict-release CI tiers before promotion/merge. |
| `regression_standard` | Standard regression and API correctness coverage outside critical/governance-only lanes. | Must remain green in baseline/full-suite CI to prevent silent regressions. |
| `dev_only` | Developer-focused acceptance/fixture coverage not used as the primary release signal. | May run in development-focused lanes but still requires marker inventory compliance. |

## Experimental rollout markers

`qa7` is an explicit experimental marker for lint-scope rollout coverage and is constrained as follows:

- Allowed location: `tests/rollout/**` only.
- Required opt-in: `QA7_LINT_ROLLOUT=1`.
- Recommended invocation: `QA7_LINT_ROLLOUT=1 PYTHONPATH=. pytest -m qa7 tests/rollout -q`.
- Default CI policy: baseline/full-suite lanes keep `QA7_LINT_ROLLOUT` unset and treat any resulting QA7 skips as expected conditional skips.

## Enforcement

- Marker declarations live in `pytest.ini`.
- Marker coverage is enforced by `scripts/validate_test_marker_inventory.py`.
- CI runs marker inventory enforcement as a prerequisite for consolidation-oriented jobs.
