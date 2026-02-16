# SPDX-License-Identifier: Apache-2.0
"""Deterministic loader/validator for the governance policy artifact."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.governance.deterministic_filesystem import read_file_deterministic
from runtime.governance.foundation import sha256_prefixed_digest
from security import cryovant

DEFAULT_GOVERNANCE_POLICY_PATH = Path(__file__).resolve().parents[2] / "governance" / "governance_policy_v1.json"
POLICY_ARTIFACT_SCHEMA_VERSION = "governance_policy_artifact.v1"
POLICY_PAYLOAD_SCHEMA_VERSION = "governance_policy_v1"


class GovernancePolicyError(ValueError):
    """Raised when a governance policy artifact is missing or invalid."""


@dataclass(frozen=True)
class GovernanceThresholds:
    determinism_pass: float
    determinism_warn: float


@dataclass(frozen=True)
class GovernanceModelMetadata:
    name: str
    version: str


@dataclass(frozen=True)
class GovernanceSignerMetadata:
    key_id: str
    algorithm: str


@dataclass(frozen=True)
class GovernancePolicy:
    schema_version: str
    model: GovernanceModelMetadata
    determinism_window: int
    mutation_rate_window_sec: int
    thresholds: GovernanceThresholds
    fingerprint: str
    signer: GovernanceSignerMetadata = GovernanceSignerMetadata(key_id="unknown", algorithm="unknown")
    signature: str = ""
    previous_artifact_hash: str = "sha256:" + ("0" * 64)
    effective_epoch: int = 0


@dataclass(frozen=True)
class GovernancePolicyArtifactEnvelope:
    schema_version: str
    payload: dict[str, Any]
    signer: GovernanceSignerMetadata
    signature: str
    previous_artifact_hash: str
    effective_epoch: int


def _require_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GovernancePolicyError(f"{field_name} must be an object")
    return value


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GovernancePolicyError(f"{field_name} must be a non-empty string")
    return value


def _require_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GovernancePolicyError(f"{field_name} must be an integer")
    return value


def _require_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GovernancePolicyError(f"{field_name} must be a number")
    return float(value)


def _require_hash(value: Any, field_name: str) -> str:
    digest = _require_str(value, field_name)
    if not digest.startswith("sha256:"):
        raise GovernancePolicyError(f"{field_name} must be prefixed sha256 hash")
    if len(digest) != len("sha256:") + 64:
        raise GovernancePolicyError(f"{field_name} must contain 64 hex chars")
    return digest


def _parse_payload(root: dict[str, Any]) -> tuple[str, GovernanceModelMetadata, GovernanceThresholds, int, int]:
    schema_version = _require_str(root.get("schema_version"), "payload.schema_version")
    if schema_version != POLICY_PAYLOAD_SCHEMA_VERSION:
        raise GovernancePolicyError(
            f"payload.schema_version must be {POLICY_PAYLOAD_SCHEMA_VERSION}, received {schema_version!r}"
        )

    model_obj = _require_mapping(root.get("model"), "payload.model")
    model = GovernanceModelMetadata(
        name=_require_str(model_obj.get("name"), "payload.model.name"),
        version=_require_str(model_obj.get("version"), "payload.model.version"),
    )

    thresholds_obj = _require_mapping(root.get("thresholds"), "payload.thresholds")
    thresholds = GovernanceThresholds(
        determinism_pass=_require_number(thresholds_obj.get("determinism_pass"), "payload.thresholds.determinism_pass"),
        determinism_warn=_require_number(thresholds_obj.get("determinism_warn"), "payload.thresholds.determinism_warn"),
    )
    if thresholds.determinism_warn > thresholds.determinism_pass:
        raise GovernancePolicyError("payload.thresholds.determinism_warn must be <= payload.thresholds.determinism_pass")

    determinism_window = _require_int(root.get("determinism_window"), "payload.determinism_window")
    mutation_rate_window_sec = _require_int(root.get("mutation_rate_window_sec"), "payload.mutation_rate_window_sec")
    if determinism_window <= 0:
        raise GovernancePolicyError("payload.determinism_window must be > 0")
    if mutation_rate_window_sec <= 0:
        raise GovernancePolicyError("payload.mutation_rate_window_sec must be > 0")
    return schema_version, model, thresholds, determinism_window, mutation_rate_window_sec


def policy_artifact_digest(envelope: GovernancePolicyArtifactEnvelope) -> str:
    """Return replay-safe deterministic digest for signed policy envelope fields."""

    digest_payload = {
        "schema_version": envelope.schema_version,
        "payload": envelope.payload,
        "signer": {"key_id": envelope.signer.key_id, "algorithm": envelope.signer.algorithm},
        "previous_artifact_hash": envelope.previous_artifact_hash,
        "effective_epoch": envelope.effective_epoch,
    }
    return sha256_prefixed_digest(digest_payload)


def _parse_envelope(artifact: dict[str, Any]) -> GovernancePolicyArtifactEnvelope:
    schema_version = _require_str(artifact.get("schema_version"), "schema_version")
    if schema_version != POLICY_ARTIFACT_SCHEMA_VERSION:
        raise GovernancePolicyError(
            f"schema_version must be {POLICY_ARTIFACT_SCHEMA_VERSION}, received {schema_version!r}"
        )
    payload_obj = _require_mapping(artifact.get("payload"), "payload")
    signer_obj = _require_mapping(artifact.get("signer"), "signer")
    signature = _require_str(artifact.get("signature"), "signature")
    previous_artifact_hash = _require_hash(artifact.get("previous_artifact_hash"), "previous_artifact_hash")
    effective_epoch = _require_int(artifact.get("effective_epoch"), "effective_epoch")

    signer = GovernanceSignerMetadata(
        key_id=_require_str(signer_obj.get("key_id"), "signer.key_id"),
        algorithm=_require_str(signer_obj.get("algorithm"), "signer.algorithm"),
    )
    if effective_epoch < 0:
        raise GovernancePolicyError("effective_epoch must be >= 0")

    envelope = GovernancePolicyArtifactEnvelope(
        schema_version=schema_version,
        payload=payload_obj,
        signer=signer,
        signature=signature,
        previous_artifact_hash=previous_artifact_hash,
        effective_epoch=effective_epoch,
    )
    signature_ok = cryovant.verify_signature(envelope.signature) or cryovant.dev_signature_allowed(envelope.signature)
    if not signature_ok and signer.algorithm == "hmac-sha256":
        signature_ok = cryovant.verify_hmac_digest_signature(
            key_id=signer.key_id,
            signed_digest=policy_artifact_digest(envelope),
            signature=envelope.signature,
            specific_env_prefix="ADAAD_POLICY_ARTIFACT_KEY_",
            generic_env_var="ADAAD_POLICY_ARTIFACT_SIGNING_KEY",
            fallback_namespace="adaad-policy-artifact-dev-secret",
        )
    if not signature_ok:
        raise GovernancePolicyError("policy signature verification failed (fail-closed)")
    return envelope


def verify_policy_artifact_chain(envelopes: list[GovernancePolicyArtifactEnvelope]) -> None:
    """Validate previous_artifact_hash links across ordered envelopes."""

    expected_prev = "sha256:" + ("0" * 64)
    for idx, envelope in enumerate(envelopes):
        if envelope.previous_artifact_hash != expected_prev:
            raise GovernancePolicyError(
                f"policy artifact hash chain mismatch at index {idx}: expected {expected_prev}, received {envelope.previous_artifact_hash}"
            )
        expected_prev = policy_artifact_digest(envelope)


def load_governance_policy(path: Path = DEFAULT_GOVERNANCE_POLICY_PATH) -> GovernancePolicy:
    if not path.exists():
        raise GovernancePolicyError(f"governance policy not found at {path}")
    try:
        artifact = json.loads(read_file_deterministic(path))
    except json.JSONDecodeError as exc:
        raise GovernancePolicyError(f"invalid JSON in governance policy: {exc}") from exc

    root = _require_mapping(artifact, "root")
    envelope = _parse_envelope(root)
    schema_version, model, thresholds, determinism_window, mutation_rate_window_sec = _parse_payload(envelope.payload)

    return GovernancePolicy(
        schema_version=schema_version,
        model=model,
        determinism_window=determinism_window,
        mutation_rate_window_sec=mutation_rate_window_sec,
        thresholds=thresholds,
        fingerprint=policy_artifact_digest(envelope),
        signer=envelope.signer,
        signature=envelope.signature,
        previous_artifact_hash=envelope.previous_artifact_hash,
        effective_epoch=envelope.effective_epoch,
    )


__all__ = [
    "DEFAULT_GOVERNANCE_POLICY_PATH",
    "GovernanceModelMetadata",
    "GovernancePolicy",
    "GovernancePolicyArtifactEnvelope",
    "GovernancePolicyError",
    "GovernanceSignerMetadata",
    "GovernanceThresholds",
    "POLICY_ARTIFACT_SCHEMA_VERSION",
    "POLICY_PAYLOAD_SCHEMA_VERSION",
    "load_governance_policy",
    "policy_artifact_digest",
    "verify_policy_artifact_chain",
]
