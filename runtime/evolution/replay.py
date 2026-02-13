# SPDX-License-Identifier: Apache-2.0
"""Deterministic replay helpers for lineage epochs."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict

from runtime.evolution.lineage_v2 import LineageLedgerV2


class ReplayEngine:
    def __init__(self, ledger: LineageLedgerV2 | None = None) -> None:
        self.ledger = ledger or LineageLedgerV2()

    def reconstruct_epoch(self, epoch_id: str) -> Dict[str, Any]:
        events = self.ledger.read_epoch(epoch_id)
        initial = [e for e in events if e.get("type") == "EpochStartEvent"]
        final = [e for e in events if e.get("type") == "EpochEndEvent"]
        bundles = [e for e in events if e.get("type") == "MutationBundleEvent"]
        return {
            "epoch_id": epoch_id,
            "initial_state": initial[0]["payload"] if initial else {},
            "bundles": bundles,
            "final_state": final[-1]["payload"] if final else {},
        }

    def compute_incremental_digest(self, epoch_id: str) -> str:
        return self.ledger.compute_incremental_epoch_digest(epoch_id)

    def replay_epoch(self, epoch_id: str) -> Dict[str, Any]:
        reconstructed = self.reconstruct_epoch(epoch_id)
        replay_digest = self.compute_incremental_digest(epoch_id)
        replay_material = {"reconstructed": reconstructed, "replay_digest": replay_digest}
        canonical_digest = hashlib.sha256(json.dumps(replay_material, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        return {
            "epoch_id": epoch_id,
            "digest": replay_digest,
            "canonical_digest": canonical_digest,
            "events": len(reconstructed.get("bundles", [])),
        }

    def deterministic_replay(self, epoch_id: str) -> Dict[str, Any]:
        return self.replay_epoch(epoch_id)

    def assert_reachable(self, epoch_id: str, expected_digest: str) -> bool:
        replay = self.replay_epoch(epoch_id)
        return replay["digest"] == expected_digest


__all__ = ["ReplayEngine"]
