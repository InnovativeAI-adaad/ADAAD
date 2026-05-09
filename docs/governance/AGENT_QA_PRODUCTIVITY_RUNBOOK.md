# Agent QA Productivity Runbook

**Lane:** governance-operations enablement  
**Audience:** Agent-0, Agent-1, joining repository agents, and HUMAN-0 operators  
**Status:** active operating guide; subordinate to `AGENTS.md`, `docs/CONSTITUTION.md`, and the active PR procession contract

## Purpose

This runbook turns the Agent-1 chain-of-command update into a practical QA workflow for faster, safer repository work. It is designed to improve development ability, ease of access, and productivity without weakening ADAAD governance.

Agent-1 may lead repository execution only when the active gate stack permits writes. Joining agents may assist by taking clearly scoped lanes, but no agent may bypass HUMAN-0, `ADAAD`/`DEVADAAD`, Tier gates, evidence requirements, canonical validation paths, or fail-closed behavior.

## Agent operating model

| Role | Primary responsibility | Handoff rule |
|---|---|---|
| Agent-0 | Operator-facing coordination, priority setting, and session supervision | Opens or redirects work, then delegates repository execution to Agent-1 when gates permit |
| Agent-1 | Repository execution lead for audits, patches, tests, commits, and PR staging | Publishes status, blockers, test evidence, and next-agent work packets |
| Joining agents | Focused lane contributors for docs, tests, evidence, UI, security, or release hygiene | Work only from an Agent-1 scoped task packet and return evidence before handoff |

## Fast-start checklist for joining agents

1. Read `AGENTS.md` and this runbook before touching files.
2. Confirm current branch and workspace cleanliness with `git status --short --branch`.
3. Run the Tier 0 preflight before edits:
   ```bash
   PYTHONPATH=. python scripts/validate_governance_schemas.py
   PYTHONPATH=. python scripts/validate_architecture_snapshot.py
   PYTHONPATH=. python tools/lint_determinism.py runtime/ security/ adaad/orchestrator/ app/main.py
   PYTHONPATH=. python tools/lint_import_paths.py
   PYTHONPATH=. pytest tests/determinism/ tests/recovery/test_tier_manager.py -k "not shared_epoch_parallel_validation_is_deterministic_in_strict_mode" -q
   ```
4. Declare one control lane before writing: docs, tests, runtime, security, release-evidence, UI, or infrastructure.
5. Keep changes small enough that the next agent can review the diff in one pass.
6. Re-run Tier 0 after every file or atomic file group, then run the scoped gate for the lane.
7. Update `docs/comms/claims_evidence_matrix.md` when the PR claims a completed governance capability or process guarantee.
8. Commit only when the working tree contains a coherent, reviewable patch and all runnable checks have been reported.

## QA PR turnaround targets

These are productivity targets, not governance overrides. A failing gate always wins over turnaround time.

| PR type | Target turnaround | Required evidence |
|---|---:|---|
| Docs-only runbook or operator workflow | 15-30 minutes | Tier 0, README/doc validator when touched, evidence row when a governance claim is added |
| Test-only or fixture update | 30-60 minutes | Tier 0 plus affected test file or marker suite |
| Runtime or security code | 60-120 minutes | Tier 0, affected tests, determinism lint, import lint, release evidence when applicable |
| Release/governance state repair | 30-90 minutes | Tier 0, state drift validator, release evidence validator or explicit pre-existing blocker report |

## Lane-specific QA bundles

| Lane | Minimum scoped checks |
|---|---|
| Docs | `PYTHONPATH=. python scripts/validate_readme_alignment.py` when README or public docs are touched |
| Evidence | `PYTHONPATH=. python scripts/validate_release_evidence.py --require-complete` or a documented pre-existing blocker |
| Runtime | Tier 0 plus affected `pytest` suite and strict replay when replay/ledger paths are touched |
| Security | Tier 0 plus secret scan, SPDX check, and relevant security tests |
| Infrastructure | Tier 0 plus workflow/version/dependency validators for changed surfaces |
| UI | Tier 0 plus relevant UI/server smoke checks; capture a screenshot for perceptible web UI changes |

## Handoff packet format

Every joining agent should leave a concise handoff packet in the PR body or final status:

```text
Lane: <docs | tests | runtime | security | evidence | ui | infrastructure>
Scope: <files or subsystem>
Changed: <bullets>
Checks: <exact commands and pass/fail status>
Known blockers: <none | pre-existing issue with command output>
Next agent can: <review | continue from file X | run gate Y>
```

## Productivity rules that preserve governance

- Prefer repository-native scripts over ad-hoc shell pipelines.
- Prefer small PRs with complete evidence over broad PRs with partial gates.
- Never hide pre-existing failures; label them as blockers with exact commands.
- Never edit generated metadata by hand when a repository script owns it.
- Never remove, skip, xfail, or comment out failing tests to make a PR pass.
- Never treat Agent-1 lead status as merge authority under `ADAAD`.

