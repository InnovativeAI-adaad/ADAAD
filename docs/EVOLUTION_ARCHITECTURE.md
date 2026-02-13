# Evolution Architecture Spec

## Concepts
- **EvolutionRuntime**: constitutional coordinator for epoch lifecycle, governance decisions, lineage digesting, and replay verification.
- **Active epoch state**: persisted at `runtime/evolution/state/current_epoch.json` and treated as the operational source of truth for epoch identity and counters.
- **Lineage**: append-only hash-linked `security/ledger/lineage_v2.jsonl` stream (replay/governance source of truth).
- **Journal projection**: `security/ledger/cryovant_journal.jsonl` is a projection derived from lineage-v2 events.
- **Replay legitimacy**: replay digest must match expected epoch digest checkpoints; mismatches trigger fail-closed.

## Active Epoch State Schema
```json
{
  "epoch_id": "epoch-20260210T140000Z-abc123",
  "start_ts": "2026-02-10T14:00:00Z",
  "mutation_count": 12,
  "metadata": {},
  "governor_version": "3.0.0"
}
```

## Invariants
1. Epoch digest authority is ledger-derived (`EpochCheckpointEvent`), not state-file stored.
2. Every mutation executes inside an active started epoch (`EpochStartEvent` exists and `EpochEndEvent` does not).
3. Epoch transitions emit typed events plus `EpochCheckpointEvent` snapshots.
4. Replay verification emits `ReplayVerificationEvent` with `epoch_digest`, `replay_digest`, and `replay_passed`.
5. Replay divergence forces governor fail-closed and blocks mutation execution until human recovery.
6. Certificates are issued pre-execution and explicitly activated/deactivated after post-mutation tests.

## Governance Policies
### Authority vs impact matrix
- `low-impact`: max impact `0.20`
- `governor-review`: max impact `0.50`
- `high-impact`: max impact `1.00`

### Signature authority
`MutationExecutor` does not perform independent signature checks. Signature authority is centralized in `EvolutionGovernor.validate_bundle`.

### Bundle ID ownership
`MutationRequest.bundle_id` is treated as a proposal hint. Governor certificate stores `bundle_id` and `bundle_id_source` (`request`/`governor`).

### Strategy anchoring
Certificates include `strategy_snapshot` and `strategy_snapshot_hash`, and cumulative bundle digesting includes those fields.

## Runtime Hooks
- `boot()`
- `before_mutation_cycle()`
- `after_mutation_cycle(result)`
- `verify_epoch(epoch_id)`
- `verify_all_epochs()`
- `before_epoch_rotation(reason)`
- `after_epoch_rotation(reason)`

## Rotation Defaults
- `max_mutations = 50`
- `max_duration_minutes = 30`
- force-end when replay divergence occurs

## Interfaces
- `runtime.evolution.runtime.EvolutionRuntime`
- `runtime.evolution.epoch.EpochManager`
- `runtime.evolution.governor.EvolutionGovernor`
- `runtime.evolution.replay.ReplayEngine`
- `runtime.evolution.lineage_v2.LineageLedgerV2.compute_epoch_digest`
- `runtime.evolution.lineage_v2.LineageLedgerV2.compute_cumulative_epoch_digest`


## Constitutional Invariants
1. LineageLedgerV2 is the sole source of evolutionary truth.
2. All epoch digests are cumulative chained hashes (`sha256(previous + bundle_digest)`).
3. Replay checks must match lineage cumulative digest exactly.
4. Authority matrix is declarative and governor-enforced.
5. Journal is projection-only and never an authority source.
6. Fail-closed recovery requires explicit recovery tier events.
