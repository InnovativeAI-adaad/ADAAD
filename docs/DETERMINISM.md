# Determinism Contract

ADAAD determinism ensures governance decisions and replay outcomes are reproducible for the same approved inputs.

## Replay contract

Replay compares current execution artifacts against canonical mutation and governance evidence for a target epoch.

A replay pass requires:
- identical policy-relevant inputs,
- identical governance constraints,
- deterministic runtime profile compliance,
- matching contract hashes for covered state.

## Hash boundaries

Hash normalization in `app.simulation_utils.stable_hash` coerces dictionary keys to typed string markers (for example `int:1` and `str:1`) before serialization so mixed key types remain replay-stable without relying on runtime key comparisons.

Deterministic boundaries include (at minimum):
- mutation manifest and governance payload hashes,
- replay attestation contract fields,
- lineage anchors and parent references,
- release evidence bundle integrity artifacts.

## What invalidates replay

Replay is invalidated when any covered deterministic input diverges, including:
- governance policy/constitution version drift,
- mutation manifest mismatch,
- lineage hash-chain mismatch,
- runtime profile lock mismatch,
- evidence bundle tampering.

## Mutation state inclusion/exclusion

### Included (governance-significant)
- mutation intent and manifest fields,
- policy decision artifacts,
- lineage/evidence references,
- replay attestation payloads.
- replay attestation payloads include `fitness_weight_snapshot_hash` bound to epoch metadata.

### Excluded (non-governance runtime noise)
- non-deterministic telemetry fields not covered by replay contract,
- non-authoritative local environment metadata outside lock boundaries.

## Replay version-policy validation

`runtime.evolution.replay.ReplayVersionValidator` enforces three deterministic policy modes for replayed scoring payloads:
- `strict`: requires both normalized version and payload value equality.
- `audit`: records version/value divergence metadata but does not hard-fail replay.
- `migration`: attempts historical rescoring via `runtime.evolution.scoring_algorithm_<version_tag>` and tolerates missing historical modules by recording divergence metadata instead of hard failure.

Before any version or value comparison, ephemeral runtime fields (for example `timestamp`/`ts`) are stripped so governance invariants are evaluated only on deterministic payload content.

Validator report contract includes deterministic top-level fields: `mode`, `ok`, `decision`, and `details` (with explicit missing-required field reporting for fail-closed behavior).


## Replay provenance fields (required)

Replay proof artifacts and sandbox evidence must include these provenance fields under `replay_environment_fingerprint`, and replay verification treats each as fail-closed:

- `runtime_version`
- `runtime_toolchain_fingerprint`
- `dependency_lock_digest`
- `env_whitelist_digest`
- `container_profile_digest`
- `filesystem_snapshot_digest`
- `filesystem_baseline_digest`
- `seed_lineage`

Accepted shape is enforced by `schemas/replay_attestation.v1.json`, and verification additionally checks that `replay_environment_fingerprint_hash` matches the canonical hash of the fingerprint object before signature validation proceeds.

## Divergence detection

Divergence is detected by contract-level hash and schema validation against the recorded baseline, then surfaced as a fail-closed governance outcome.

## Formal guarantees vs non-guarantees

### Guarantees
- Replay mismatch prevents governed execution.
- Covered governance decisions are reproducible under contract constraints.
- Evidence and lineage artifacts are integrity-checked.

### Non-guarantees
- Determinism does not imply semantic perfection of a mutation.
- Determinism does not replace required human review policies.
- Determinism scope is limited to declared contract boundaries.

## Determinism provider enforcement

`runtime.governance.foundation.determinism.default_provider()` now enforces strict replay semantics:

- `ADAAD_FORCE_DETERMINISTIC_PROVIDER=1` always selects `SeededDeterminismProvider`.
- `ADAAD_REPLAY_MODE=strict` also selects `SeededDeterminismProvider`, but only when `ADAAD_DETERMINISTIC_SEED` is set.
- Missing `ADAAD_DETERMINISTIC_SEED` in strict replay mode is a hard failure (`RuntimeError`) so replay does not silently degrade to live entropy.

`runtime.evolution.agm_event.create_event_envelope()` enforces `require_replay_safe_provider(...)` before any ID/timestamp generation so strict replay cannot emit non-deterministic ledger evidence.

`runtime.evolution.population_manager.PopulationManager` default RNG initialization now follows the same deterministic seed path by deriving its default PRNG seed from `ADAAD_DETERMINISTIC_SEED` and falling back to `"adaad"` when unset/blank. Caller-injected `rng` instances and `set_seed()` remain supported for compatibility.

`runtime.autonomy.agent_bandit_selector.AgentBanditSelector` Thompson-mode RNG contract is deterministic by default: when no constructor `rng` is provided, `recommend(epoch_id=...)` derives a per-call RNG from `epoch_id` and produces reproducible recommendations for identical arm state + epoch. If constructor `rng` is supplied, that injected RNG is used directly (caller-owned stream).

Event envelope validation now requires:

- `event_id` to match 32 lowercase hex chars (`^[0-9a-f]{32}$`).
- `emitted_at` to match `YYYY-MM-DDTHH:MM:SSZ` and parse successfully.
