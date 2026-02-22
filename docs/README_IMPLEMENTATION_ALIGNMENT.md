# ADAAD Implementation ↔ Documentation Alignment

**Authoritative version and posture:** `0.65.x` (latest tagged release: `0.65.0`), **Experimental / pre-1.0**. Governance/replay controls are validated in-tree; mutation autonomy and sovereignty federation remain staged.

This document cross-references `README.md` operational claims with concrete implementation modules and tests.

## Governance Philosophy Alignment

README governance principles are implemented via:

- **Determinism controls**: `runtime/evolution/entropy_discipline.py`
  - `deterministic_context(...)`
  - `deterministic_id(...)`
  - `deterministic_token(...)`
  - `deterministic_token_with_budget(...)`
- **Replay enforcement and fail-closed semantics**: `runtime/evolution/replay_mode.py` and `runtime/evolution/runtime.py`
  - `ReplayMode.fail_closed`
  - `ReplayMode.should_verify`
  - `EvolutionRuntime.replay_preflight(...)`
- **Tiered safety posture**: `runtime/recovery/tier_manager.py`
  - `RecoveryTierLevel`
  - `RecoveryPolicy.for_tier(...)`
  - `TierManager.evaluate_tier(...)`

## Replay Contract Alignment

README replay contract (`off`, `audit`, `strict`) is implemented by:

- `runtime/evolution/replay_mode.py`
  - Mode normalization (`normalize_replay_mode`)
  - CLI parsing helper (`parse_replay_args`)
- `runtime/evolution/runtime.py`
  - `replay_preflight(...)` returning:
    - `mode`
    - `verify_target`
    - `has_divergence`
    - `decision`
    - `results`
- Integration replay parity harness: `tests/determinism/test_replay_runtime_harness.py`
  - Calls `EvolutionRuntime.verify_epoch(...)`, `EvolutionRuntime.replay_preflight(...)`, and `ReplayEngine.replay_epoch(...)` directly
  - Verifies canonical parity against ledger epoch digests and `ReplayVerificationEvent` payload fields

## Recovery Tier Ladder Alignment

README ladder (`none`, `advisory`, `conservative`, `governance`, `critical`) is implemented by:

- `runtime/recovery/tier_manager.py`
  - Tier enum and ordering semantics
  - Policy mapping (mutation rate, approval requirements, fail-close behavior)
  - Escalation triggers (ledger errors, governance violations, mutation failures, anomalies)

## Snapshot / Recovery Alignment

Snapshot and restore flows described in docs are implemented by:

- `runtime/recovery/ledger_guardian.py`
  - `SnapshotManager.create_snapshot(...)` (single-file and lineage+journal signatures)
  - `SnapshotManager.list_snapshots()`
  - `SnapshotManager.get_latest_snapshot()`
  - `SnapshotManager.restore_snapshot(...)`
  - `AutoRecoveryHook` integrity failure handlers and `attempt_recovery(...)`

## Mutation Lifecycle Alignment

README mutation lifecycle concepts map to:

- **Discovery + staging**: `app/dream_mode.py`
- **Mutation ID determinism**: `app/mutation_executor.py`
- **Epoch lifecycle + digest tracking**: `runtime/evolution/epoch.py`, `runtime/evolution/runtime.py`
- **Promotion transition + events**: `runtime/evolution/promotion_state_machine.py`, `runtime/evolution/promotion_events.py`, `runtime/evolution/promotion_policy.py`, `runtime/evolution/simulation_runner.py`
- **Fitness scoring support**: `runtime/evolution/fitness.py`, `runtime/fitness_pipeline.py`, `runtime/evolution/scoring_algorithm.py`, `runtime/evolution/scoring_validator.py`, `runtime/evolution/scoring_ledger.py`
- **Lineage digest verification**: `runtime/evolution/lineage_v2.py`, `runtime/evolution/replay.py`
- **Null-safe governance accessors for mutable logs/state**: `runtime/governance/foundation/safe_access.py`, consumed in `app/beast_mode_loop.py`, `runtime/evolution/checkpoint_registry.py`, and audit/entropy tools under `tools/`.

## Validation Coverage

The following tests validate alignment-critical behavior:

- `tests/test_orchestrator_replay_mode.py`
- `tests/test_entropy_discipline_replay.py`
- `tests/determinism/test_replay_equivalence.py`
- `tests/determinism/test_replay_runtime_harness.py`
- `tests/recovery/test_tier_manager.py`
- `tests/governance/test_ledger_guardian.py`
- `tests/test_evolution_infrastructure.py`
- `tests/test_promotion_events.py`
- `tests/test_promotion_policy.py`
- `tests/determinism/test_scoring_algorithm_determinism.py`
- `tests/test_scoring_validator.py`
- `tests/test_scoring_ledger.py`
- `tests/test_mutation_guard.py`
- `tests/evolution/test_checkpoint_registry.py`
- `tests/stability/test_null_guards.py`
- `tests/evolution/test_entropy_policy.py`
- `tests/sandbox/test_sandbox_evidence.py`
- `tests/sandbox/test_sandbox_policy_enforcement.py`
- `tests/sandbox/test_sandbox_replay.py`
- `tests/sandbox/test_sandbox_executor.py`

## Current Validation Status

Run the full suite:

```bash
pytest -q
```

Expected status in this repository branch: all tests passing (with one known collection warning from `runtime/test_sandbox.py`).

- Governance schema versioning policy: `docs/governance/schema_versioning_and_migration.md`


## Sovereignty Requirements: Implemented vs Planned

| Requirement | Evidence in repository | Status | Validation posture |
|---|---|---|---|
| Deterministic substrate | `runtime.governance.foundation.{canonical,hashing,clock,determinism}` plus replay/determinism tests in `tests/determinism/*` | Implemented | Validated guarantee for governance/replay execution paths |
| Sandbox hardening depth | Sandbox policy + enforcement + isolation/preflight primitives in `runtime/sandbox/*` and tests in `tests/sandbox/test_sandbox_*` | Partially implemented | Enhanced deterministic fail-closed baseline validated; kernel/container hardening depth remains roadmap |
| Replay proofs | Replay preflight/runtime harnesses in `runtime/evolution/*`, attestation builder `runtime/evolution/replay_attestation.py`, and determinism tests in `tests/determinism/test_replay_*` | Implemented baseline | Deterministic replay verification + signed attestations validated in-tree; external trust-root hardening remains roadmap |
| Federation | Deterministic federation coordination primitives + handshake envelope serializers in `runtime/governance/federation/*`, schemas `schemas/federation_handshake_*.v1.json`, and tests in `tests/governance/test_federation_coordination.py` + `tests/governance/test_federation_protocol_contract.py` | Implemented baseline | Coordination/protocol contract behavior validated in-tree; distributed transport hardening remains roadmap |

## Phase 2 Migration Checklist

- Treat `tools/lint_determinism.py` as the canonical migration gate for governance/evolution determinism hardening.
- Phase 2 migration completion requires a clean determinism lint run with no forbidden nondeterministic filesystem API usage in `runtime/governance/` and `runtime/evolution/`.

## PR Milestone Reconciliation (PR-1 .. PR-6)

| Milestone | Status in docs | Reconciled repository posture |
|---|---|---|
| PR-1 | Complete | Keep as complete (scoring + deterministic ledger/test claims present and aligned) |
| PR-2 | Open | Keep as planned/open (no validated completion claim retained) |
| PR-3 | In progress | Partial implementation present (checkpoint + entropy policy primitives) |
| PR-4 | In progress | Partial implementation present (promotion policy/state transitions) |
| PR-5 | Complete baseline | Keep complete for baseline hardening; additional depth remains roadmap |
| PR-6 | Planned | Federation scope remains roadmap |

## Release Notes Rule: Guarantees vs Roadmap

For `CHANGELOG.md` and release notes:

- Put only tested, branch-validated behavior under **Validated guarantees**.
- Put future work and unverified posture claims under **Roadmap**.
- Do not label planned federation or deep hardening items as production guarantees until explicit validation artifacts/tests are present.


- Fail-closed recovery runbook: `docs/governance/fail_closed_recovery_runbook.md`


## Architecture contract and boundary enforcement

- Canonical platform entrypoint is `app/main.py`; legacy adapter paths are documented as adapter-only in app/runtime READMEs.
- Layer ownership and forbidden cross-layer imports are defined in `docs/ARCHITECTURE_CONTRACT.md`.
- CI enforces import boundaries via `python tools/lint_import_paths.py` plus `tests/test_lint_import_paths.py` guard tests, including relative-import boundary checks.
