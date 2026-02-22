# SPDX-License-Identifier: Apache-2.0
"""Deterministic federation coordination primitives for governance and replay."""

from runtime.governance.federation.coordination import (
    DECISION_CLASS_CONFLICT,
    DECISION_CLASS_CONSENSUS,
    DECISION_CLASS_LOCAL_OVERRIDE,
    DECISION_CLASS_QUORUM,
    DECISION_CLASS_REJECTED,
    POLICY_PRECEDENCE_BOTH,
    POLICY_PRECEDENCE_FEDERATED,
    POLICY_PRECEDENCE_LOCAL,
    FederationDecision,
    FederationPolicyExchange,
    FederationVote,
    evaluate_federation_decision,
    persist_federation_decision,
    resolve_governance_precedence,
)
from runtime.governance.federation.protocol import (
    FederationProtocolValidationError,
    decode_handshake_request_envelope,
    decode_handshake_response_envelope,
    encode_handshake_request_envelope,
    encode_handshake_response_envelope,
)

__all__ = [
    "DECISION_CLASS_CONFLICT",
    "DECISION_CLASS_CONSENSUS",
    "DECISION_CLASS_LOCAL_OVERRIDE",
    "DECISION_CLASS_QUORUM",
    "DECISION_CLASS_REJECTED",
    "POLICY_PRECEDENCE_BOTH",
    "POLICY_PRECEDENCE_FEDERATED",
    "POLICY_PRECEDENCE_LOCAL",
    "FederationDecision",
    "FederationPolicyExchange",
    "FederationVote",
    "evaluate_federation_decision",
    "persist_federation_decision",
    "resolve_governance_precedence",
    "FederationProtocolValidationError",
    "decode_handshake_request_envelope",
    "decode_handshake_response_envelope",
    "encode_handshake_request_envelope",
    "encode_handshake_response_envelope",
]
