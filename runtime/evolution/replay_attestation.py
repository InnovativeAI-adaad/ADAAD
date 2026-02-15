# SPDX-License-Identifier: Apache-2.0
"""Deterministic replay attestation proof bundle helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

from runtime import ROOT_DIR
from runtime.evolution.lineage_v2 import LineageLedgerV2
from runtime.evolution.replay import ReplayEngine
from runtime.governance.foundation import ZERO_HASH, canonical_json, sha256_digest, sha256_prefixed_digest
from security import cryovant

REPLAY_PROOFS_DIR = ROOT_DIR / "security" / "ledger" / "replay_proofs"
DEFAULT_PROOF_SIGNING_ALGORITHM = "hmac-sha256"


def _normalize_checkpoint_event(payload: Dict[str, Any]) -> Dict[str, str]:
    return {
        "checkpoint_id": str(payload.get("checkpoint_id") or ""),
        "checkpoint_hash": str(payload.get("checkpoint_hash") or ZERO_HASH),
        "prev_checkpoint_hash": str(payload.get("prev_checkpoint_hash") or ZERO_HASH),
        "epoch_digest": str(payload.get("epoch_digest") or "sha256:0"),
        "baseline_digest": str(payload.get("baseline_digest") or "sha256:0"),
        "created_at": str(payload.get("created_at") or ""),
    }
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
        checkpoint_chain = self._collect_checkpoint_chain(epoch_id)
        checkpoint_hashes = [item["checkpoint_hash"] for item in checkpoint_chain]
        unsigned_bundle = {
            "schema_version": "1.0",
            "epoch_id": epoch_id,
            "checkpoint_chain": checkpoint_chain,
            "checkpoint_chain_digest": sha256_prefixed_digest(checkpoint_hashes),
            "replay_digest": str(replay_state.get("digest") or "sha256:0"),
            "canonical_digest": str(replay_state.get("canonical_digest") or sha256_digest(replay_state)),
            "policy_hashes": self._policy_hashes(checkpoint_chain, epoch_id),
        }
        proof_digest = sha256_prefixed_digest(unsigned_bundle)
        signed_digest = proof_digest
        signature = {
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
        return {**unsigned_bundle, "proof_digest": proof_digest, "signatures": [signature]}

    def write_bundle(self, epoch_id: str, destination: Path | None = None) -> Path:
        bundle = self.build_bundle(epoch_id)
        target = destination or (self.proofs_dir / f"{epoch_id}.replay_attestation.v1.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(canonical_json(bundle) + "\n", encoding="utf-8")
        return target


def verify_replay_proof_bundle(bundle: Dict[str, Any], *, keyring: Mapping[str, str] | None = None) -> Dict[str, Any]:
    """Offline replay proof verification without runtime state dependencies."""

    signatures = bundle.get("signatures")
    if not isinstance(signatures, list) or not signatures:
        return {"ok": False, "error": "missing_signatures"}

    unsigned_bundle = {
        "schema_version": bundle.get("schema_version"),
        "epoch_id": bundle.get("epoch_id"),
        "checkpoint_chain": bundle.get("checkpoint_chain", []),
        "checkpoint_chain_digest": bundle.get("checkpoint_chain_digest"),
        "replay_digest": bundle.get("replay_digest"),
        "canonical_digest": bundle.get("canonical_digest"),
        "policy_hashes": bundle.get("policy_hashes", {}),
    }
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
    return json.loads(path.read_text(encoding="utf-8"))


__all__ = [
    "ReplayProofBuilder",
    "verify_replay_proof_bundle",
    "load_replay_proof",
    "REPLAY_PROOFS_DIR",
    "DEFAULT_PROOF_SIGNING_ALGORITHM",
]
