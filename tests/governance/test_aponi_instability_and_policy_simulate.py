# SPDX-License-Identifier: Apache-2.0
# ruff: noqa: E402

"""
Module: test_aponi_instability_and_policy_simulate
Purpose: Validate deterministic instability outputs and policy simulate read-only guards.
Author: ADAAD / InnovativeAI-adaad
Integration points:
  - Imports from: ui.aponi_dashboard
  - Consumed by: pytest governance suite
  - Governance impact: low — verifies fail-closed, deterministic dashboard policy behavior
"""

from unittest.mock import patch
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ui.aponi_dashboard import AponiDashboard


def _handler_class():
    dashboard = AponiDashboard(host="127.0.0.1", port=0)
    return dashboard._build_handler()


def test_instability_calculation_is_deterministic() -> None:
    handler = _handler_class()
    risk_summary = {
        "escalation_frequency": 0.2,
        "override_frequency": 0.0,
        "replay_failure_rate": 0.1,
        "aggression_trend_variance": 0.0,
        "determinism_drift_index": 0.05,
    }
    timeline = [
        {"risk_tier": "high"},
        {"risk_tier": "critical"},
        {"risk_tier": "low"},
        {"risk_tier": "unknown"},
    ]

    with patch.object(handler, "_risk_summary", return_value=risk_summary):
        with patch.object(handler, "_evolution_timeline", return_value=timeline):
            with patch.object(handler, "_semantic_drift_weighted_density", return_value={"density": 0.75, "window": 4, "considered": 4}):
                first = handler._risk_instability()
                second = handler._risk_instability()

    assert first == second
    assert first["instability_index"] == 0.3375


def test_policy_simulate_blocks_mutation_flags() -> None:
    handler = _handler_class()

    payload = handler._policy_simulation({"mutate": ["true"]})

    assert payload == {"ok": False, "error": "read_only_endpoint", "blocked_flag": "mutate"}
