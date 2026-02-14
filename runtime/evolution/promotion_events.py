# SPDX-License-Identifier: Apache-2.0
"""Deterministic promotion event creation with hash chaining."""

from __future__ import annotations

from typing import Any, Dict, Optional

from runtime.evolution.promotion_state_machine import PromotionState
from runtime.governance.foundation import (
    RuntimeDeterminismProvider,
    default_provider,
    require_replay_safe_provider,
    sha256_prefixed_digest,
)
from runtime.governance.foundation.hashing import ZERO_HASH


def derive_event_id(
    mutation_id: str,
    from_state: PromotionState,
    to_state: PromotionState,
    prev_event_hash: Optional[str],
) -> str:
    """Derive deterministic event ID from transition material (timestamp-independent)."""
    base = f"{mutation_id}:{from_state.value}:{to_state.value}:{prev_event_hash or 'root'}"
    digest = sha256_prefixed_digest(base)
    return f"evt_{digest.split(':', 1)[1][:16]}"


def create_promotion_event(
    *,
    mutation_id: str,
    epoch_id: str,
    from_state: PromotionState,
    to_state: PromotionState,
    actor_type: str,
    actor_id: str,
    policy_version: str,
    payload: Dict[str, Any],
    prev_event_hash: Optional[str],
    provider: RuntimeDeterminismProvider | None = None,
    replay_mode: str = "off",
    recovery_tier: str | None = None,
) -> Dict[str, Any]:
    """Create immutable promotion event with deterministic hash chain."""
    runtime_provider = provider or default_provider()
    require_replay_safe_provider(runtime_provider, replay_mode=replay_mode, recovery_tier=recovery_tier)

    event_id = derive_event_id(mutation_id, from_state, to_state, prev_event_hash)
    event = {
        "event_id": event_id,
        "mutation_id": mutation_id,
        "epoch_id": epoch_id,
        "timestamp": runtime_provider.iso_now(),
        "from_state": from_state.value,
        "to_state": to_state.value,
        "actor": {"type": actor_type, "id": actor_id},
        "policy_version": policy_version,
        "payload": dict(payload),
        "prev_event_hash": prev_event_hash or ZERO_HASH,
    }

    hash_material = dict(event)
    hash_material.pop("timestamp", None)
    event["event_hash"] = sha256_prefixed_digest(hash_material)
    return event


__all__ = ["create_promotion_event", "derive_event_id"]
