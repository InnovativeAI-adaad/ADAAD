from __future__ import annotations

from runtime.governance.pr_lifecycle_event_contract import (
    CURRENT_PR_LIFECYCLE_SCHEMA_VERSION,
    build_event_digest,
    classify_retry,
    derive_idempotency_key,
    is_schema_version_compatible,
    validate_append_only_invariants,
)


def _base_event(*, sequence: int, previous_event_digest: str, payload: dict) -> dict:
    event = {
        "schema_version": CURRENT_PR_LIFECYCLE_SCHEMA_VERSION,
        "event_type": "replay_verified",
        "pr_number": 42,
        "commit_sha": "a" * 40,
        "idempotency_key": derive_idempotency_key(pr_number=42, commit_sha="a" * 40, event_type="replay_verified"),
        "attempt": 1,
        "sequence": sequence,
        "previous_event_digest": previous_event_digest,
        "payload": payload,
    }
    event["event_digest"] = build_event_digest(event)
    return event


def test_duplicate_emission_semantics() -> None:
    first = {
        "event_type": "replay_verified",
        "pr_number": 17,
        "commit_sha": "b" * 40,
        "idempotency_key": derive_idempotency_key(pr_number=17, commit_sha="b" * 40, event_type="replay_verified"),
        "payload": {"replay_run_id": "r1", "verification_result": "pass"},
    }
    duplicate_same = dict(first)
    duplicate_conflict = {**first, "payload": {"replay_run_id": "r1", "verification_result": "fail"}}
    distinct = {
        **first,
        "event_type": "promotion_policy_evaluated",
        "idempotency_key": derive_idempotency_key(
            pr_number=17,
            commit_sha="b" * 40,
            event_type="promotion_policy_evaluated",
        ),
    }

    assert classify_retry(first, duplicate_same) == "duplicate_ack"
    assert classify_retry(first, duplicate_conflict) == "duplicate_conflict"
    assert classify_retry(first, distinct) == "distinct"


def test_schema_version_compatibility_policy() -> None:
    assert is_schema_version_compatible("1.0")
    assert is_schema_version_compatible("1.7")
    assert not is_schema_version_compatible("2.0")


def test_append_only_invariants_detect_tampering() -> None:
    valid = [
        _base_event(
            sequence=1,
            previous_event_digest="sha256:" + ("0" * 64),
            payload={"replay_run_id": "run-1", "replay_digest": "sha256:" + ("1" * 64), "verification_result": "pass"},
        ),
        _base_event(
            sequence=2,
            previous_event_digest="",
            payload={"replay_run_id": "run-2", "replay_digest": "sha256:" + ("2" * 64), "verification_result": "pass"},
        ),
    ]

    valid[1]["previous_event_digest"] = valid[0]["event_digest"]
    valid[1]["event_digest"] = build_event_digest(valid[1])

    assert validate_append_only_invariants(valid) == []

    tampered = [dict(valid[0]), dict(valid[1])]
    tampered[1]["previous_event_digest"] = "sha256:" + ("f" * 64)

    errors = validate_append_only_invariants(tampered)
    assert "event[1]:previous_event_digest_mismatch" in errors
