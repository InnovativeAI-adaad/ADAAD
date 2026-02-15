# SPDX-License-Identifier: Apache-2.0

import pytest

from runtime.evolution.promotion_state_machine import PromotionState, can_transition, canary_stage_definitions, require_transition


def test_valid_transitions() -> None:
    assert can_transition(PromotionState.PROPOSED, PromotionState.CERTIFIED)
    assert can_transition(PromotionState.CERTIFIED, PromotionState.ACTIVATED)


def test_invalid_transition_raises() -> None:
    with pytest.raises(ValueError):
        require_transition(PromotionState.ACTIVATED, PromotionState.PROPOSED)


def test_default_canary_stage_definitions_are_deterministic() -> None:
    first = canary_stage_definitions()
    second = canary_stage_definitions()
    assert first == second
    first[0]["stage_id"] = "mutated"
    assert canary_stage_definitions()[0]["stage_id"] == "canary_small"
