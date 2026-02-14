# ADAAD Autonomy Enhancement Plan

## Milestone 1: Agent Roles and Behavioral Contracts
- **Success criteria**
  - Five canonical roles defined with explicit interfaces and sandbox permissions.
  - Runtime-accessible role contracts are deterministic data structures.
- **Required inputs**
  - Existing governance and mutation architecture.
  - Operational safety constraints.
- **Outputs**
  - Role contract module (`runtime/autonomy/roles.py`).
- **Constraints**
  - Preserve fail-closed behavior.
  - Python 3.10+ only.
- **Risks / mitigations**
  - Risk: role ambiguity. Mitigation: explicit IO schema and error policy per role.

## Milestone 2: Self-Validation Loop
- **Success criteria**
  - Autonomy loop logs actions and post-conditions.
  - Deterministic decision output: `self_mutate`, `hold`, or `escalate`.
- **Required inputs**
  - Agent action telemetry and post-condition callbacks.
- **Outputs**
  - Self-check loop helper (`runtime/autonomy/loop.py`).
- **Constraints**
  - No external dependencies.
- **Risks / mitigations**
  - Risk: hidden failure modes. Mitigation: structured per-check logging.

## Milestone 3: Modular Mutation Scaffolding
- **Success criteria**
  - Candidate scoring function with deterministic ranking.
  - Acceptance threshold supports pass/reject gating.
- **Required inputs**
  - Candidate features: gain, risk, complexity, coverage.
- **Outputs**
  - Scoring module (`runtime/autonomy/mutation_scaffold.py`).
- **Constraints**
  - Stable sorting for reproducibility.
- **Risks / mitigations**
  - Risk: gaming one metric. Mitigation: weighted multi-factor formula.

## Milestone 4: Metrics & Feedback Scoreboard
- **Success criteria**
  - Scoreboard exposes at least three views:
    1. agent runtime performance,
    2. mutation outcomes,
    3. sandbox validation failures.
- **Required inputs**
  - Existing metrics JSONL events.
- **Outputs**
  - Scoreboard builder (`runtime/autonomy/scoreboard.py`).
- **Constraints**
  - Read existing metrics log format without schema breakage.
- **Risks / mitigations**
  - Risk: sparse metrics in early boot. Mitigation: empty-safe aggregations.

## Milestone 5: Acceptance Validation
- **Success criteria**
  - Automated tests for role contracts, autonomy loop decisions, mutation scoring, and scoreboard views.
- **Required inputs**
  - Test harness and metrics logger.
- **Outputs**
  - Tests in `tests/test_autonomy_enhancements.py`.
- **Constraints**
  - Keep tests deterministic and isolated.
- **Risks / mitigations**
  - Risk: flaky checks from shared metrics file. Mitigation: patch metrics paths in tests.


## Implementation References
- Feature schema: `docs/AUTONOMY_FEATURE_SCHEMA.md`
- Migration guide: `docs/AUTONOMY_MIGRATION_GUIDE.md`
