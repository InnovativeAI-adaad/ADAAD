# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from runtime.governance.federation import (
    DECISION_CLASS_CONFLICT,
    DECISION_CLASS_QUORUM,
    FederationDecision,
    FederationPolicyExchange,
    FederationProtocolValidationError,
    FederationVote,
    decode_handshake_request_envelope,
    decode_handshake_response_envelope,
    encode_handshake_request_envelope,
    encode_handshake_response_envelope,
    evaluate_federation_decision,
)


def _exchange() -> FederationPolicyExchange:
    return FederationPolicyExchange(
        local_peer_id="node-a",
        local_policy_version="2.0.0",
        local_manifest_digest="sha256:mlocal",
        peer_versions={"node-b": "2.1.0", "node-c": "2.1.0"},
        local_certificate={"issuer": "root-a", "serial": "1001"},
        peer_certificates={
            "node-b": {"issuer": "root-b", "serial": "2001"},
            "node-c": {"issuer": "root-c", "serial": "3001"},
        },
    )


def _sig() -> dict[str, str]:
    return {"algorithm": "ed25519", "key_id": "node-a-key", "value": "sig"}


def test_version_negotiation_round_trip_envelope_contract() -> None:
    exchange = _exchange()
    votes = [
        FederationVote(peer_id="node-c", policy_version="2.1.0", manifest_digest="sha256:mc", decision="accept"),
        FederationVote(peer_id="node-b", policy_version="2.1.0", manifest_digest="sha256:mb", decision="accept"),
    ]

    request = encode_handshake_request_envelope(
        message_id="msg-1",
        exchange_id="ex-1",
        signature=_sig(),
        exchange=exchange,
        votes=votes,
        phase="compatibility_decision",
        retry_counter=0,
        retry_token="tkn-1",
    )
    decoded_exchange, decoded_votes, metadata = decode_handshake_request_envelope(request)

    assert decoded_exchange.exchange_digest() == exchange.exchange_digest()
    assert [vote.peer_id for vote in decoded_votes] == ["node-b", "node-c"]
    assert metadata["phase"] == "compatibility_decision"


def test_idempotent_retry_metadata_preserved_across_response_round_trip() -> None:
    decision = FederationDecision(
        decision_class=DECISION_CLASS_QUORUM,
        selected_policy_version="2.1.0",
        peer_ids=["node-a", "node-b", "node-c"],
        manifest_digests={"node-a": "sha256:ma", "node-b": "sha256:mb", "node-c": "sha256:mc"},
        reconciliation_actions=["stage_majority_policy"],
        quorum_size=2,
        vote_digest="sha256:" + "a" * 64,
    )

    response = encode_handshake_response_envelope(
        message_id="msg-2",
        exchange_id="ex-2",
        signature=_sig(),
        decision=decision,
        retry_counter=2,
        retry_token="retry-2",
    )
    decoded, metadata = decode_handshake_response_envelope(response)

    assert decoded == decision
    assert metadata["phase"] == "bind"
    assert metadata["retry_counter"] == 2
    assert metadata["retry_token"] == "retry-2"


def test_deterministic_conflict_resolution_is_stable_across_vote_ordering() -> None:
    exchange = _exchange()
    votes_a = [
        FederationVote(peer_id="node-b", policy_version="2.0.0", manifest_digest="sha256:mb", decision="accept"),
        FederationVote(peer_id="node-c", policy_version="2.1.0", manifest_digest="sha256:mc", decision="accept"),
    ]
    votes_b = list(reversed(votes_a))

    decision_a = evaluate_federation_decision(exchange, votes_a, quorum_size=3)
    decision_b = evaluate_federation_decision(exchange, votes_b, quorum_size=3)

    assert decision_a.decision_class == DECISION_CLASS_CONFLICT
    assert decision_b.decision_class == DECISION_CLASS_CONFLICT
    assert decision_a.vote_digest == decision_b.vote_digest


def test_schema_validation_rejects_malformed_payload() -> None:
    exchange = _exchange()
    request = encode_handshake_request_envelope(
        message_id="msg-3",
        exchange_id="ex-3",
        signature=_sig(),
        exchange=exchange,
        votes=[],
        phase="init",
    )
    request["payload"]["local_manifest_digest"] = "invalid-digest"

    try:
        decode_handshake_request_envelope(request)
    except FederationProtocolValidationError as exc:
        assert "pattern_mismatch" in str(exc)
    else:
        raise AssertionError("expected validation failure")
