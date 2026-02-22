# SPDX-License-Identifier: Apache-2.0
"""Federation handshake protocol envelopes and deterministic schema validation.

Mutation rationale:
- Federation wire payloads are encoded via a single deterministic contract so
  replay paths and cross-peer negotiation outcomes stay auditable.

Expected invariants:
- Envelope and payload canonicalization are stable for identical logical inputs.
- Validation failures are deterministic and fail closed.
- Retry metadata is preserved across round trips for idempotent replay-safe retries.
"""

from __future__ import annotations

from dataclasses import asdict
import json
import re
from typing import Any

from runtime import ROOT_DIR
from runtime.governance.deterministic_filesystem import read_file_deterministic
from runtime.governance.federation.coordination import FederationDecision, FederationPolicyExchange, FederationVote

_PROTOCOL = "adaad.federation.handshake"
_PROTOCOL_VERSION = "1.0"
_SCHEMA_BASE = "https://adaad.local/schemas"
_ENVELOPE_SCHEMA = "federation_handshake_envelope.v1.json"
_REQUEST_SCHEMA = "federation_handshake_request.v1.json"
_RESPONSE_SCHEMA = "federation_handshake_response.v1.json"


class FederationProtocolValidationError(ValueError):
    """Raised when protocol envelope or payload validation fails."""


def _schema(schema_name: str) -> dict[str, Any]:
    path = ROOT_DIR / "schemas" / schema_name
    return json.loads(read_file_deterministic(path))


def _is_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    return True


def _validate(schema: dict[str, Any], payload: Any, path: str = "$") -> list[str]:
    errors: list[str] = []
    expected_type = schema.get("type")
    if isinstance(expected_type, str) and not _is_type(payload, expected_type):
        return [f"{path}:expected_{expected_type}"]

    if "const" in schema and payload != schema["const"]:
        errors.append(f"{path}:const_mismatch")

    enum = schema.get("enum")
    if isinstance(enum, list) and payload not in enum:
        errors.append(f"{path}:enum_mismatch")

    if isinstance(payload, str):
        minimum = schema.get("minLength")
        if isinstance(minimum, int) and len(payload) < minimum:
            errors.append(f"{path}:min_length")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.match(pattern, payload) is None:
            errors.append(f"{path}:pattern_mismatch")

    if isinstance(payload, int):
        minimum = schema.get("minimum")
        if isinstance(minimum, int) and payload < minimum:
            errors.append(f"{path}:minimum")

    if isinstance(payload, dict):
        required = schema.get("required") if isinstance(schema.get("required"), list) else []
        for key in required:
            if isinstance(key, str) and key not in payload:
                errors.append(f"{path}.{key}:missing_required")

        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        additional = schema.get("additionalProperties", True)
        for key, value in payload.items():
            if key in properties and isinstance(properties[key], dict):
                errors.extend(_validate(properties[key], value, f"{path}.{key}"))
            elif additional is False:
                errors.append(f"{path}.{key}:additional_property")
            elif isinstance(additional, dict):
                errors.extend(_validate(additional, value, f"{path}.{key}"))

    if isinstance(payload, list):
        minimum_items = schema.get("minItems")
        if isinstance(minimum_items, int) and len(payload) < minimum_items:
            errors.append(f"{path}:min_items")
        item_schema = schema.get("items") if isinstance(schema.get("items"), dict) else None
        if item_schema is not None:
            for idx, item in enumerate(payload):
                errors.extend(_validate(item_schema, item, f"{path}[{idx}]"))

    return errors


def _validate_or_raise(schema_name: str, payload: dict[str, Any]) -> None:
    errors = _validate(_schema(schema_name), payload)
    if errors:
        raise FederationProtocolValidationError(";".join(sorted(errors)))


def encode_handshake_request_envelope(
    *,
    message_id: str,
    exchange_id: str,
    signature: dict[str, str],
    exchange: FederationPolicyExchange,
    votes: list[FederationVote],
    phase: str,
    retry_counter: int = 0,
    retry_token: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_id": f"{_SCHEMA_BASE}/{_REQUEST_SCHEMA}",
        "phase": phase,
        "local_peer_id": exchange.local_peer_id,
        "local_policy_version": exchange.local_policy_version,
        "local_manifest_digest": exchange.local_manifest_digest,
        "peer_versions": {key: exchange.peer_versions[key] for key in sorted(exchange.peer_versions)},
        "local_certificate": {key: exchange.local_certificate[key] for key in sorted(exchange.local_certificate)},
        "peer_certificates": {
            peer_id: {
                cert_key: exchange.peer_certificates[peer_id][cert_key]
                for cert_key in sorted(exchange.peer_certificates[peer_id])
            }
            for peer_id in sorted(exchange.peer_certificates)
        },
        "votes": sorted(
            [asdict(vote) for vote in votes],
            key=lambda item: (item["peer_id"], item["policy_version"], item["manifest_digest"], item["decision"]),
        ),
        "retry_counter": max(0, int(retry_counter)),
    }
    if retry_token:
        payload["retry_token"] = retry_token

    envelope = {
        "schema_id": f"{_SCHEMA_BASE}/{_ENVELOPE_SCHEMA}",
        "protocol": _PROTOCOL,
        "protocol_version": _PROTOCOL_VERSION,
        "message_id": message_id,
        "exchange_id": exchange_id,
        "message_type": "request",
        "signature": dict(signature),
        "payload": payload,
    }
    _validate_or_raise(_REQUEST_SCHEMA, payload)
    _validate_or_raise(_ENVELOPE_SCHEMA, envelope)
    return envelope


def decode_handshake_request_envelope(envelope: dict[str, Any]) -> tuple[FederationPolicyExchange, list[FederationVote], dict[str, Any]]:
    _validate_or_raise(_ENVELOPE_SCHEMA, envelope)
    if envelope.get("message_type") != "request":
        raise FederationProtocolValidationError("$.message_type:expected_request")
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        raise FederationProtocolValidationError("$.payload:expected_object")
    _validate_or_raise(_REQUEST_SCHEMA, payload)

    exchange = FederationPolicyExchange(
        local_peer_id=payload["local_peer_id"],
        local_policy_version=payload["local_policy_version"],
        local_manifest_digest=payload["local_manifest_digest"],
        peer_versions=dict(payload["peer_versions"]),
        local_certificate=dict(payload["local_certificate"]),
        peer_certificates={peer_id: dict(certs) for peer_id, certs in payload["peer_certificates"].items()},
    )
    votes = [
        FederationVote(
            peer_id=row["peer_id"],
            policy_version=row["policy_version"],
            manifest_digest=row["manifest_digest"],
            decision=row["decision"],
        )
        for row in payload["votes"]
    ]
    metadata = {
        "message_id": envelope["message_id"],
        "exchange_id": envelope["exchange_id"],
        "signature": dict(envelope["signature"]),
        "phase": payload["phase"],
        "retry_counter": payload["retry_counter"],
        "retry_token": payload.get("retry_token"),
    }
    return exchange, votes, metadata


def encode_handshake_response_envelope(
    *,
    message_id: str,
    exchange_id: str,
    signature: dict[str, str],
    decision: FederationDecision,
    retry_counter: int = 0,
    retry_token: str | None = None,
) -> dict[str, Any]:
    phase = "bind" if decision.decision_class in {"consensus", "quorum"} else "reject"
    conflict_class = "none"
    error_class = "none"
    if decision.decision_class == "conflict":
        conflict_class = "policy_version_split"
    if decision.decision_class == "rejected":
        error_class = "quorum_unmet"

    payload: dict[str, Any] = {
        "schema_id": f"{_SCHEMA_BASE}/{_RESPONSE_SCHEMA}",
        "phase": phase,
        "decision_class": decision.decision_class,
        "selected_policy_version": decision.selected_policy_version,
        "peer_ids": list(decision.peer_ids),
        "manifest_digests": {key: decision.manifest_digests[key] for key in sorted(decision.manifest_digests)},
        "reconciliation_actions": list(decision.reconciliation_actions),
        "quorum_size": decision.quorum_size,
        "vote_digest": decision.vote_digest,
        "conflict_class": conflict_class,
        "error_class": error_class,
        "retry_counter": max(0, int(retry_counter)),
    }
    if retry_token:
        payload["retry_token"] = retry_token

    envelope = {
        "schema_id": f"{_SCHEMA_BASE}/{_ENVELOPE_SCHEMA}",
        "protocol": _PROTOCOL,
        "protocol_version": _PROTOCOL_VERSION,
        "message_id": message_id,
        "exchange_id": exchange_id,
        "message_type": "response",
        "signature": dict(signature),
        "payload": payload,
    }
    _validate_or_raise(_RESPONSE_SCHEMA, payload)
    _validate_or_raise(_ENVELOPE_SCHEMA, envelope)
    return envelope


def decode_handshake_response_envelope(envelope: dict[str, Any]) -> tuple[FederationDecision, dict[str, Any]]:
    _validate_or_raise(_ENVELOPE_SCHEMA, envelope)
    if envelope.get("message_type") != "response":
        raise FederationProtocolValidationError("$.message_type:expected_response")
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        raise FederationProtocolValidationError("$.payload:expected_object")
    _validate_or_raise(_RESPONSE_SCHEMA, payload)

    decision = FederationDecision(
        decision_class=payload["decision_class"],
        selected_policy_version=payload["selected_policy_version"],
        peer_ids=list(payload["peer_ids"]),
        manifest_digests={key: payload["manifest_digests"][key] for key in sorted(payload["manifest_digests"])},
        reconciliation_actions=list(payload["reconciliation_actions"]),
        quorum_size=int(payload["quorum_size"]),
        vote_digest=payload["vote_digest"],
    )
    metadata = {
        "message_id": envelope["message_id"],
        "exchange_id": envelope["exchange_id"],
        "signature": dict(envelope["signature"]),
        "phase": payload["phase"],
        "conflict_class": payload["conflict_class"],
        "error_class": payload["error_class"],
        "retry_counter": payload["retry_counter"],
        "retry_token": payload.get("retry_token"),
    }
    return decision, metadata


__all__ = [
    "FederationProtocolValidationError",
    "decode_handshake_request_envelope",
    "decode_handshake_response_envelope",
    "encode_handshake_request_envelope",
    "encode_handshake_response_envelope",
]
