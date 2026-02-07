# SPDX-License-Identifier: Apache-2.0

import os

from runtime.constitution import determine_tier, get_forced_tier, Tier


def test_force_tier_override() -> None:
    original = os.environ.get("ADAAD_FORCE_TIER")
    os.environ["ADAAD_FORCE_TIER"] = "SANDBOX"
    try:
        assert get_forced_tier() == Tier.SANDBOX
        assert determine_tier("runtime.core") == Tier.SANDBOX
    finally:
        if original is None:
            os.environ.pop("ADAAD_FORCE_TIER", None)
        else:
            os.environ["ADAAD_FORCE_TIER"] = original
