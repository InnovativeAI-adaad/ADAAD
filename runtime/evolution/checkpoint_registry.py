# SPDX-License-Identifier: Apache-2.0
"""Epoch checkpoint registry for deterministic governance evidence."""

from __future__ import annotations

from typing import Any, Dict

from runtime.evolution.checkpoint_events import EpochCheckpointEvent
from runtime.evolution.lineage_v2 import LineageLedgerV2
from runtime.governance.foundation import (
    RuntimeDeterminismProvider,
    ZERO_HASH,
    default_provider,
    require_replay_safe_provider,
    sha256_prefixed_digest,
)


class CheckpointRegistry:
    def __init__(
        self,
        ledger: LineageLedgerV2,
        *,
        provider: RuntimeDeterminismProvider | None = None,
        replay_mode: str = "off",
        recovery_tier: str | None = None,
        promotion_policy_hash: str = ZERO_HASH,
        entropy_policy_hash: str = ZERO_HASH,
        sandbox_policy_hash: str = ZERO_HASH,
    ) -> None:
        self.ledger = ledger
        self.provider = provider or default_provider()
        self.replay_mode = replay_mode
        self.recovery_tier = recovery_tier
        self.promotion_policy_hash = promotion_policy_hash
        self.entropy_policy_hash = entropy_policy_hash
        self.sandbox_policy_hash = sandbox_policy_hash

    def _latest_checkpoint_hash(self, epoch_id: str) -> str:
        latest = ZERO_HASH
        for entry in self.ledger.read_epoch(epoch_id):
            if entry.get("type") != "EpochCheckpointEvent":
                continue
            payload = entry.get("payload") or {}
            candidate = payload.get("checkpoint_hash")
            if isinstance(candidate, str) and candidate:
                latest = candidate
        return latest

    def create_checkpoint(self, epoch_id: str) -> Dict[str, Any]:
        require_replay_safe_provider(self.provider, replay_mode=self.replay_mode, recovery_tier=self.recovery_tier)
        epoch_events = self.ledger.read_epoch(epoch_id)
        mutation_count = sum(1 for e in epoch_events if e.get("type") == "MutationBundleEvent")
        promotion_count = sum(1 for e in epoch_events if e.get("type") == "PromotionEvent")
        scoring_count = sum(1 for e in epoch_events if e.get("type") == "ScoringEvent")
        sandbox_evidence = [
            (e.get("payload") or {}).get("evidence_hash")
            for e in epoch_events
            if e.get("type") == "SandboxEvidenceEvent"
        ]
        evidence_hash = sha256_prefixed_digest(sorted(v for v in sandbox_evidence if isinstance(v, str)))

        epoch_digest = self.ledger.get_epoch_digest(epoch_id) or "sha256:0"
        baseline_digest = self.ledger.compute_incremental_epoch_digest(epoch_id)
        prev_checkpoint_hash = self._latest_checkpoint_hash(epoch_id)
        checkpoint_material = {
            "epoch_id": epoch_id,
            "epoch_digest": epoch_digest,
            "baseline_digest": baseline_digest,
            "mutation_count": mutation_count,
            "promotion_event_count": promotion_count,
            "scoring_event_count": scoring_count,
            "promotion_policy_hash": self.promotion_policy_hash,
            "entropy_policy_hash": self.entropy_policy_hash,
            "evidence_hash": evidence_hash,
            "sandbox_policy_hash": self.sandbox_policy_hash,
            "prev_checkpoint_hash": prev_checkpoint_hash,
        }
        checkpoint_hash = sha256_prefixed_digest(checkpoint_material)
        checkpoint_id = f"chk_{checkpoint_hash.split(':', 1)[1][:16]}"
        event = EpochCheckpointEvent(
            epoch_id=epoch_id,
            checkpoint_id=checkpoint_id,
            checkpoint_hash=checkpoint_hash,
            prev_checkpoint_hash=prev_checkpoint_hash,
            epoch_digest=epoch_digest,
            baseline_digest=baseline_digest,
            mutation_count=mutation_count,
            promotion_event_count=promotion_count,
            scoring_event_count=scoring_count,
            entropy_policy_hash=self.entropy_policy_hash,
            promotion_policy_hash=self.promotion_policy_hash,
            evidence_hash=evidence_hash,
            sandbox_policy_hash=self.sandbox_policy_hash,
            created_at=self.provider.iso_now(),
        )
        payload = event.to_payload()
        self.ledger.append_event("EpochCheckpointEvent", payload)
        return payload


__all__ = ["CheckpointRegistry"]
