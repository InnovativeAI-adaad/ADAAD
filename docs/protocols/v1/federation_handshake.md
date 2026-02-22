# Federation Handshake Protocol v1

## Purpose

This document defines an interoperable, deterministic federation handshake between ADAAD peers for policy/manifest negotiation. All peers MUST process this protocol in canonical order and fail closed on any schema/signature mismatch.

## Message sequence

1. **`init` request**
   - Sender transmits a `request` envelope with payload phase `init`.
   - Includes local peer identity, policy version, manifest digest, certificate metadata, and retry metadata.
2. **`manifest_exchange` request**
   - Sender transmits phase `manifest_exchange` with peer policy/version map and known certificates.
   - Votes MAY be empty at this stage.
3. **`compatibility_decision` request**
   - Sender transmits phase `compatibility_decision` including deterministic vote set.
   - Receiver computes compatibility/quorum outcome using deterministic tally rules.
4. **`bind` or `reject` response**
   - Receiver replies with `response` envelope.
   - `phase=bind` for `consensus`/`quorum` outcomes.
   - `phase=reject` for `conflict`, `rejected`, or local-override fail-closed outcomes.

## Envelope and payload requirements

### Envelope (`schemas/federation_handshake_envelope.v1.json`)

Required fields:
- `schema_id` (constant URL for envelope schema)
- `protocol` (`adaad.federation.handshake`)
- `protocol_version` (`1.0`)
- `message_id` (unique per sender)
- `exchange_id` (stable per negotiation)
- `message_type` (`request` or `response`)
- `signature`
- `payload`

### Signature requirements

`signature` MUST include:
- `algorithm`
- `key_id`
- `value`

Signers MUST sign canonical JSON of the full envelope with keys sorted, using UTF-8 and compact separators (`","`, `":"`). Verification failure maps to `error_class=invalid_signature`.

### Request payload (`schemas/federation_handshake_request.v1.json`)

Required:
- `phase`: `init`, `manifest_exchange`, `compatibility_decision`
- `local_peer_id`, `local_policy_version`, `local_manifest_digest`
- `peer_versions`, `local_certificate`, `peer_certificates`
- `votes[]` (`peer_id`, `policy_version`, `manifest_digest`, `decision`)
- `retry_counter`

Optional:
- `retry_token` for idempotent retry correlation

### Response payload (`schemas/federation_handshake_response.v1.json`)

Required:
- `phase`: `bind` or `reject`
- `decision_class`
- `selected_policy_version`
- `peer_ids`, `manifest_digests`
- `reconciliation_actions`
- `quorum_size`, `vote_digest`
- `conflict_class`, `error_class`
- `retry_counter`

Optional:
- `retry_token`

## Deterministic conflict and error classes

`conflict_class`:
- `none`
- `policy_version_split`
- `manifest_digest_mismatch`
- `signature_mismatch`
- `governance_precedence_conflict`

`error_class`:
- `none`
- `invalid_signature`
- `schema_validation_failed`
- `replay_detected`
- `quorum_unmet`

Peers MUST choose classes deterministically from payload state only; no wall-clock/network side channels are allowed.

## Replay-safe retry behavior

- Retries MUST reuse `exchange_id` and increment `retry_counter` monotonically.
- `retry_token` SHOULD be stable per original attempt so duplicate deliveries are idempotent.
- Receivers MUST treat same `(exchange_id, retry_counter, retry_token)` as replay-equivalent and return the previously computed response.
- Retries MUST NOT mutate vote ordering; votes are sorted canonically before digesting.
