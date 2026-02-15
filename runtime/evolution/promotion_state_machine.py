# SPDX-License-Identifier: Apache-2.0
"""Promotion lifecycle state machine used by mutation governance."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List


class PromotionState(Enum):
    PROPOSED = "proposed"
    CERTIFIED = "certified"
    ACTIVATED = "activated"
    REJECTED = "rejected"


_DEFAULT_CANARY_STAGES: tuple[dict[str, Any], ...] = (
    {
        "stage_id": "canary_small",
        "cohort_ids": ["cohort_a", "cohort_b"],
        "rollback_threshold": 1,
        "halt_on_fail": True,
    },
    {
        "stage_id": "canary_medium",
        "cohort_ids": ["cohort_c", "cohort_d"],
        "rollback_threshold": 2,
        "halt_on_fail": True,
    },
)


def canary_stage_definitions() -> List[Dict[str, Any]]:
    """Return deterministic default canary stage definitions."""
    return [dict(stage, cohort_ids=list(stage.get("cohort_ids") or [])) for stage in _DEFAULT_CANARY_STAGES]


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


__all__ = ["PromotionState", "can_transition", "require_transition", "canary_stage_definitions"]
