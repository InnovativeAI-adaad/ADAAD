# ADAAD Implementation ↔ Documentation Alignment

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
- **Fitness scoring support**: `runtime/evolution/fitness.py`, `runtime/fitness_pipeline.py`
- **Lineage digest verification**: `runtime/evolution/lineage_v2.py`, `runtime/evolution/replay.py`

## Validation Coverage

The following tests validate alignment-critical behavior:

- `tests/test_orchestrator_replay_mode.py`
- `tests/test_entropy_discipline_replay.py`
- `tests/determinism/test_replay_equivalence.py`
- `tests/recovery/test_tier_manager.py`
- `tests/governance/test_ledger_guardian.py`
- `tests/test_evolution_infrastructure.py`

## Current Validation Status

Run the full suite:

```bash
pytest -q
```

Expected status in this repository branch: all tests passing (with one known collection warning from `runtime/test_sandbox.py`).
