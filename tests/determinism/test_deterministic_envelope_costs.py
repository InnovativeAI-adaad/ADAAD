# SPDX-License-Identifier: Apache-2.0

import pytest

from runtime.governance.deterministic_envelope import (
    ENTROPY_COSTS,
    EntropyBudgetExceeded,
    EntropySource,
    charge_entropy,
    deterministic_envelope,
)


def test_provider_source_has_non_zero_cost() -> None:
    assert ENTROPY_COSTS[EntropySource.PROVIDER] == 1


def test_provider_charges_contribute_to_budget_exhaustion() -> None:
    with deterministic_envelope(epoch_id="epoch-provider", budget=2) as ledger:
        charge_entropy(EntropySource.PROVIDER, "start")
        charge_entropy(EntropySource.PROVIDER, "signature")
        with pytest.raises(EntropyBudgetExceeded, match="entropy_budget_exceeded"):
            charge_entropy(EntropySource.PROVIDER, "impact")
        assert ledger.consumed == 2
        assert ledger.overflow is True
