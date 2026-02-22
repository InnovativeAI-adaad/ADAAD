# SPDX-License-Identifier: Apache-2.0
"""Deterministic replay attestation proof bundle helpers."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

from runtime import ROOT_DIR
from runtime.constitution import CONSTITUTION_VERSION
from runtime.evolution.lineage_v2 import LineageLedgerV2
from runtime.evolution.replay import ReplayEngine
from runtime.governance.deterministic_filesystem import read_file_deterministic
from runtime.governance.foundation import ZERO_HASH, canonical_json, sha256_digest, sha256_prefixed_digest
from security import cryovant

REPLAY_PROOFS_DIR = ROOT_DIR / "security" / "ledger" / "replay_proofs"
DEFAULT_PROOF_SIGNING_ALGORITHM = "hmac-sha256"
REPLAY_ATTESTATION_SCHEMA_PATH = ROOT_DIR / "schemas" / "replay_attestation.v1.json"


def _normalize_checkpoint_event(payload: Dict[str, Any]) -> Dict[str, str]:
    return {
        "checkpoint_id": str(payload.get("checkpoint_id") or ""),
        "checkpoint_hash": str(payload.get("checkpoint_hash") or ZERO_HASH),
        "prev_checkpoint_hash": str(payload.get("prev_checkpoint_hash") or ZERO_HASH),
        "epoch_digest": str(payload.get("epoch_digest") or "sha256:0"),
        "baseline_digest": str(payload.get("baseline_digest") or "sha256:0"),
        "created_at": str(payload.get("created_at") or ""),
    }


def _json_type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def _validate_schema_subset(instance: Any, schema: Dict[str, Any], path: str = "$") -> List[str]:
    errors: List[str] = []
    expected_type = schema.get("type")
    if isinstance(expected_type, str) and _json_type_name(instance) != expected_type:
        return [f"{path}:expected_{expected_type}:got_{_json_type_name(instance)}"]

    if expected_type == "object":
        if not isinstance(instance, dict):
            return [f"{path}:not_object"]
        required = schema.get("required") or []
        for key in required:
            if key not in instance:
                errors.append(f"{path}.{key}:missing_required")
        properties = schema.get("properties") or {}
        for key, value in instance.items():
            if key in properties:
                errors.extend(_validate_schema_subset(value, properties[key], f"{path}.{key}"))
        if schema.get("additionalProperties") is False:
            extras = sorted(set(instance.keys()) - set(properties.keys()))
            for key in extras:
                errors.append(f"{path}.{key}:additional_property")

    if expected_type == "array":
        if not isinstance(instance, list):
            return [f"{path}:not_array"]
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for idx, value in enumerate(instance):
                errors.extend(_validate_schema_subset(value, item_schema, f"{path}[{idx}]"))

    if isinstance(instance, str):
        const_value = schema.get("const")
        if const_value is not None and instance != const_value:
            errors.append(f"{path}:const_mismatch")
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and len(instance) < min_length:
            errors.append(f"{path}:min_length_violation")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.fullmatch(pattern, instance) is None:
            errors.append(f"{path}:pattern_violation")

    return errors


def _parse_iso8601_utc(value: str) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


class ReplayProofBuilder:
    """Collect deterministic replay evidence and emit a signed proof bundle."""

    def __init__(
        self,
        ledger: LineageLedgerV2 | None = None,
        replay_engine: ReplayEngine | None = None,
        *,
        proofs_dir: Path | None = None,
        key_id: str | None = None,
        algorithm: str | None = None,
    ) -> None:
        self.ledger = ledger or LineageLedgerV2()
        self.replay_engine = replay_engine or ReplayEngine(self.ledger)
        self.proofs_dir = proofs_dir or REPLAY_PROOFS_DIR
        self.key_id = (key_id or os.getenv("ADAAD_REPLAY_PROOF_KEY_ID", "replay-proof-dev")).strip()
        self.algorithm = (algorithm or os.getenv("ADAAD_REPLAY_PROOF_ALGO", DEFAULT_PROOF_SIGNING_ALGORITHM)).strip()

    def _collect_checkpoint_chain(self, epoch_id: str) -> List[Dict[str, str]]:
        checkpoints: List[Dict[str, str]] = []
        for entry in self.ledger.read_epoch(epoch_id):
            if entry.get("type") != "EpochCheckpointEvent":
                continue
            payload = entry.get("payload") or {}
            if isinstance(payload, dict):
                checkpoints.append(_normalize_checkpoint_event(payload))
        checkpoints.sort(
            key=lambda item: (
                item.get("created_at", ""),
                item.get("checkpoint_id", ""),
                item.get("checkpoint_hash", ""),
            )
        )
        return checkpoints

    def _policy_hashes(self, checkpoint_chain: Iterable[Dict[str, str]], epoch_id: str) -> Dict[str, str]:
        policy_hashes = {
            "promotion_policy_hash": ZERO_HASH,
            "entropy_policy_hash": ZERO_HASH,
            "sandbox_policy_hash": ZERO_HASH,
        }
        events = self.ledger.read_epoch(epoch_id)
        for entry in events:
            if entry.get("type") != "EpochCheckpointEvent":
                continue
            payload = entry.get("payload") or {}
            if not isinstance(payload, dict):
                continue
            for field in policy_hashes:
                candidate = payload.get(field)
                if isinstance(candidate, str) and candidate:
                    policy_hashes[field] = candidate
        if not events:
            for checkpoint in checkpoint_chain:
                for field in policy_hashes:
                    candidate = checkpoint.get(field)
                    if isinstance(candidate, str) and candidate:
                        policy_hashes[field] = candidate
        return policy_hashes

    def build_bundle(self, epoch_id: str) -> Dict[str, Any]:
        replay_state = self.replay_engine.replay_epoch(epoch_id)
        ledger_state_hash = self.ledger.get_epoch_digest(epoch_id) or replay_state.get("digest") or "sha256:0"
        checkpoint_chain = self._collect_checkpoint_chain(epoch_id)
        checkpoint_hashes = [item["checkpoint_hash"] for item in checkpoint_chain]
        baseline_digest = str((checkpoint_chain[-1].get("baseline_digest") if checkpoint_chain else "") or replay_state.get("digest") or "sha256:0")
        goal_graph_path = ROOT_DIR / "runtime" / "evolution" / "goal_graph.json"
        if not goal_graph_path.exists():
            raise RuntimeError("replay_proof_goal_graph_missing")
        mutation_graph_fingerprint = "sha256:" + sha256_digest(read_file_deterministic(goal_graph_path))
        policy_hashes = self._policy_hashes(checkpoint_chain, epoch_id)
        unsigned_bundle = {
            "schema_version": "1.0",
            "epoch_id": epoch_id,
            "baseline_digest": baseline_digest,
            "ledger_state_hash": str(ledger_state_hash),
            "mutation_graph_fingerprint": mutation_graph_fingerprint,
            "constitution_version": CONSTITUTION_VERSION,
            "sandbox_policy_hash": policy_hashes.get("sandbox_policy_hash") or ZERO_HASH,
            "checkpoint_chain": checkpoint_chain,
            "checkpoint_chain_digest": sha256_prefixed_digest(checkpoint_hashes),
            "replay_digest": str(replay_state.get("digest") or "sha256:0"),
            "canonical_digest": str(replay_state.get("canonical_digest") or sha256_digest(replay_state)),
            "policy_hashes": policy_hashes,
        }
        proof_digest = sha256_prefixed_digest(unsigned_bundle)
        signed_digest = proof_digest
        signature_bundle = {
            "key_id": self.key_id,
            "algorithm": self.algorithm,
            "signed_digest": signed_digest,
            "signature": cryovant.sign_hmac_digest(
                key_id=self.key_id,
                signed_digest=signed_digest,
                specific_env_prefix="ADAAD_REPLAY_PROOF_KEY_",
                generic_env_var="ADAAD_REPLAY_PROOF_SIGNING_KEY",
                fallback_namespace="adaad-replay-proof-dev-secret",
            ),
        }
        bundle = {**unsigned_bundle, "proof_digest": proof_digest, "signature_bundle": signature_bundle, "signatures": [signature_bundle]}
        errors = validate_replay_proof_schema(bundle)
        if errors:
            raise ValueError(f"replay_proof_schema_validation_failed:{';'.join(errors)}")
        return bundle

    def write_bundle(self, epoch_id: str, destination: Path | None = None) -> Path:
        bundle = self.build_bundle(epoch_id)
        target = destination or (self.proofs_dir / f"{epoch_id}.replay_attestation.v1.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(canonical_json(bundle) + "\n", encoding="utf-8")
        return target


def verify_replay_proof_bundle(
    bundle: Dict[str, Any],
    *,
    keyring: Mapping[str, str] | None = None,
    accepted_issuers: Iterable[str] | None = None,
    key_validity_windows: Mapping[str, Mapping[str, str]] | None = None,
    revocation_source: Any | None = None,
    trust_policy_version: str | None = None,
) -> Dict[str, Any]:
    """Offline replay proof verification without runtime state dependencies."""

    schema_errors = validate_replay_proof_schema(bundle)
    if schema_errors:
        return {"ok": False, "error": "schema_validation_failed", "schema_errors": schema_errors}

    signatures = bundle.get("signatures")
    if not isinstance(signatures, list) or not signatures:
        return {"ok": False, "error": "missing_signatures"}

    signature_bundle = bundle.get("signature_bundle")
    if signature_bundle != signatures[0]:
        return {"ok": False, "error": "signature_bundle_mismatch"}

    trust_metadata = bundle.get("trust_root_metadata")
    enforced_policy = any(
        item is not None
        for item in (accepted_issuers, key_validity_windows, revocation_source, trust_policy_version)
    )
    if enforced_policy and not isinstance(trust_metadata, dict):
        return {"ok": False, "error": "trust_root_metadata_required"}

    accepted_issuer_set = set(accepted_issuers or [])
    if isinstance(trust_metadata, dict) and accepted_issuer_set:
        issuer_chain = trust_metadata.get("issuer_chain")
        if not isinstance(issuer_chain, list) or not issuer_chain:
            return {"ok": False, "error": "invalid_issuer_chain"}
        if not any(str(issuer) in accepted_issuer_set for issuer in issuer_chain):
            return {"ok": False, "error": "issuer_not_accepted"}

    if isinstance(trust_metadata, dict) and trust_policy_version is not None:
        if str(trust_metadata.get("trust_policy_version") or "") != trust_policy_version:
            return {
                "ok": False,
                "error": "trust_policy_version_mismatch",
                "expected_trust_policy_version": trust_policy_version,
                "actual_trust_policy_version": trust_metadata.get("trust_policy_version"),
            }

    unsigned_bundle = {
        "schema_version": bundle.get("schema_version"),
        "epoch_id": bundle.get("epoch_id"),
        "baseline_digest": bundle.get("baseline_digest"),
        "ledger_state_hash": bundle.get("ledger_state_hash"),
        "mutation_graph_fingerprint": bundle.get("mutation_graph_fingerprint"),
        "constitution_version": bundle.get("constitution_version"),
        "sandbox_policy_hash": bundle.get("sandbox_policy_hash"),
        "checkpoint_chain": bundle.get("checkpoint_chain", []),
        "checkpoint_chain_digest": bundle.get("checkpoint_chain_digest"),
        "replay_digest": bundle.get("replay_digest"),
        "canonical_digest": bundle.get("canonical_digest"),
        "policy_hashes": bundle.get("policy_hashes", {}),
    }
    if "trust_root_metadata" in bundle:
        unsigned_bundle["trust_root_metadata"] = bundle.get("trust_root_metadata")
    expected_proof_digest = sha256_prefixed_digest(unsigned_bundle)
    if bundle.get("proof_digest") != expected_proof_digest:
        return {
            "ok": False,
            "error": "proof_digest_mismatch",
            "expected_proof_digest": expected_proof_digest,
            "actual_proof_digest": bundle.get("proof_digest"),
        }

    validation: List[Dict[str, Any]] = []
    for signature in signatures:
        if not isinstance(signature, dict):
            validation.append({"ok": False, "error": "invalid_signature_entry"})
            continue
        key_id = str(signature.get("key_id") or "")
        algorithm = str(signature.get("algorithm") or "")
        signed_digest = str(signature.get("signed_digest") or "")
        provided = str(signature.get("signature") or "")
        if signed_digest != expected_proof_digest:
            validation.append(
                {
                    "ok": False,
                    "key_id": key_id,
                    "algorithm": algorithm,
                    "error": "signed_digest_mismatch",
                    "expected_signed_digest": expected_proof_digest,
                    "actual_signed_digest": signed_digest,
                }
            )
            continue

        if isinstance(trust_metadata, dict) and key_validity_windows is not None:
            key_epoch = trust_metadata.get("key_epoch")
            if not isinstance(key_epoch, dict):
                validation.append({"ok": False, "key_id": key_id, "algorithm": algorithm, "error": "missing_key_epoch"})
                continue
            epoch_id = str(key_epoch.get("id") or "")
            window = key_validity_windows.get(epoch_id)
            if window is None:
                validation.append(
                    {
                        "ok": False,
                        "key_id": key_id,
                        "algorithm": algorithm,
                        "error": "unknown_key_epoch",
                        "key_epoch_id": epoch_id,
                    }
                )
                continue
            actual_from = _parse_iso8601_utc(str(key_epoch.get("valid_from") or ""))
            actual_until = _parse_iso8601_utc(str(key_epoch.get("valid_until") or ""))
            expected_from = _parse_iso8601_utc(str(window.get("valid_from") or ""))
            expected_until = _parse_iso8601_utc(str(window.get("valid_until") or ""))
            if None in (actual_from, actual_until, expected_from, expected_until):
                validation.append(
                    {
                        "ok": False,
                        "key_id": key_id,
                        "algorithm": algorithm,
                        "error": "invalid_key_validity_window",
                        "key_epoch_id": epoch_id,
                    }
                )
                continue
            if actual_from < expected_from or actual_until > expected_until:
                validation.append(
                    {
                        "ok": False,
                        "key_id": key_id,
                        "algorithm": algorithm,
                        "error": "key_validity_window_violation",
                        "key_epoch_id": epoch_id,
                    }
                )
                continue

        if isinstance(trust_metadata, dict) and revocation_source is not None:
            revocation_reference = trust_metadata.get("revocation_reference")
            revoked = bool(revocation_source(key_id=key_id, trust_metadata=trust_metadata, revocation_reference=revocation_reference))
            if revoked:
                validation.append({"ok": False, "key_id": key_id, "algorithm": algorithm, "error": "key_revoked"})
                continue
        if keyring is not None:
            secret = (keyring or {}).get(key_id)
            if not secret:
                validation.append({"ok": False, "key_id": key_id, "algorithm": algorithm, "error": "unknown_key_id"})
                continue
            expected_signature = "sha256:" + sha256_digest(f"{secret}:{signed_digest}")
        else:
            expected_signature = cryovant.sign_hmac_digest(
                key_id=key_id,
                signed_digest=signed_digest,
                specific_env_prefix="ADAAD_REPLAY_PROOF_KEY_",
                generic_env_var="ADAAD_REPLAY_PROOF_SIGNING_KEY",
                fallback_namespace="adaad-replay-proof-dev-secret",
            )
        validation.append(
            {
                "ok": provided == expected_signature,
                "key_id": key_id,
                "algorithm": algorithm,
                "error": "" if provided == expected_signature else "signature_mismatch",
            }
        )

    all_valid = bool(validation) and all(item.get("ok") for item in validation)
    return {"ok": all_valid, "proof_digest": expected_proof_digest, "signature_results": validation}


def load_replay_proof(path: Path) -> Dict[str, Any]:
    return json.loads(read_file_deterministic(path))


def validate_replay_proof_schema(bundle: Dict[str, Any]) -> List[str]:
    schema = json.loads(read_file_deterministic(REPLAY_ATTESTATION_SCHEMA_PATH))
    return _validate_schema_subset(bundle, schema)


__all__ = [
    "ReplayProofBuilder",
    "verify_replay_proof_bundle",
    "load_replay_proof",
    "validate_replay_proof_schema",
    "REPLAY_PROOFS_DIR",
    "DEFAULT_PROOF_SIGNING_ALGORITHM",
]
