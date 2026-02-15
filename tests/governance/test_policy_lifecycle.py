# SPDX-License-Identifier: Apache-2.0

import pytest

from runtime.governance.policy_lifecycle import PolicyLifecycleError, apply_transition


def _proof(*, digest: str, prev: str = "sha256:" + "0" * 64) -> dict:
    return {
        "artifact_digest": digest,
        "previous_transition_hash": prev,
        "evidence": {"approver": "operator-1", "ticket": "GOV-1"},
    }


def test_policy_lifecycle_transition_appends_immutable_event(monkeypatch) -> None:
    events = []
    monkeypatch.setattr(
        "runtime.governance.policy_lifecycle.append_tx",
        lambda tx_type, payload, tx_id=None: events.append({"tx_type": tx_type, "payload": payload, "tx_id": tx_id}),
    )
    digest = "sha256:" + "1" * 64

    transition = apply_transition(
        artifact_digest=digest,
        from_state="authoring",
        to_state="review-approved",
        proof=_proof(digest=digest),
    )

    assert transition.to_state == "review-approved"
    assert events and events[0]["tx_type"] == "policy_lifecycle_transition"
    assert events[0]["payload"]["transition_hash"] == transition.transition_hash


def test_policy_lifecycle_enforces_transition_rules(monkeypatch) -> None:
    monkeypatch.setattr("runtime.governance.policy_lifecycle.append_tx", lambda *args, **kwargs: None)
    digest = "sha256:" + "2" * 64

    with pytest.raises(PolicyLifecycleError, match="invalid transition"):
        apply_transition(
            artifact_digest=digest,
            from_state="authoring",
            to_state="signed",
            proof=_proof(digest=digest),
        )


def test_policy_lifecycle_requires_matching_proof_digest(monkeypatch) -> None:
    monkeypatch.setattr("runtime.governance.policy_lifecycle.append_tx", lambda *args, **kwargs: None)
    digest = "sha256:" + "3" * 64

    with pytest.raises(PolicyLifecycleError, match="proof.artifact_digest"):
        apply_transition(
            artifact_digest=digest,
            from_state="review-approved",
            to_state="signed",
            proof=_proof(digest="sha256:" + "4" * 64),
        )
