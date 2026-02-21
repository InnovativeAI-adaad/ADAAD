# SPDX-License-Identifier: Apache-2.0
"""Contract helpers for PR lifecycle governance events."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from runtime.governance.foundation.canonical import canonical_json_bytes
from runtime.governance.foundation.hashing import ZERO_HASH, sha256_prefixed_digest

REQUIRED_PR_LIFECYCLE_EVENT_TYPES: tuple[str, ...] = (
    "pr_merged",
    "constitution_evaluated",
    "replay_verified",
    "promotion_policy_evaluated",
    "sandbox_preflight_passed",
    "forensic_bundle_exported",
)

CURRENT_PR_LIFECYCLE_SCHEMA_VERSION = "1.0"


def is_schema_version_compatible(schema_version: str) -> bool:
    """Return True when ``schema_version`` is backward compatible with current readers.

    Policy: major version changes are breaking; minor/patch changes are additive.
    """

    try:
        major, *_ = schema_version.split(".")
        current_major, *_ = CURRENT_PR_LIFECYCLE_SCHEMA_VERSION.split(".")
    except ValueError:
        return False
    return major == current_major


def derive_idempotency_key(*, pr_number: int, commit_sha: str, event_type: str) -> str:
    """Derive deterministic idempotency key for a PR lifecycle event."""

    normalized_event_type = event_type.strip().lower()
    normalized_commit_sha = commit_sha.strip().lower()
    material = {
        "event_type": normalized_event_type,
        "pr_number": int(pr_number),
        "commit_sha": normalized_commit_sha,
    }
    return sha256_prefixed_digest(canonical_json_bytes(material))


def build_event_digest(event: Mapping[str, Any]) -> str:
    """Compute deterministic digest for append-only event entries."""

    canonical_event = {
        "schema_version": event["schema_version"],
        "event_type": event["event_type"],
        "pr_number": event["pr_number"],
        "commit_sha": event["commit_sha"],
        "idempotency_key": event["idempotency_key"],
        "attempt": event["attempt"],
        "sequence": event["sequence"],
        "previous_event_digest": event["previous_event_digest"],
        "payload": event["payload"],
    }
    return sha256_prefixed_digest(canonical_json_bytes(canonical_event))


def classify_retry(existing_event: Mapping[str, Any], incoming_event: Mapping[str, Any]) -> str:
    """Classify duplicate handling for retries.

    Returns one of:
    - ``distinct``: idempotency keys differ.
    - ``duplicate_ack``: same key and semantically identical event.
    - ``duplicate_conflict``: same key but conflicting payload.
    """

    if existing_event["idempotency_key"] != incoming_event["idempotency_key"]:
        return "distinct"

    existing_material = {
        "event_type": existing_event["event_type"],
        "pr_number": existing_event["pr_number"],
        "commit_sha": existing_event["commit_sha"],
        "payload": existing_event["payload"],
    }
    incoming_material = {
        "event_type": incoming_event["event_type"],
        "pr_number": incoming_event["pr_number"],
        "commit_sha": incoming_event["commit_sha"],
        "payload": incoming_event["payload"],
    }
    return "duplicate_ack" if existing_material == incoming_material else "duplicate_conflict"


def validate_append_only_invariants(events: Sequence[Mapping[str, Any]]) -> list[str]:
    """Validate append-only ordering and hash-link invariants."""

    errors: list[str] = []
    previous_digest = ZERO_HASH
    previous_sequence = 0

    for idx, event in enumerate(events):
        sequence = int(event["sequence"])
        if sequence != previous_sequence + 1:
            errors.append(f"event[{idx}]:non_contiguous_sequence")
        if event["previous_event_digest"] != previous_digest:
            errors.append(f"event[{idx}]:previous_event_digest_mismatch")
        expected_digest = build_event_digest(event)
        if event["event_digest"] != expected_digest:
            errors.append(f"event[{idx}]:event_digest_mismatch")

        previous_sequence = sequence
        previous_digest = event["event_digest"]

    return errors


__all__ = [
    "CURRENT_PR_LIFECYCLE_SCHEMA_VERSION",
    "REQUIRED_PR_LIFECYCLE_EVENT_TYPES",
    "build_event_digest",
    "classify_retry",
    "derive_idempotency_key",
    "is_schema_version_compatible",
    "validate_append_only_invariants",
]
