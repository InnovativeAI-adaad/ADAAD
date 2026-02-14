# SPDX-License-Identifier: Apache-2.0

import pytest

from runtime.evolution.promotion_state_machine import PromotionState, can_transition, require_transition


def test_valid_transitions() -> None:
    assert can_transition(PromotionState.PROPOSED, PromotionState.CERTIFIED)
    assert can_transition(PromotionState.CERTIFIED, PromotionState.ACTIVATED)


def test_invalid_transition_raises() -> None:
    with pytest.raises(ValueError):
        require_transition(PromotionState.ACTIVATED, PromotionState.PROPOSED)
