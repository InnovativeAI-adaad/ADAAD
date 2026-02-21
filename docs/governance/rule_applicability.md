# Rule Applicability Specification

This document defines how constitutional rules are applied per mutation request/PR, and how PR checklists are generated from machine-readable applicability output.

## Source of truth

- Machine-readable policy: `governance/rule_applicability.yaml`
- Runtime consumer: `runtime/constitution.py`
- PR checklist generator/validator: `scripts/pr_rule_checklist.py`

## Applicability model

For each rule:

- **Scope**: directories + change types.
- **Trigger conditions**: e.g., requires targets, signature, operation count, tier.
- **Severity/fail behavior**: aligned with constitutional policy + tier overrides.
- **Required evidence/log output**: fields that must be present in verdict details.

At evaluation time, ADAAD computes an **applicability matrix** for all enabled rules and includes it in `constitutional_evaluation.payload.applicability_matrix`.

Rules that are not applicable are marked `applicable=false` and emitted as pass-through verdicts with `details.reason=rule_not_applicable`.

## PR workflow

1. Produce/evaluate constitutional output for the PR changes.
2. Generate checklist markdown from applicability output:
   - `python scripts/pr_rule_checklist.py --evaluation-json <path>`
3. Validate PR body checklist against applicability output:
   - `python scripts/pr_rule_checklist.py --evaluation-json <path> --pr-body-file <path> --validate`

This removes manual interpretation and ensures checkboxes come from the same matrix used by evaluators.
