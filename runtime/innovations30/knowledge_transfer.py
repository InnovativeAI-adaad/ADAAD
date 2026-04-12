# SPDX-License-Identifier: Apache-2.0
"""Innovation #13 — Institutional Memory Transfer (IMT).

Cryptographically verified transfer of knowledge between ADAAD instances.
The system's engineering wisdom outlives its hardware.

Constitutional invariants enforced by this module
  IMT-0        KnowledgeBundle MUST be cryptographically signed before transmission.
  IMT-VERIFY-0 import_bundle() MUST verify signature before any knowledge state write.
  IMT-CHAIN-0  Every import event MUST be recorded in chain-of-custody ledger.
  IMT-DETERM-0 Bundle serialization is deterministic: canonical JSON (sort_keys=True),
               no datetime.now(), no random, no uuid4.
"""
from __future__ import annotations
import hashlib, hmac, json, gzip
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import hashlib
import hmac

# Hardening scaffold — injected by fix/senior-deep-dive-hardening
KNTR_INV_CHAIN: str = "KNTR-INV-CHAIN"


class KnowledgeTransferViolation(RuntimeError):
    """Raised when a Knowledge Transfer constitutional invariant is breached."""



_IMT_SIGN_ALGO: str = "sha256-hmac"
_IMT_BUNDLE_VERSION: str = "1.1"
_IMT_CHAIN_LEDGER: str = "data/governance_events.jsonl"


class TransferVerificationError(Exception):
    """Raised when IMT-VERIFY-0 violated: unsigned or tampered bundle."""


class TransferIntegrityError(Exception):
    """Raised when bundle_hash does not match recomputed content digest."""


def _compute_hmac(message: str, key: str) -> str:
    """IMT-0 / IMT-VERIFY-0: deterministic HMAC-SHA256. Returns hex digest."""
    return hmac.new(key.encode(), message.encode(), hashlib.sha256).hexdigest()


@dataclass
class KnowledgeBundle:
    """Immutable knowledge snapshot with cryptographic provenance.
    IMT-0: signature must be non-empty before transmission.
    IMT-DETERM-0: bundle_hash is sha256(canonical-json(knowledge_snapshot)).
    """
    source_instance_id: str
    bundle_version: str
    epoch_count: int
    knowledge_snapshot: dict[str, Any]
    bundle_hash: str
    signature: str = ""

    @classmethod
    def create(cls, source_id: str, knowledge: dict[str, Any], epoch_count: int) -> "KnowledgeBundle":
        """IMT-DETERM-0: sort_keys=True, no datetime/random."""
        payload = json.dumps(knowledge, sort_keys=True, ensure_ascii=False)
        bundle_hash = "sha256:" + hashlib.sha256(payload.encode()).hexdigest()
        return cls(source_instance_id=source_id, bundle_version=_IMT_BUNDLE_VERSION,
                   epoch_count=epoch_count, knowledge_snapshot=knowledge, bundle_hash=bundle_hash)

    def to_bytes(self) -> bytes:
        """IMT-DETERM-0: deterministic gzip+JSON serialization."""
        payload = json.dumps({
            "source_instance_id": self.source_instance_id, "bundle_version": self.bundle_version,
            "epoch_count": self.epoch_count, "knowledge_snapshot": self.knowledge_snapshot,
            "bundle_hash": self.bundle_hash, "signature": self.signature,
        }, sort_keys=True, ensure_ascii=False).encode()
        return gzip.compress(payload)

    @classmethod
    def from_bytes(cls, data: bytes) -> "KnowledgeBundle":
        payload = json.loads(gzip.decompress(data))
        return cls(**payload)

    def verify_integrity(self) -> bool:
        """IMT-DETERM-0: recompute bundle_hash from snapshot."""
        payload = json.dumps(self.knowledge_snapshot, sort_keys=True, ensure_ascii=False)
        expected = "sha256:" + hashlib.sha256(payload.encode()).hexdigest()
        return hmac.compare_digest(expected, self.bundle_hash)

    def verify_signature(self, signing_key: str) -> bool:
        """IMT-VERIFY-0: HMAC-SHA256 over bundle_hash. Empty sig returns False."""
        if not self.signature:
            return False
        return hmac.compare_digest(_compute_hmac(self.bundle_hash, signing_key), self.signature)


@dataclass
class TransferResult:
    success: bool
    imported_items: int
    integrity_verified: bool
    signature_verified: bool
    source_instance_id: str
    chain_ledger_path: str = ""
    error: str = ""


class InstitutionalMemoryTransfer:
    """Exports, signs, and imports knowledge bundles between ADAAD instances.
    IMT-0        sign_bundle() is the sole signing surface.
    IMT-VERIFY-0 import_bundle() raises TransferVerificationError before any state write.
    IMT-CHAIN-0  Every import event appended to chain_ledger before return.
    IMT-DETERM-0 All hashing: sort_keys=True, sha256, no runtime entropy.
    """

    def __init__(self, transfer_log: Path = Path("data/memory_transfers.jsonl"),
                 chain_ledger: Path = Path(_IMT_CHAIN_LEDGER)):
        self.transfer_log = Path(transfer_log)
        self.chain_ledger = Path(chain_ledger)

    def export_bundle(self, instance_id: str, knowledge_sources: dict[str, Path],
                      epoch_count: int) -> KnowledgeBundle:
        """IMT-DETERM-0: sources iterated in sorted order for determinism."""
        knowledge: dict[str, Any] = {}
        for name, path in sorted(knowledge_sources.items()):
            p = Path(path)
            if p.exists():
                try:
                    content = p.read_text()
                    try:
                        knowledge[name] = json.loads(content)
                    except json.JSONDecodeError:
                        knowledge[name] = {"raw_lines": len(content.splitlines())}
                except Exception:
                    pass
        return KnowledgeBundle.create(instance_id, knowledge, epoch_count)

    def sign_bundle(self, bundle: KnowledgeBundle, signing_key: str) -> KnowledgeBundle:
        """IMT-0: sign a bundle. Returns new KnowledgeBundle with signature set."""
        if not signing_key:
            raise ValueError("IMT-0: signing_key must be non-empty")
        sig = _compute_hmac(bundle.bundle_hash, signing_key)
        return KnowledgeBundle(
            source_instance_id=bundle.source_instance_id, bundle_version=bundle.bundle_version,
            epoch_count=bundle.epoch_count, knowledge_snapshot=bundle.knowledge_snapshot,
            bundle_hash=bundle.bundle_hash, signature=sig)

    def import_bundle(self, bundle: KnowledgeBundle, target_paths: dict[str, Path],
                      signing_key: str, human_0_authorized: bool = False) -> TransferResult:
        """IMT-VERIFY-0: verify signature + integrity before any state write.
        IMT-CHAIN-0: chain event recorded on both success and rejection.
        """
        if not bundle.signature:
            self._record_chain_event(bundle, "REJECTED_UNSIGNED", human_0_authorized)
            raise TransferVerificationError(
                "IMT-0 / IMT-VERIFY-0: bundle signature is empty; sign_bundle() must be called before import")

        if not bundle.verify_signature(signing_key):
            self._record_chain_event(bundle, "REJECTED_BAD_SIGNATURE", human_0_authorized)
            raise TransferVerificationError(
                "IMT-VERIFY-0: HMAC signature verification failed — bundle may be tampered or signing_key mismatch")

        if not bundle.verify_integrity():
            self._record_chain_event(bundle, "REJECTED_INTEGRITY", human_0_authorized)
            raise TransferIntegrityError(
                "IMT-DETERM-0: bundle_hash does not match recomputed sha256 of knowledge_snapshot")

        imported = 0
        for name, data in bundle.knowledge_snapshot.items():
            if name in target_paths:
                tp = Path(target_paths[name])
                tp.parent.mkdir(parents=True, exist_ok=True)
                tp.write_text(json.dumps(data, indent=2, sort_keys=True))
                imported += 1

        result = TransferResult(success=True, imported_items=imported, integrity_verified=True,
            signature_verified=True, source_instance_id=bundle.source_instance_id,
            chain_ledger_path=str(self.chain_ledger))
        self._record_chain_event(bundle, "IMPORTED_OK", human_0_authorized)
        self._log_transfer(bundle, result)
        return result

    def _record_chain_event(self, bundle: KnowledgeBundle, outcome: str,
                            human_0_authorized: bool) -> None:
        """IMT-CHAIN-0: append governance event. Path.open — never builtins.open.
        IMT-DETERM-0: no datetime.now().
        """
        event: dict[str, Any] = {
            "event_type": "institutional_memory_transfer", "outcome": outcome,
            "source_instance_id": bundle.source_instance_id, "bundle_version": bundle.bundle_version,
            "epoch_count": bundle.epoch_count, "bundle_hash": bundle.bundle_hash,
            "sign_algo": _IMT_SIGN_ALGO, "human_0_authorized": human_0_authorized,
            "invariants": ["IMT-0", "IMT-VERIFY-0", "IMT-CHAIN-0", "IMT-DETERM-0"],
        }
        self.chain_ledger.parent.mkdir(parents=True, exist_ok=True)
        with self.chain_ledger.open("a") as fh:
            fh.write(json.dumps(event, sort_keys=True) + "\n")

    def _log_transfer(self, bundle: KnowledgeBundle, result: TransferResult) -> None:
        self.transfer_log.parent.mkdir(parents=True, exist_ok=True)
        with self.transfer_log.open("a") as fh:
            fh.write(json.dumps({
                "source": bundle.source_instance_id, "epoch_count": bundle.epoch_count,
                "bundle_hash": bundle.bundle_hash, "imported": result.imported_items,
                "success": result.success, "sig_verified": result.signature_verified,
            }, sort_keys=True) + "\n")


__all__ = ["InstitutionalMemoryTransfer", "KnowledgeBundle", "TransferResult",
           "TransferVerificationError", "TransferIntegrityError"]
