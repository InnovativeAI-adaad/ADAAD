# SPDX-License-Identifier: Apache-2.0
"""Promotion lifecycle state machine used by mutation governance."""

from __future__ import annotations

from enum import Enum


class PromotionState(Enum):
    PROPOSED = "proposed"
    CERTIFIED = "certified"
    ACTIVATED = "activated"
    REJECTED = "rejected"


_ALLOWED_TRANSITIONS: dict[PromotionState, frozenset[PromotionState]] = {
    PromotionState.PROPOSED: frozenset({PromotionState.CERTIFIED, PromotionState.REJECTED}),
    PromotionState.CERTIFIED: frozenset({PromotionState.ACTIVATED, PromotionState.REJECTED}),
    PromotionState.ACTIVATED: frozenset(),
    PromotionState.REJECTED: frozenset(),
}


def can_transition(current: PromotionState, nxt: PromotionState) -> bool:
    return nxt in _ALLOWED_TRANSITIONS[current]


def require_transition(current: PromotionState, nxt: PromotionState) -> None:
    if not can_transition(current, nxt):
        raise ValueError(f"invalid promotion transition: {current.value} -> {nxt.value}")


__all__ = ["PromotionState", "can_transition", "require_transition"]
