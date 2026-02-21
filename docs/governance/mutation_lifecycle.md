# Mutation Lifecycle Specification

## Canonical state chain (no implicit transitions)

The lifecycle is strictly:

`proposed -> staged -> certified -> executing -> completed -> pruned`

Only the transitions listed below are legal. Any other transition MUST be rejected and recorded as a failure/rejection event.

## Transition contract

### `proposed -> staged`
- **Allowed predecessor states**: `proposed` only.
- **Required guard checks**:
  - Cryovant signature validity gate: valid verified signature OR `cryovant-dev-*` when trust mode is `dev`.
  - Founder’s Law invariant gate: runtime invariant suite must pass.
  - Fitness threshold gate: not applicable.
  - Trust-mode compatibility gate: trust mode must be one of `dev|prod`.
- **Required side effects**:
  - Ledger event: `mutation_lifecycle_transition`.
  - Ledger payload schema:
    - `mutation_id`, `agent_id`, `epoch_id`
    - `from_state`, `to_state`
    - `trust_mode`
    - `guard_report` (contains all gate outputs)
    - `cert_refs`, `fitness_score`, `fitness_threshold`, `stage_timestamps`, `metadata`, `ts`
  - Journal append record: append `type=mutation_lifecycle_transition` entry using hash-linked `prev_hash` chain.
  - Failure/rejection event on guard failure: `mutation_lifecycle_rejected` with same payload shape and failing `guard_report`.

### `staged -> certified`
- **Allowed predecessor states**: `staged` only.
- **Required guard checks**:
  - Cryovant signature validity gate.
  - Founder’s Law invariant gate.
  - Fitness threshold gate: not applicable.
  - Trust-mode compatibility gate: `dev|prod`.
  - Certificate reference gate: certification refs must be present.
- **Required side effects**:
  - Ledger event: `mutation_lifecycle_transition` with payload schema above.
  - Journal append record: hash-linked append.
  - Failure/rejection event: `mutation_lifecycle_rejected`.

### `certified -> executing`
- **Allowed predecessor states**: `certified` only.
- **Required guard checks**:
  - Cryovant signature validity gate.
  - Founder’s Law invariant gate.
  - Fitness threshold gate: required (`fitness_score >= fitness_threshold`).
  - Trust-mode compatibility gate: `dev|prod`.
  - Certificate reference gate: required.
- **Required side effects**:
  - Ledger event: `mutation_lifecycle_transition` with payload schema above.
  - Journal append record: hash-linked append.
  - Failure/rejection event: `mutation_lifecycle_rejected`.

### `executing -> completed`
- **Allowed predecessor states**: `executing` only.
- **Required guard checks**:
  - Cryovant signature validity gate.
  - Founder’s Law invariant gate.
  - Fitness threshold gate: not applicable.
  - Trust-mode compatibility gate: `dev|prod`.
  - Certificate reference gate: required.
- **Required side effects**:
  - Ledger event: `mutation_lifecycle_transition` with payload schema above.
  - Journal append record: hash-linked append.
  - Failure/rejection event: `mutation_lifecycle_rejected`.

### `completed -> pruned`
- **Allowed predecessor states**: `completed` only.
- **Required guard checks**:
  - Cryovant signature validity gate.
  - Founder’s Law invariant gate.
  - Fitness threshold gate: not applicable.
  - Trust-mode compatibility gate: `dev|prod`.
- **Required side effects**:
  - Ledger event: `mutation_lifecycle_transition` with payload schema above.
  - Journal append record: hash-linked append.
  - Failure/rejection event: `mutation_lifecycle_rejected`.

## Runtime enforcement requirements

- Transition enforcement is centralized in `runtime/mutation_lifecycle.py::transition(...)`.
- Runtime callers (including mutation execution flow) must invoke this function and treat undeclared transitions as hard rejections.
- No fallback or inferred predecessor transitions are permitted.


## Canonical module paths

- Deterministic foundation helpers: `runtime.governance.foundation.canonical`, `runtime.governance.foundation.hashing`, and `runtime.governance.foundation.clock`.
- Evolution promotion and checkpoint helpers: `runtime.evolution.promotion_state_machine`, `runtime.evolution.scoring`, and `runtime.evolution.checkpoint`.
- Mutation execution emits deterministic `PromotionEvent` records through `runtime.evolution.promotion_events`; policy rejection is fail-closed and does not emit invalid self-transitions.
- Mutation execution also applies deterministic entropy ceiling policy gates before promotion activation.
- Mutation execution enforces sandbox manifest/policy validation and emits hash-stable sandbox evidence records for replay/audit.
- Backward-compat imports under `governance.*` are adapters only; runtime code should import from `runtime.*`.


## Governance policy artifact lifecycle (new)

- Policy artifacts are now envelope documents (`governance_policy_artifact.v1`) containing:
  - `payload` (`governance_policy_v1` policy body)
  - `signer` metadata (`key_id`, `algorithm`)
  - `signature`
  - `previous_artifact_hash`
  - `effective_epoch`
- Policy consumers must fail closed on envelope validation or signature verification failure.
- Policy lifecycle states are deterministic and linear:
  - `authoring -> review-approved -> signed -> deployed`
- Every successful policy lifecycle transition must include a transition proof and is appended to `security/ledger` as immutable `policy_lifecycle_transition` journal events.

## Import-path compliance operational follow-ups

- CI job `import-path-compliance` must be configured as a **required status check** in repository branch protection to guarantee merge blocking when the lint fails.
- ✅ `tools/lint_import_paths.py` now includes a governance implementation-detection pass that flags non-re-export implementation code added under `governance/` while preserving adapter-layer import allowlisting for compatibility shims.

