# SPDX-License-Identifier: Apache-2.0
"""Runtime replay verification and divergence handling."""

from __future__ import annotations

from typing import Any, Dict

from runtime.evolution.lineage_v2 import LineageLedgerV2
from runtime.evolution.replay import ReplayEngine


class ReplayVerifier:
    def __init__(self, ledger: LineageLedgerV2, replay_engine: ReplayEngine, *, verify_every_n_mutations: int = 3) -> None:
        self.ledger = ledger
        self.replay_engine = replay_engine
        self.verify_every_n_mutations = max(1, verify_every_n_mutations)

    def should_verify(self, mutation_count: int) -> bool:
        return mutation_count > 0 and mutation_count % self.verify_every_n_mutations == 0

    def verify_epoch(self, epoch_id: str, expected_digest: str) -> Dict[str, Any]:
        replay_digest = self.replay_engine.compute_incremental_digest(epoch_id)
        passed = replay_digest == expected_digest
        event = {
            "epoch_id": epoch_id,
            "epoch_digest": expected_digest,
            "checkpoint_digest": expected_digest,
            "replay_digest": replay_digest,
            "replay_passed": passed,
        }
        self.ledger.append_event("ReplayVerificationEvent", event)
        return event


__all__ = ["ReplayVerifier"]
