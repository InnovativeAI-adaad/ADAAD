# SPDX-License-Identifier: Apache-2.0
"""Deterministic replay helpers for lineage epochs."""

from __future__ import annotations

from typing import Any, Dict

from runtime.evolution.lineage_v2 import LineageLedgerV2
from runtime.governance.foundation.hashing import sha256_digest
from runtime.sandbox.replay import replay_sandbox_execution


class ReplayEngine:
    def __init__(self, ledger: LineageLedgerV2 | None = None) -> None:
        self.ledger = ledger or LineageLedgerV2()

    def reconstruct_epoch(self, epoch_id: str) -> Dict[str, Any]:
        events = self.ledger.read_epoch(epoch_id)
        initial = [e for e in events if e.get("type") == "EpochStartEvent"]
        final = [e for e in events if e.get("type") == "EpochEndEvent"]
        bundles = [e for e in events if e.get("type") == "MutationBundleEvent"]
        sandbox_events = [e for e in events if e.get("type") == "SandboxEvidenceEvent"]
        return {
            "epoch_id": epoch_id,
            "initial_state": initial[0]["payload"] if initial else {},
            "bundles": bundles,
            "sandbox_events": sandbox_events,
            "final_state": final[-1]["payload"] if final else {},
        }

    def compute_incremental_digest_unverified(self, epoch_id: str) -> str:
        """Recompute digest from event payloads without hash-chain integrity checks.

        Intended for forensic / tamper-analysis workflows where the ledger chain
        may already be compromised. For production replay verification use
        :meth:`compute_incremental_digest` which enforces chain integrity first.
        """

        return self.ledger.compute_incremental_epoch_digest_unverified(epoch_id)

    def compute_incremental_digest(self, epoch_id: str) -> str:
        """Recompute digest with chain-integrity verification enforced."""

        return self.ledger.compute_incremental_epoch_digest(epoch_id)

    def replay_epoch(self, epoch_id: str) -> Dict[str, Any]:
        reconstructed = self.reconstruct_epoch(epoch_id)
        replay_digest = self.compute_incremental_digest(epoch_id)
        sandbox_events = reconstructed.get("sandbox_events", [])
        sandbox_replay = [
            replay_sandbox_execution((event.get("payload") or {}).get("manifest", {}), (event.get("payload") or {}))
            for event in sandbox_events
            if isinstance((event.get("payload") or {}).get("manifest"), dict)
        ]
        replay_material = {"reconstructed": reconstructed, "replay_digest": replay_digest, "sandbox_replay": sandbox_replay}
        canonical_digest = sha256_digest(replay_material)
        return {
            "epoch_id": epoch_id,
            "digest": replay_digest,
            "canonical_digest": canonical_digest,
            "events": len(reconstructed.get("bundles", [])),
            "sandbox_replay": sandbox_replay,
        }

    def deterministic_replay(self, epoch_id: str) -> Dict[str, Any]:
        return self.replay_epoch(epoch_id)

    def assert_reachable(self, epoch_id: str, expected_digest: str) -> bool:
        replay = self.replay_epoch(epoch_id)
        return replay["digest"] == expected_digest


__all__ = ["ReplayEngine"]
