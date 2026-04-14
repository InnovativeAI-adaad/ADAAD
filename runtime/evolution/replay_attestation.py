# SPDX-License-Identifier: Apache-2.0
"""Deterministic replay attestation proof bundle helpers."""

from __future__ import annotations

import json
import os
import re
import base64
import hashlib
import hmac
import importlib.util
from functools import lru_cache
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

from runtime import ROOT_DIR
from runtime.constitution import CONSTITUTION_VERSION
from runtime.evolution.lineage_v2 import LineageLedgerV2
from runtime.evolution.replay import ReplayEngine
from runtime.governance.deterministic_filesystem import read_file_deterministic
from runtime.governance.foundation import ZERO_HASH, canonical_json, sha256_digest, sha256_prefixed_digest
from runtime.sandbox.environment_snapshot import collect_pre_execution_snapshot
from security import cryovant

REPLAY_PROOFS_DIR = ROOT_DIR / "security" / "ledger" / "replay_proofs"
DEFAULT_PROOF_SIGNING_ALGORITHM = "hmac-sha256"
PREFERRED_PROOF_SIGNING_ALGORITHM = "ed25519"
PROOF_KEYRING_PATH = ROOT_DIR / "security" / "replay_proof_keyring.json"
LOCAL_PROOF_KEYRING_PATH = ROOT_DIR / "security" / "replay_proof_keyring.local.json"
REPLAY_ATTESTATION_SCHEMA_PATH = ROOT_DIR / "schemas" / "replay_attestation.v1.json"

_SECRET_FIELDS = frozenset({"hmac_secret", "private_key"})
_PLACEHOLDER_MARKERS = ("placeholder", "replace_with", "example", "dummy", "unset")


def _explicit_dev_mode_enabled() -> bool:
    env = (os.getenv("ADAAD_ENV") or "").strip().lower()
    return env in {"dev", "test"}


def _looks_like_placeholder_secret(value: str) -> bool:
    normalized = value.strip().lower()
    if not normalized:
        return True
    return any(marker in normalized for marker in _PLACEHOLDER_MARKERS)


def _load_keyring_file(path: Path) -> Dict[str, Dict[str, str]]:
    if not path.exists():
        return {}
    raw = json.loads(read_file_deterministic(path))
    if not isinstance(raw, dict):
        return {}
    keys = raw.get("keys")
    if not isinstance(keys, dict):
        return {}
    normalized: Dict[str, Dict[str, str]] = {}
    for key_id, payload in keys.items():
        if not isinstance(key_id, str) or not isinstance(payload, dict):
            continue
        normalized[key_id] = {str(k): str(v) for k, v in payload.items() if isinstance(v, str)}
    return normalized


def _merge_keyring_payloads(base: Dict[str, Dict[str, str]], overlay: Mapping[str, Mapping[str, str]]) -> None:
    for key_id, payload in overlay.items():
        target = base.setdefault(key_id, {})
        for field, value in payload.items():
            if isinstance(value, str) and value.strip():
                target[field] = value.strip()


@lru_cache(maxsize=128)
def _key_variant_tokens(key_id: str) -> List[str]:
    normalized = key_id.strip().upper().replace("-", "_")
    compact = normalized.replace("_", "")
    variants = [normalized]
    if compact != normalized:
        variants.append(compact)
    return variants


def _resolve_env_secret_field(*, key_id: str, field: str) -> str:
    field_token = field.upper()
    for key_variant in _key_variant_tokens(key_id):
        specific = os.getenv(f"ADAAD_REPLAY_PROOF_{field_token}_{key_variant}", "").strip()
        if specific:
            return specific
    generic = os.getenv(f"ADAAD_REPLAY_PROOF_{field_token}", "").strip()
    if generic:
        return generic
    return ""


def _apply_env_secret_overrides(keys: Dict[str, Dict[str, str]]) -> None:
    for key_id, payload in keys.items():
        for field in _SECRET_FIELDS:
            resolved = _resolve_env_secret_field(key_id=key_id, field=field)
            if resolved:
                payload[field] = resolved


def _validate_keyring_secrets(keys: Mapping[str, Mapping[str, str]]) -> None:
    if _explicit_dev_mode_enabled():
        return
    for key_id, payload in keys.items():
        algorithm = str(payload.get("algorithm") or "").strip().lower()
        if algorithm == "hmac-sha256":
            secret = str(payload.get("hmac_secret") or "")
            if _looks_like_placeholder_secret(secret):
                raise RuntimeError(f"replay_proof_keyring_placeholder_secret:{key_id}:hmac_secret")
        if algorithm == "ed25519":
            secret = str(payload.get("private_key") or "")
            if _looks_like_placeholder_secret(secret):
                raise RuntimeError(f"replay_proof_keyring_placeholder_secret:{key_id}:private_key")


def _load_hmac_replay_proof_keyring(path: Path | None = None) -> Dict[str, str]:
    keyring = _load_replay_proof_keyring(path)
    normalized: Dict[str, str] = {}
    for key_id, payload in keyring.items():
        if payload.get("algorithm") not in {"", "hmac-sha256"}:
            continue
        secret = payload.get("hmac_secret")
        if isinstance(secret, str) and secret.strip():
            normalized[key_id] = secret.strip()
    return normalized


def _load_ed25519_signing_key():
    from nacl.signing import SigningKey

    return SigningKey


def _load_ed25519_verify_key():
    from nacl.signing import VerifyKey

    return VerifyKey


@lru_cache(maxsize=1)
def _has_pynacl() -> bool:
    return importlib.util.find_spec("nacl") is not None and importlib.util.find_spec("nacl.signing") is not None


def _has_ed25519_private_key(key_id: str, *, keyring: Mapping[str, Mapping[str, str]] | None = None) -> bool:
    keys = keyring or _load_replay_proof_keyring()
    payload = keys.get(key_id) or {}
    return bool(payload.get("private_key"))


def _load_replay_proof_keyring(path: Path | None = None) -> Dict[str, Dict[str, str]]:
    target = path or Path(os.getenv("ADAAD_REPLAY_PROOF_KEYRING_PATH", str(PROOF_KEYRING_PATH)))
    local_override = Path(os.getenv("ADAAD_REPLAY_PROOF_KEYRING_LOCAL_PATH", str(LOCAL_PROOF_KEYRING_PATH)))
    secret_mount = os.getenv("ADAAD_REPLAY_PROOF_KEYRING_SECRET_PATH", "").strip()

    normalized: Dict[str, Dict[str, str]] = {}
    _merge_keyring_payloads(normalized, _load_keyring_file(target))
    _merge_keyring_payloads(normalized, _load_keyring_file(local_override))
    if secret_mount:
        _merge_keyring_payloads(normalized, _load_keyring_file(Path(secret_mount)))
    _apply_env_secret_overrides(normalized)
    _validate_keyring_secrets(normalized)
    return normalized


class ReplayProofSigner:
    def sign(self, *, key_id: str, signed_digest: str) -> str:
        raise NotImplementedError

    def verify(self, *, key_id: str, signed_digest: str, signature: str) -> bool:
        raise NotImplementedError


class HmacReplayProofSigner(ReplayProofSigner):
    def __init__(self, *, keyring: Mapping[str, str] | None = None):
        self.keyring = keyring

    def sign(self, *, key_id: str, signed_digest: str) -> str:
        secret = self.keyring.get(key_id) if self.keyring is not None else None
        return cryovant.sign_artifact_hmac_digest(
            artifact_type="replay_proof",
            key_id=key_id,
            signed_digest=signed_digest,
            hmac_secret=secret,
        )

    def verify(self, *, key_id: str, signed_digest: str, signature: str) -> bool:
        secret = self.keyring.get(key_id) if self.keyring is not None else None
        if self.keyring is not None and not secret:
            return False
        return cryovant.verify_artifact_hmac_digest_signature(
            artifact_type="replay_proof",
            key_id=key_id,
            signed_digest=signed_digest,
            signature=signature,
            hmac_secret=secret,
        )


class Ed25519ReplayProofSigner(ReplayProofSigner):
    def __init__(self, *, keyring: Mapping[str, Mapping[str, str]]):
        self.keyring = keyring

    def sign(self, *, key_id: str, signed_digest: str) -> str:
        if not _has_pynacl():
            raise RuntimeError("ed25519_signing_requires_pynacl")
        key_payload = self.keyring.get(key_id) or {}
        seed_b64 = key_payload.get("private_key")
        if not seed_b64:
            raise ValueError(f"missing_private_key:{key_id}")
        SigningKey = _load_ed25519_signing_key()
        try:
            private_key_seed = base64.b64decode(seed_b64)
            signing_key = SigningKey(private_key_seed)
        except Exception as exc:
            raise ValueError(f"invalid_private_key:{key_id}") from exc
        signature = signing_key.sign(signed_digest.encode("utf-8")).signature
        return "ed25519:" + base64.b64encode(signature).decode("ascii")

    def verify(self, *, key_id: str, signed_digest: str, signature: str) -> bool:
        key_payload = self.keyring.get(key_id) or {}
        if not isinstance(signature, str) or not signature.startswith("ed25519:"):
            return False
        if not _has_pynacl():
            return False
        verify_key_b64 = key_payload.get("public_key")
        if not verify_key_b64:
            private_key_seed_b64 = key_payload.get("private_key")
            if not private_key_seed_b64:
                return False
            try:
                SigningKey = _load_ed25519_signing_key()
                derived_verify_key = SigningKey(base64.b64decode(private_key_seed_b64)).verify_key
                verify_key_b64 = base64.b64encode(bytes(derived_verify_key)).decode("ascii")
            except Exception:
                return False
        try:
            VerifyKey = _load_ed25519_verify_key()
            decoded_signature = base64.b64decode(signature.split(":", 1)[1])
            verify_key_candidates = [verify_key_b64]
            private_key_seed_b64 = key_payload.get("private_key")
            if private_key_seed_b64:
                SigningKey = _load_ed25519_signing_key()
                derived_verify_key = SigningKey(base64.b64decode(private_key_seed_b64)).verify_key
                derived_verify_key_b64 = base64.b64encode(bytes(derived_verify_key)).decode("ascii")
                if derived_verify_key_b64 not in verify_key_candidates:
                    verify_key_candidates.append(derived_verify_key_b64)
            for candidate in verify_key_candidates:
                verify_key = VerifyKey(base64.b64decode(candidate))
                try:
                    verify_key.verify(signed_digest.encode("utf-8"), decoded_signature)
                    return True
                except Exception:
                    continue
        except Exception:
            return False
        return False


def sign_replay_payload_digest(*, algorithm: str, key_id: str, signed_digest: str, keyring: Mapping[str, Any] | None = None) -> str:
    """Sign a canonical replay payload digest using replay-proof key material."""
    if algorithm == "ed25519":
        signer_keyring: Any = keyring or _load_replay_proof_keyring()
    elif algorithm == "hmac-sha256":
        if keyring is not None:
            signer_keyring = keyring
        else:
            hmac_keyring = _load_hmac_replay_proof_keyring()
            signer_keyring = hmac_keyring if key_id in hmac_keyring else None
    else:
        raise ValueError(f"unsupported_signing_algorithm:{algorithm}")

    signer = _build_signer(algorithm, keyring=signer_keyring)
    return signer.sign(key_id=key_id, signed_digest=signed_digest)


def verify_replay_payload_digest_signature(
    *,
    algorithm: str,
    key_id: str,
    signed_digest: str,
    signature: str,
    keyring: Mapping[str, Any] | None = None,
) -> bool:
    """Verify a replay payload digest signature using replay-proof key material."""
    if algorithm == "ed25519":
        signer_keyring: Any = keyring or _load_replay_proof_keyring()
    elif algorithm == "hmac-sha256":
        if keyring is not None:
            signer_keyring = keyring
        else:
            hmac_keyring = _load_hmac_replay_proof_keyring()
            signer_keyring = hmac_keyring if key_id in hmac_keyring else None
    else:
        return False

    signer = _build_signer(algorithm, keyring=signer_keyring)
    return signer.verify(key_id=key_id, signed_digest=signed_digest, signature=signature)


def _build_signer(algorithm: str, *, keyring: Any = None) -> ReplayProofSigner:
    if algorithm == "hmac-sha256":
        return HmacReplayProofSigner(keyring=keyring)
    if algorithm == "ed25519":
        return Ed25519ReplayProofSigner(keyring=keyring or {})
    raise ValueError(f"unsupported_signing_algorithm:{algorithm}")


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
        resolved_algorithm = (algorithm or os.getenv("ADAAD_REPLAY_PROOF_ALGO", "")).strip()
        if not resolved_algorithm:
            env_name = os.getenv("ADAAD_ENV", "dev").strip().lower()
            if env_name in {"production", "prod", "staging"}:
                if _has_ed25519_private_key(self.key_id):
                    resolved_algorithm = PREFERRED_PROOF_SIGNING_ALGORITHM
                else:
                    # REPLAY-ALGO-0: In production, if Ed25519 key is absent and no
                    # explicit override is set, FAIL CLOSED rather than silently
                    # downgrading to HMAC.  The only permitted escape is the explicit
                    # opt-in env var ADAAD_REPLAY_PROOF_ALLOW_HMAC_FALLBACK=1.
                    allow_fallback = os.getenv(
                        "ADAAD_REPLAY_PROOF_ALLOW_HMAC_FALLBACK", ""
                    ).strip().lower() in {"1", "true", "yes", "on"}
                    if not allow_fallback:
                        raise RuntimeError(
                            "REPLAY-ALGO-0: Ed25519 key absent in production environment. "
                            "Silent HMAC downgrade is constitutionally prohibited. "
                            "Execute the Ed25519 key ceremony (FINDING-66-004) or set "
                            "ADAAD_REPLAY_PROOF_ALLOW_HMAC_FALLBACK=1 to explicitly "
                            "acknowledge the degraded security posture."
                        )
                    resolved_algorithm = DEFAULT_PROOF_SIGNING_ALGORITHM
            else:
                resolved_algorithm = DEFAULT_PROOF_SIGNING_ALGORITHM
        if resolved_algorithm == "ed25519" and not _has_pynacl():
            allow_downgrade = os.getenv("ADAAD_REPLAY_PROOF_ALLOW_ED25519_DOWNGRADE", "").strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
            if allow_downgrade:
                resolved_algorithm = DEFAULT_PROOF_SIGNING_ALGORITHM
            else:
                raise RuntimeError("ed25519_requires_pynacl_or_explicit_downgrade")
        self.algorithm = resolved_algorithm

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


    def _fitness_weight_snapshot_hash(self, epoch_id: str) -> str:
        events = self.ledger.read_epoch(epoch_id)
        for entry in reversed(events):
            payload_raw = entry.get("payload")
            payload: Dict[str, Any] = payload_raw if isinstance(payload_raw, dict) else {}
            if entry.get("type") == "EpochMetadataEvent":
                metadata_raw = payload.get("metadata")
                metadata: Dict[str, Any] = metadata_raw if isinstance(metadata_raw, dict) else {}
                candidate = metadata.get("fitness_weight_snapshot_hash")
                if isinstance(candidate, str) and candidate:
                    return candidate
            if entry.get("type") == "fitness_regime_snapshot":
                candidate = payload.get("weight_snapshot_hash") or payload.get("config_hash")
                if isinstance(candidate, str) and candidate:
                    return candidate
        return ZERO_HASH

    def _replay_seed_for_epoch(self, epoch_id: str) -> str:
        events = self.ledger.read_epoch(epoch_id)
        for entry in events:
            payload_raw = entry.get("payload")
            payload: Dict[str, Any] = payload_raw if isinstance(payload_raw, dict) else {}
            if entry.get("type") == "EpochStartEvent":
                metadata = payload.get("metadata") or {}
                if isinstance(metadata, dict):
                    seed = metadata.get("seed")
                    if isinstance(seed, str) and seed:
                        return seed
        return epoch_id

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
        fitness_weight_snapshot_hash = self._fitness_weight_snapshot_hash(epoch_id)
        replay_environment_fingerprint = collect_pre_execution_snapshot({"replay_seed": self._replay_seed_for_epoch(epoch_id)})
        replay_environment_fingerprint.pop("_tracked_files", None)
        replay_environment_fingerprint.pop("_filesystem_state", None)
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
            "fitness_weight_snapshot_hash": fitness_weight_snapshot_hash,
            "replay_environment_fingerprint": replay_environment_fingerprint,
            "replay_environment_fingerprint_hash": sha256_prefixed_digest(replay_environment_fingerprint),
        }
        proof_digest = sha256_prefixed_digest(unsigned_bundle)
        signed_digest = proof_digest
        if self.algorithm == "ed25519":
            signer_keyring: Any = _load_replay_proof_keyring()
        elif self.algorithm == "hmac-sha256":
            hmac_keyring = _load_hmac_replay_proof_keyring()
            signer_keyring = hmac_keyring if self.key_id in hmac_keyring else None
        else:
            signer_keyring = None
        signer = _build_signer(self.algorithm, keyring=signer_keyring)
        signature_bundle = {
            "key_id": self.key_id,
            "algorithm": self.algorithm,
            "signed_digest": signed_digest,
            "signature": signer.sign(key_id=self.key_id, signed_digest=signed_digest),
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
    keyring: Mapping[str, Any] | None = None,
    accepted_issuers: Iterable[str] | None = None,
    key_validity_windows: Mapping[str, Mapping[str, str]] | None = None,
    revocation_source: Any | None = None,
    trust_policy_version: str | None = None,
    expected_replay_environment_fingerprint: Mapping[str, Any] | None = None,
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


    observed_replay_environment_fingerprint = dict(bundle.get("replay_environment_fingerprint") or {})
    observed_replay_environment_fingerprint_hash = str(bundle.get("replay_environment_fingerprint_hash") or "")
    expected_fingerprint_hash = sha256_prefixed_digest(observed_replay_environment_fingerprint)
    if observed_replay_environment_fingerprint_hash != expected_fingerprint_hash:
        return {
            "ok": False,
            "error": "replay_environment_fingerprint_hash_mismatch",
            "expected_replay_environment_fingerprint_hash": expected_fingerprint_hash,
            "actual_replay_environment_fingerprint_hash": observed_replay_environment_fingerprint_hash,
        }

    if expected_replay_environment_fingerprint is not None:
        normalized_expected_replay_environment_fingerprint = json.loads(
            canonical_json(dict(expected_replay_environment_fingerprint))
        )
        if normalized_expected_replay_environment_fingerprint != observed_replay_environment_fingerprint:
            return {
                "ok": False,
                "error": "replay_environment_fingerprint_mismatch",
                "expected_replay_environment_fingerprint": normalized_expected_replay_environment_fingerprint,
                "actual_replay_environment_fingerprint": observed_replay_environment_fingerprint,
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
        "fitness_weight_snapshot_hash": bundle.get("fitness_weight_snapshot_hash"),
        "replay_environment_fingerprint": observed_replay_environment_fingerprint,
        "replay_environment_fingerprint_hash": observed_replay_environment_fingerprint_hash,
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
            assert actual_from is not None and actual_until is not None and expected_from is not None and expected_until is not None
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
        if algorithm == "ed25519":
            if not _has_pynacl():
                validation.append(
                    {
                        "ok": False,
                        "key_id": key_id,
                        "algorithm": algorithm,
                        "error": "missing_dependency_pynacl",
                    }
                )
                continue
            resolved_ed25519_keyring = keyring or _load_replay_proof_keyring()
            signer = _build_signer("ed25519", keyring=resolved_ed25519_keyring)
            if key_id not in resolved_ed25519_keyring:
                validation.append({"ok": False, "key_id": key_id, "algorithm": algorithm, "error": "unknown_key_id"})
                continue
            matches = signer.verify(key_id=key_id, signed_digest=signed_digest, signature=provided)
        elif algorithm == "hmac-sha256":
            if keyring is not None:
                signer_keyring: Any = keyring
            else:
                hmac_keyring = _load_hmac_replay_proof_keyring()
                signer_keyring = hmac_keyring if key_id in hmac_keyring else None
            signer = _build_signer("hmac-sha256", keyring=signer_keyring)
            if keyring is not None and key_id not in keyring:
                validation.append({"ok": False, "key_id": key_id, "algorithm": algorithm, "error": "unknown_key_id"})
                continue
            matches = signer.verify(key_id=key_id, signed_digest=signed_digest, signature=provided)
        else:
            validation.append({"ok": False, "key_id": key_id, "algorithm": algorithm, "error": "unsupported_algorithm"})
            continue
        validation.append(
            {
                "ok": matches,
                "key_id": key_id,
                "algorithm": algorithm,
                "error": "" if matches else "signature_mismatch",
            }
        )

    all_valid = bool(validation) and all(item.get("ok") for item in validation)
    return {"ok": all_valid, "proof_digest": expected_proof_digest, "signature_results": validation}


def load_replay_proof(path: Path) -> Dict[str, Any]:
    return json.loads(read_file_deterministic(path))


def validate_replay_proof_schema(bundle: Dict[str, Any]) -> List[str]:
    schema = json.loads(read_file_deterministic(REPLAY_ATTESTATION_SCHEMA_PATH))
    errors = _validate_schema_subset(bundle, schema)

    signatures = bundle.get("signatures")
    if isinstance(signatures, list):
        for idx, signature in enumerate(signatures):
            if not isinstance(signature, dict):
                continue
            algorithm = str(signature.get("algorithm") or "")
            value = str(signature.get("signature") or "")
            if algorithm == "hmac-sha256" and not re.fullmatch(r"(?:sha256:)?[a-f0-9]{64}", value):
                errors.append(f"$.signatures[{idx}].signature:invalid_hmac_signature")
            if algorithm == "ed25519" and not re.fullmatch(r"ed25519:[A-Za-z0-9+/=]+", value):
                errors.append(f"$.signatures[{idx}].signature:invalid_ed25519_signature")
            if algorithm == "ed25519" and not str(signature.get("key_id") or ""):
                errors.append(f"$.signatures[{idx}].key_id:missing_required")
            if algorithm not in {"hmac-sha256", "ed25519"}:
                errors.append(f"$.signatures[{idx}].algorithm:unsupported")
    return errors


__all__ = [
    "ReplayProofBuilder",
    "sign_replay_payload_digest",
    "verify_replay_payload_digest_signature",
    "verify_replay_proof_bundle",
    "load_replay_proof",
    "validate_replay_proof_schema",
    "REPLAY_PROOFS_DIR",
    "DEFAULT_PROOF_SIGNING_ALGORITHM",
]
