# SPDX-License-Identifier: Apache-2.0

import pytest

from runtime.evolution.entropy_discipline import EntropyBudget, deterministic_token_with_budget


def test_entropy_budget_consumption() -> None:
    budget = EntropyBudget()
    token, updated = deterministic_token_with_budget("epoch-1", "mutation_1", budget=budget)
    assert isinstance(token, int)
    assert updated.random_samples == 1


def test_entropy_budget_exhaustion() -> None:
    budget = EntropyBudget(random_samples=101)
    with pytest.raises(RuntimeError, match="entropy_budget_exhausted"):
        deterministic_token_with_budget("epoch-1", "mutation_1", budget=budget)
