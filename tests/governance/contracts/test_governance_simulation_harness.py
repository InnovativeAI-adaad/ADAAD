# SPDX-License-Identifier: Apache-2.0

from runtime import constitution
from tools.simulate_governance_harness import run_simulation


def test_governance_simulation_harness_smoke() -> None:
    summary = run_simulation(count=10, tier=constitution.Tier.SANDBOX)
    assert summary.total_requests == 10
    assert summary.passed >= 0
    assert summary.unique_envelope_digests >= 1
