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
- Operator note: acceptance is threshold-gated on base fitness; ranking order can still be determined by downstream weighted ranking signals.
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
- Lifecycle context persistence is crash-safe: state snapshots are written to a same-directory temporary file, `flush` + `fsync`ed, and atomically promoted with `Path.replace()` so readers never observe partial JSON state files.
- Persistence invariant: serialized lifecycle payload keys and JSON formatting remain stable (`ensure_ascii=False`, `indent=2`) to preserve compatibility for replay and external tooling.


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


---

## Mutation Type Extension: `roadmap_amendment` (Phase 6)

**Effective:** v3.1.0 · **Authority:** `docs/governance/ARCHITECT_SPEC_v3.1.0.md` §2–3

`roadmap_amendment` is a first-class mutation type governed identically to code mutations
with the following additional constraints that take precedence over the standard lifecycle
where noted.

### State chain for `roadmap_amendment`

```
proposed → pending_governor_review → approved | rejected
```

This is a parallel state machine to the standard lifecycle. It does NOT use `staged`,
`certified`, `executing`, `completed`, or `pruned`. These states are not valid for
`roadmap_amendment` type mutations.

| State | Entry Condition | Exit Transitions |
|---|---|---|
| `proposed` | `RoadmapAmendmentEngine.propose()` called; all 6 M6-03 gates passed | → `pending_governor_review` (immediate on creation) |
| `pending_governor_review` | Proposal ledger entry written | → `approved` (≥2 governor approvals + human sign-off token) OR `rejected` (explicit rejection) |
| `approved` | Human sign-off token validated; `GovernanceGate` approval recorded | Terminal. No further transitions. |
| `rejected` | Explicit `RoadmapAmendmentEngine.reject()` call OR `DeterminismViolation` | Terminal. No further transitions. |

### Additional blocking guards (beyond standard lifecycle)

The following guards apply to `roadmap_amendment` type and are evaluated **in addition to**
the standard Cryovant signature and Founders Law gates:

| Guard | Trigger State | Failure Mode |
|---|---|---|
| `authority_level == "governor-review"` | `proposed` | `GovernanceViolation` — proposal rejected at source |
| `len(rationale.split()) >= 10` | `proposed` | `GovernanceViolation` — rationale too short |
| `diff_score ∈ [0.0, 1.0]` | `proposed` | `GovernanceViolation` — diff score out of bounds |
| `approver_id` not already in `approvals` list | `pending_governor_review` | `GovernanceViolation` — duplicate approval rejected |
| `human_signoff_token` present and valid | `pending_governor_review → approved` | Transition blocked; remains `pending_governor_review` |
| `verify_replay()` passes | Before any ROADMAP.md write | `DeterminismViolation` — write blocked; `replay_proof_status = "fail"` in ledger |

### Ledger events (canonical — registered in `ledger_event_contract.md` §8)

All transitions emit events to the evidence ledger hash chain. Non-silent: `LedgerWriteError`
on failure halts the triggering function.

| Transition | Event Type |
|---|---|
| `proposed → pending_governor_review` | `roadmap_amendment_proposed` |
| Governor approval recorded | `roadmap_amendment_human_signoff` |
| `pending_governor_review → approved` | `roadmap_amendment_approved` |
| `pending_governor_review → rejected` | `roadmap_amendment_rejected` |
| `verify_replay()` hash mismatch | `roadmap_amendment_determinism_divergence` |
| Post-merge replay pass | `roadmap_amendment_committed` |

### `roadmap_amendment` in federated context (M6-04)

When propagated via `FederationMutationBroker.propagate_amendment()`, the destination
node receives the proposal at `proposed` state and begins a fresh lifecycle evaluation.
The source node's state (`approved` or `pending_governor_review`) is NOT inherited.
The `federation_origin` field in the proposal lineage chain records the source node
identifier for audit traceability.

**Module paths:**
- State machine: `runtime/autonomy/roadmap_amendment_engine.py`
- Ledger writes: `runtime/ledger/cryovant_journal.py`
- Federation intake: `runtime/governance/federation/mutation_broker.py` (`propagate_amendment()`)

### Phase 178 — INNOV-83 CAE execution boundary

CAE execution is constrained to the canonical governance/runtime path: `runtime/autonomy/roadmap_amendment_engine.py` (proposal/execution), `security/ledger/*` (event persistence), and existing boot/replay validation entry routes in `app/main.py` and `security/cryovant.py`. CAE must fail closed on payload schema errors, authority-level mutation, missing `human_signoff_token`, or replay divergence before approval transitions are written.
