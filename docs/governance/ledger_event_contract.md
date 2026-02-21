# PR Lifecycle Ledger Event Contract

This document defines the contract for required governance PR lifecycle events:

- `pr_merged`
- `constitution_evaluated`
- `replay_verified`
- `promotion_policy_evaluated`
- `sandbox_preflight_passed`
- `forensic_bundle_exported`

## 1) Common envelope and required fields

Every event in the PR lifecycle stream MUST include:

- `schema_version` (`"1.0"` for this contract version)
- `event_id` (globally unique event record id)
- `event_type` (one of the required lifecycle events)
- `pr_number` (integer > 0)
- `commit_sha` (40-char lowercase git SHA)
- `idempotency_key` (deterministic `sha256:<hex>`)
- `attempt` (1-based emission attempt counter)
- `sequence` (append-only contiguous sequence number)
- `emitted_at` (RFC 3339 UTC timestamp)
- `correlation_id` (end-to-end lifecycle correlation key)
- `causation_event_id` (optional link to the direct predecessor event)
- `previous_event_digest` (hash link to previous event, `sha256:000..000` for stream start)
- `event_digest` (digest of canonical event content)
- `payload` (event-specific object)

Event-specific required payload fields are enforced in `schemas/pr_lifecycle_event.v1.json`.

## 2) Event-specific required payload fields

### `pr_merged`

Required payload fields:

- `merged_at`
- `merged_by`
- `base_branch`
- `head_branch`
- `merge_commit_sha`

### `constitution_evaluated`

Required payload fields:

- `constitution_version`
- `evaluation_result` (`pass|fail`)
- `evidence_digest`

### `replay_verified`

Required payload fields:

- `replay_run_id`
- `replay_digest`
- `verification_result` (`pass|fail`)

### `promotion_policy_evaluated`

Required payload fields:

- `policy_version`
- `evaluation_result` (`allow|deny`)
- `decision_id`

### `sandbox_preflight_passed`

Required payload fields:

- `preflight_profile`
- `sandbox_policy_hash`
- `result` (must be `pass`)

### `forensic_bundle_exported`

Required payload fields:

- `bundle_uri`
- `bundle_digest`
- `exported_at`

## 3) Schema versioning and migration policy

- `schema_version` is mandatory for each event.
- Contract follows semantic versioning (`MAJOR.MINOR`).
- Backward-compatible additions (optional fields, new non-required payload fields) increment `MINOR`.
- Breaking changes (required field removals/renames/type changes) increment `MAJOR`.
- Readers MUST accept all versions with the same `MAJOR` and reject mismatched `MAJOR` values.
- Migration policy is append-only:
  - Existing stored events are immutable.
  - Upconverters may materialize read-time compatible views but MUST NOT mutate historical records.

## 4) Deterministic idempotency key derivation

Idempotency keys are deterministic and derived from canonical JSON over:

- `event_type` (lowercase)
- `pr_number`
- `commit_sha` (lowercase)

Derivation:

```text
idempotency_key = sha256_prefixed_digest(canonical_json({
  "event_type": event_type,
  "pr_number": pr_number,
  "commit_sha": commit_sha,
}))
```

This ensures retries for the same PR + commit + event type resolve to the same key.

## 5) Retry semantics and duplicate handling

Duplicate classes:

- `distinct`: idempotency keys differ → process as a new event.
- `duplicate_ack`: same idempotency key and same semantic payload → acknowledge without re-appending.
- `duplicate_conflict`: same idempotency key but different payload fields → reject and escalate.

Retry rules:

- Producers may retry transient failures with incremented `attempt`.
- Consumers MUST perform dedupe using `idempotency_key` before append.
- Duplicate ACKs MUST NOT create a second append record.
- Conflicts MUST be treated as integrity violations.

## 6) Ordering guarantees and cross-event linkage

- Stream is append-only and ordered by `sequence`.
- `sequence` MUST increase contiguously by 1.
- `previous_event_digest` MUST equal the prior event's `event_digest`.
- `event_digest` is computed from canonical event fields and payload.
- `correlation_id` links all events for a PR lifecycle.
- `causation_event_id` links direct dependencies across event boundaries.

Recommended lifecycle order:

1. `pr_merged`
2. `constitution_evaluated`
3. `replay_verified`
4. `promotion_policy_evaluated`
5. `sandbox_preflight_passed`
6. `forensic_bundle_exported`

If out-of-order emission is necessary, `causation_event_id` must preserve explicit dependency lineage.

## 7) References

- `schemas/pr_lifecycle_event.v1.json`
- `schemas/pr_lifecycle_event_stream.v1.json`
- `runtime/governance/pr_lifecycle_event_contract.py`
