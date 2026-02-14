# SPDX-License-Identifier: Apache-2.0
"""Deterministic checkpoint event helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class EpochCheckpointEvent:
    epoch_id: str
    checkpoint_id: str
    checkpoint_hash: str
    prev_checkpoint_hash: str
    epoch_digest: str
    baseline_digest: str
    mutation_count: int
    promotion_event_count: int
    scoring_event_count: int
    entropy_policy_hash: str
    promotion_policy_hash: str
    evidence_hash: str
    sandbox_policy_hash: str
    created_at: str

    def to_payload(self) -> Dict[str, Any]:
        return asdict(self)


__all__ = ["EpochCheckpointEvent"]
