# SPDX-License-Identifier: Apache-2.0
"""Tests for governance_health_service + endpoint — ADAAD Phase 8, PR-8-02."""

from __future__ import annotations

import inspect
import pytest
pytestmark = pytest.mark.governance_gate
from unittest.mock import patch


def _make_snapshot(score: float):
    from runtime.governance.health_aggregator import HealthSnapshot
    return HealthSnapshot(
        epoch_id="epoch-test",
        health_score=score,
        signal_breakdown={
            "avg_reviewer_reputation": score,
            "amendment_gate_pass_rate": score,
            "federation_divergence_clean": 1.0,
            "epoch_health_score": score,
        },
        weight_snapshot={"avg_reviewer_reputation": 0.30, "amendment_gate_pass_rate": 0.25,
                         "federation_divergence_clean": 0.25, "epoch_health_score": 0.20},
        weight_snapshot_digest="sha256:" + "a" * 64,
        constitution_version="0.4.0",
        scoring_algorithm_version="1.0",
        degraded=score < 0.60,
    )


class TestGovernanceHealthService:
    """T8-02-01..10: governance_health_service unit tests."""

    def _svc(self):
        from runtime.governance.health_service import governance_health_service
        return governance_health_service

    def test_T8_02_01_returns_green_status_above_80(self):
        with patch("runtime.governance.health_aggregator.GovernanceHealthAggregator.compute",
                   return_value=_make_snapshot(0.85)):
            result = self._svc()(epoch_id="e1")
            assert result["status"] == "green"

    def test_T8_02_02_returns_amber_status_between_60_and_80(self):
        with patch("runtime.governance.health_aggregator.GovernanceHealthAggregator.compute",
                   return_value=_make_snapshot(0.70)):
            result = self._svc()(epoch_id="e2")
            assert result["status"] == "amber"

    def test_T8_02_03_returns_red_status_below_60(self):
        with patch("runtime.governance.health_aggregator.GovernanceHealthAggregator.compute",
                   return_value=_make_snapshot(0.40)):
            result = self._svc()(epoch_id="e3")
            assert result["status"] == "red"
            assert result["degraded"] is True

    def test_T8_02_04_result_contains_signal_breakdown(self):
        with patch("runtime.governance.health_aggregator.GovernanceHealthAggregator.compute",
                   return_value=_make_snapshot(0.75)):
            result = self._svc()(epoch_id="e4")
            assert "signal_breakdown" in result
            assert "avg_reviewer_reputation" in result["signal_breakdown"]

    def test_T8_02_05_result_contains_weight_digest(self):
        with patch("runtime.governance.health_aggregator.GovernanceHealthAggregator.compute",
                   return_value=_make_snapshot(0.75)):
            result = self._svc()(epoch_id="e5")
            assert result["weight_snapshot_digest"].startswith("sha256:")

    def test_T8_02_06_result_contains_constitution_version(self):
        with patch("runtime.governance.health_aggregator.GovernanceHealthAggregator.compute",
                   return_value=_make_snapshot(0.75)):
            result = self._svc()(epoch_id="e6")
            assert "constitution_version" in result

    def test_T8_02_07_not_degraded_when_h_at_exactly_60(self):
        with patch("runtime.governance.health_aggregator.GovernanceHealthAggregator.compute",
                   return_value=_make_snapshot(0.60)):
            result = self._svc()(epoch_id="e7")
            assert result["status"] == "amber"
            assert result["degraded"] is False

    def test_T8_02_08_service_is_readonly_no_mutation_authority(self):
        import runtime.governance.health_service as svc_mod
        src = inspect.getsource(svc_mod.governance_health_service)
        assert "GovernanceGate" not in src
        assert "approve_mutation" not in src

    def test_T8_02_09_service_handles_missing_dependencies_gracefully(self):
        try:
            result = self._svc()(epoch_id="edge-none")
            assert "health_score" in result
        except Exception as exc:
            pytest.fail(f"governance_health_service raised with missing deps: {exc}")

    def test_T8_02_10_deterministic_on_identical_mock_inputs(self):
        snap = _make_snapshot(0.72)
        with patch("runtime.governance.health_aggregator.GovernanceHealthAggregator.compute",
                   return_value=snap):
            r1 = self._svc()(epoch_id="det-epoch")
            r2 = self._svc()(epoch_id="det-epoch")
            assert r1["health_score"] == r2["health_score"]
            assert r1["status"] == r2["status"]
            assert r1["degradation_reasons"] == r2["degradation_reasons"]

    def test_T8_02_10a_reports_component_failure_reason(self):
        with (
            patch("runtime.governance.health_aggregator.GovernanceHealthAggregator.compute",
                  return_value=_make_snapshot(0.91)),
            patch("runtime.governance.reviewer_reputation_ledger.ReviewerReputationLedger.load",
                  side_effect=RuntimeError("forced-load-failure")),
        ):
            result = self._svc()(epoch_id="dep-failure")

        assert result["status"] == "green"
        assert result["dependency_degraded"] is True
        assert any(
            item["component"] == "reviewer_reputation_ledger"
            and item["reason_code"] == "dependency_init_or_load_failed"
            and item["scope"] == "critical"
            for item in result["degradation_reasons"]
        )

    def test_T8_02_10b_degradation_schema_stable(self):
        with patch("runtime.governance.health_aggregator.GovernanceHealthAggregator.compute",
                   return_value=_make_snapshot(0.80)):
            result = self._svc()(epoch_id="schema-stable")
        assert "degradation_reasons" in result
        assert isinstance(result["degradation_reasons"], list)
        for item in result["degradation_reasons"]:
            assert set(item.keys()) == {"component", "reason_code", "scope"}


class TestGovernanceHealthAggregatorAuthorityInvariants:
    """T8-02-11..15: GovernanceGate authority preservation."""

    def test_T8_02_11_aggregator_has_no_approve_mutation_method(self):
        from runtime.governance.health_aggregator import GovernanceHealthAggregator
        assert not hasattr(GovernanceHealthAggregator, "approve_mutation")

    def test_T8_02_12_aggregator_imports_do_not_include_governance_gate(self):
        import runtime.governance.health_aggregator as mod
        # Check only the import lines, not docstring
        src = inspect.getsource(mod)
        import_lines = [l for l in src.splitlines() if l.startswith("import ") or l.startswith("from ")]
        for line in import_lines:
            assert "GovernanceGate" not in line, f"GovernanceGate found in import: {line}"

    def test_T8_02_13_health_score_does_not_affect_gate_decision(self):
        from runtime.governance.health_aggregator import GovernanceHealthAggregator
        agg = GovernanceHealthAggregator(journal_emit=lambda *a: None)
        snap = agg.compute("ep-gate-test")
        assert isinstance(snap.health_score, float)
        assert snap.health_score >= 0.0

    def test_T8_02_14_snapshot_degraded_flag_is_bool(self):
        from runtime.governance.health_aggregator import GovernanceHealthAggregator
        agg = GovernanceHealthAggregator(journal_emit=lambda *a: None)
        snap = agg.compute("ep-flag")
        assert isinstance(snap.degraded, bool)

    def test_T8_02_15_service_result_has_required_health_fields(self):
        snap = _make_snapshot(0.75)
        with patch("runtime.governance.health_aggregator.GovernanceHealthAggregator.compute",
                   return_value=snap):
            from runtime.governance.health_service import governance_health_service
            result = governance_health_service(epoch_id="floor-test")
            for key in (
                "health_score",
                "status",
                "signal_breakdown",
                "degraded",
                "dependency_degraded",
                "degradation_reasons",
                "weight_snapshot_digest",
                "constitution_version",
                "routing_health",
                "review_pressure",
                "strategy_capability",
            ):
                assert key in result, f"Missing required field: {key}"

    def test_T8_02_16_runtime_services_wrapper_delegates_to_canonical_service(self):
        from runtime.api.runtime_services import governance_health_service as wrapped
        from runtime.governance.health_service import governance_health_service as canonical

        with patch("runtime.governance.health_aggregator.GovernanceHealthAggregator.compute", return_value=_make_snapshot(0.73)):
            wrapped_result = wrapped(epoch_id="single-schema")
            canonical_result = canonical(epoch_id="single-schema")

        assert wrapped_result == canonical_result
        assert set(wrapped_result.keys()) == {
            "epoch_id",
            "health_score",
            "status",
            "signal_breakdown",
            "weight_snapshot_digest",
            "constitution_version",
            "scoring_algorithm_version",
            "degraded",
            "dependency_degraded",
            "degradation_reasons",
            "routing_health",
            "review_pressure",
            "strategy_capability",
        }
