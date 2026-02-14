# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from runtime.evolution.promotion_events import create_promotion_event, derive_event_id
from runtime.evolution.promotion_state_machine import PromotionState
from runtime.governance.foundation import SeededDeterminismProvider
from runtime.governance.foundation.hashing import ZERO_HASH


def test_event_id_determinism() -> None:
    first = derive_event_id("mut-1", PromotionState.CERTIFIED, PromotionState.ACTIVATED, None)
    second = derive_event_id("mut-1", PromotionState.CERTIFIED, PromotionState.ACTIVATED, None)
    assert first == second


def test_promotion_event_hash_chain() -> None:
    provider = SeededDeterminismProvider(seed="promo")
    event_one = create_promotion_event(
        mutation_id="mut-1",
        epoch_id="epoch-1",
        from_state=PromotionState.PROPOSED,
        to_state=PromotionState.CERTIFIED,
        actor_type="SYSTEM",
        actor_id="engine",
        policy_version="v1.0.0",
        payload={"score": 0.7},
        prev_event_hash=None,
        provider=provider,
        replay_mode="strict",
    )
    event_two = create_promotion_event(
        mutation_id="mut-1",
        epoch_id="epoch-1",
        from_state=PromotionState.CERTIFIED,
        to_state=PromotionState.ACTIVATED,
        actor_type="SYSTEM",
        actor_id="engine",
        policy_version="v1.0.0",
        payload={"score": 0.9},
        prev_event_hash=event_one["event_hash"],
        provider=provider,
        replay_mode="strict",
    )

    assert event_one["prev_event_hash"] == ZERO_HASH
    assert event_two["prev_event_hash"] == event_one["event_hash"]
    assert event_one["event_hash"].startswith("sha256:")
    assert event_two["event_hash"].startswith("sha256:")
