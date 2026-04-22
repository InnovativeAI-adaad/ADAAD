# SPDX-License-Identifier: Apache-2.0
"""Tests for Constitution v0.4.0 — ADAAD Phase 8, PR-8-03."""

from __future__ import annotations

import json
import pytest
pytestmark = pytest.mark.governance_gate


def test_T8_03_01_constitution_version_is_0_4_0():
    from runtime.constitution import CONSTITUTION_VERSION
    assert CONSTITUTION_VERSION == "1.0.0"  # updated: constitution at v1.0.0 Phase 150+


def test_T8_03_02_governance_health_floor_rule_present_in_yaml():
    import json
    from pathlib import Path
    yaml_path = Path("runtime/governance/constitution.yaml")
    data = json.loads(yaml_path.read_text())
    rules = data.get("rules", [])
    names = [r.get("name") for r in rules]
    assert "governance_health_floor" in names


def test_T8_03_03_governance_health_floor_is_advisory():
    from pathlib import Path
    data = json.loads(Path("runtime/governance/constitution.yaml").read_text())
    rule = next(r for r in data["rules"] if r["name"] == "governance_health_floor")
    assert rule["severity"] == "advisory"


def test_T8_03_04_governance_health_floor_is_enabled():
    from pathlib import Path
    data = json.loads(Path("runtime/governance/constitution.yaml").read_text())
    rule = next(r for r in data["rules"] if r["name"] == "governance_health_floor")
    assert rule["enabled"] is True


def test_T8_03_05_governance_health_floor_has_four_signals():
    from pathlib import Path
    data = json.loads(Path("runtime/governance/constitution.yaml").read_text())
    rule = next(r for r in data["rules"] if r["name"] == "governance_health_floor")
    signals = rule.get("signals", [])
    assert len(signals) == 4
    assert "avg_reviewer_reputation" in signals
    assert "amendment_gate_pass_rate" in signals
    assert "federation_divergence_clean" in signals
    assert "epoch_health_score" in signals


def test_T8_03_06_governance_health_floor_degraded_threshold_is_0_60():
    from pathlib import Path
    data = json.loads(Path("runtime/governance/constitution.yaml").read_text())
    rule = next(r for r in data["rules"] if r["name"] == "governance_health_floor")
    assert rule.get("degraded_threshold") == pytest.approx(0.60)


def test_T8_03_07_reviewer_calibration_rule_still_present():
    from pathlib import Path
    data = json.loads(Path("runtime/governance/constitution.yaml").read_text())
    names = [r["name"] for r in data["rules"]]
    assert "reviewer_calibration" in names


def test_T8_03_08_constitution_version_propagates_to_health_snapshot():
    from runtime.governance.health_aggregator import GovernanceHealthAggregator
    from runtime.constitution import CONSTITUTION_VERSION
    agg = GovernanceHealthAggregator(journal_emit=lambda *a: None)
    snap = agg.compute("version-test")
    assert snap.constitution_version == CONSTITUTION_VERSION  # dynamic: always matches runtime.constitution


def test_T8_03_09_governance_gate_authority_invariant_documented_in_rule():
    from pathlib import Path
    data = json.loads(Path("runtime/governance/constitution.yaml").read_text())
    rule = next(r for r in data["rules"] if r["name"] == "governance_health_floor")
    reason = rule.get("reason", "")
    assert "GovernanceGate" in reason or "authority" in reason.lower()


def test_T8_03_10_constitution_yaml_is_valid_json():
    from pathlib import Path
    raw = Path("runtime/governance/constitution.yaml").read_text()
    parsed = json.loads(raw)  # must not raise
    assert isinstance(parsed, dict)
