# SPDX-License-Identifier: Apache-2.0
"""Checkpoint chain verification helpers."""

from __future__ import annotations

from typing import Any, Dict, List

from runtime.evolution.lineage_v2 import LineageLedgerV2
from runtime.governance.foundation import ZERO_HASH, sha256_prefixed_digest


def verify_checkpoint_chain(ledger: LineageLedgerV2, epoch_id: str) -> Dict[str, Any]:
    checkpoints: List[Dict[str, Any]] = [
        dict(entry.get("payload") or {})
        for entry in ledger.read_epoch(epoch_id)
        if entry.get("type") == "EpochCheckpointEvent"
    ]
    previous = ZERO_HASH
    errors: List[str] = []
    for index, cp in enumerate(checkpoints):
        prev = str(cp.get("prev_checkpoint_hash") or "")
        if prev != previous:
            errors.append(f"prev_checkpoint_mismatch:{index}")
        material = {
            "epoch_id": cp.get("epoch_id"),
            "epoch_digest": cp.get("epoch_digest"),
            "baseline_digest": cp.get("baseline_digest"),
            "mutation_count": cp.get("mutation_count"),
            "promotion_event_count": cp.get("promotion_event_count"),
            "scoring_event_count": cp.get("scoring_event_count"),
            "promotion_policy_hash": cp.get("promotion_policy_hash"),
            "entropy_policy_hash": cp.get("entropy_policy_hash"),
            "evidence_hash": cp.get("evidence_hash"),
            "sandbox_policy_hash": cp.get("sandbox_policy_hash"),
            "prev_checkpoint_hash": cp.get("prev_checkpoint_hash"),
        }
        expected_hash = sha256_prefixed_digest(material)
        if str(cp.get("checkpoint_hash") or "") != expected_hash:
            errors.append(f"checkpoint_hash_mismatch:{index}")
        previous = str(cp.get("checkpoint_hash") or previous)
    return {"epoch_id": epoch_id, "count": len(checkpoints), "passed": not errors, "errors": errors}


__all__ = ["verify_checkpoint_chain"]
