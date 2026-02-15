# SPDX-License-Identifier: Apache-2.0

from unittest.mock import patch

from runtime.governance.event_taxonomy import (
    EVENT_TYPE_CONSTITUTION_ESCALATION,
    EVENT_TYPE_OPERATOR_OVERRIDE,
    EVENT_TYPE_REPLAY_DIVERGENCE,
    EVENT_TYPE_REPLAY_FAILURE,
    normalize_event_type,
)
from runtime.governance.policy_artifact import GovernanceModelMetadata, GovernancePolicy, GovernanceThresholds
from ui.aponi_dashboard import AponiDashboard


def _handler_class():
    dashboard = AponiDashboard(host="127.0.0.1", port=0)
    return dashboard._build_handler()


def _test_policy() -> GovernancePolicy:
    return GovernancePolicy(
        schema_version="governance_policy_v1",
        model=GovernanceModelMetadata(name="governance_health", version="v1.0.0"),
        determinism_window=200,
        mutation_rate_window_sec=3600,
        thresholds=GovernanceThresholds(determinism_pass=0.98, determinism_warn=0.90),
        fingerprint="sha256:testpolicy",
    )


def test_governance_health_model_is_formalized_and_deterministic() -> None:
    handler = _handler_class()
    with patch("ui.aponi_dashboard.GOVERNANCE_POLICY", _test_policy()):
        with patch.object(handler, "_rolling_determinism_score", return_value={"rolling_score": 0.99}):
            with patch.object(
                handler,
                "_mutation_rate_state",
                return_value={"ok": True, "max_mutations_per_hour": 60.0, "rate_per_hour": 6.0},
            ):
                with patch("ui.aponi_dashboard.metrics.tail", return_value=[]):
                    snapshot = handler._intelligence_snapshot()

    assert snapshot["governance_health"] == "PASS"
    assert snapshot["model_version"] == "v1.0.0"
    assert snapshot["policy_fingerprint"] == "sha256:testpolicy"
    assert snapshot["model_inputs"]["threshold_pass"] == 0.98
    assert snapshot["model_inputs"]["threshold_warn"] == 0.90


def test_governance_health_applies_warn_and_block_thresholds() -> None:
    handler = _handler_class()
    with patch("ui.aponi_dashboard.GOVERNANCE_POLICY", _test_policy()):
        with patch.object(
            handler,
            "_mutation_rate_state",
            return_value={"ok": True, "max_mutations_per_hour": 60.0, "rate_per_hour": 6.0},
        ):
            with patch("ui.aponi_dashboard.metrics.tail", return_value=[]):
                with patch.object(handler, "_rolling_determinism_score", return_value={"rolling_score": 0.93}):
                    warn_snapshot = handler._intelligence_snapshot()
                with patch.object(handler, "_rolling_determinism_score", return_value={"rolling_score": 0.85}):
                    block_snapshot = handler._intelligence_snapshot()

    assert warn_snapshot["governance_health"] == "WARN"
    assert block_snapshot["governance_health"] == "BLOCK"


def test_replay_divergence_counts_recent_replay_events() -> None:
    handler = _handler_class()
    entries = [
        {"event": "replay_divergence_detected"},
        {"event_type": EVENT_TYPE_REPLAY_FAILURE},
        {"event": "fitness_scored"},
    ]
    with patch("ui.aponi_dashboard.metrics.tail", return_value=entries):
        summary = handler._replay_divergence()

    assert summary["window"] == 200
    assert summary["divergence_event_count"] == 2
    assert len(summary["latest_events"]) == 2


def test_constitution_escalations_supports_canonical_and_legacy_names() -> None:
    handler = _handler_class()
    entries = [
        {"event_type": EVENT_TYPE_CONSTITUTION_ESCALATION},
        {"event": "constitution_escalated"},
        {"event": "constitution escalation critical"},
    ]

    assert handler._constitution_escalations(entries) == 3


def test_risk_summary_uses_normalized_event_types_with_legacy_fallbacks() -> None:
    handler = _handler_class()
    entries = [
        {"event": "manual_override"},
        {"event_type": EVENT_TYPE_OPERATOR_OVERRIDE},
        {"event": "replay_check_failed"},
        {"event_type": EVENT_TYPE_REPLAY_FAILURE},
    ]
    intelligence = {
        "constitution_escalations_last_100": 10,
        "mutation_aggression_index": 0.25,
        "determinism_score": 0.95,
    }
    with patch.object(handler, "_intelligence_snapshot", return_value=intelligence):
        with patch("ui.aponi_dashboard.metrics.tail", return_value=entries):
            summary = handler._risk_summary()

    assert summary["escalation_frequency"] == 0.1
    assert summary["override_frequency"] == 0.01
    assert summary["replay_failure_rate"] == 0.01


def test_normalize_event_type_maps_legacy_and_canonical_fields() -> None:
    assert normalize_event_type({"event": "constitution_escalated"}) == EVENT_TYPE_CONSTITUTION_ESCALATION
    assert normalize_event_type({"event": "replay_divergence_detected"}) == EVENT_TYPE_REPLAY_DIVERGENCE
    assert normalize_event_type({"event_type": EVENT_TYPE_OPERATOR_OVERRIDE}) == EVENT_TYPE_OPERATOR_OVERRIDE


def test_normalize_event_type_prefers_explicit_event_type() -> None:
    entry = {"event_type": EVENT_TYPE_REPLAY_FAILURE, "event": "manual_override"}

    assert normalize_event_type(entry) == EVENT_TYPE_REPLAY_FAILURE


def test_semantic_drift_classifier_assigns_expected_categories() -> None:
    handler = _handler_class()

    assert handler._semantic_drift_class_for_key("constitution.policy_hash") == "governance_drift"
    assert handler._semantic_drift_class_for_key("policy/override") == "governance_drift"
    assert handler._semantic_drift_class_for_key("traits.error_handler") == "trait_drift"
    assert handler._semantic_drift_class_for_key("runtime/checkpoints/latest") == "runtime_artifact_drift"
    assert handler._semantic_drift_class_for_key("config.rate_limit") == "config_drift"


def test_replay_diff_returns_semantic_drift_with_stable_ordering() -> None:
    epoch = {
        "bundles": [{"id": "b-1"}],
        "initial_state": {
            "traits.error_handler": "off",
            "config.max_mutations": 60,
            "constitution.policy_hash": "abc",
            "runtime.checkpoint.last": "cp-1",
            "zeta": "legacy",
        },
        "final_state": {
            "config.max_mutations": 30,
            "traits.error_handler": "on",
            "constitution.policy_hash": "def",
            "runtime.checkpoint.last": "cp-2",
            "alpha": "new-value",
        },
    }
    with patch("ui.aponi_dashboard.ReplayEngine") as replay_mock:
        replay_mock.return_value.reconstruct_epoch.return_value = epoch
        handler = _handler_class()
        payload = handler._replay_diff("epoch-1")

    assert payload["ok"] is True
    assert payload["changed_keys"] == [
        "config.max_mutations",
        "constitution.policy_hash",
        "runtime.checkpoint.last",
        "traits.error_handler",
    ]
    assert payload["added_keys"] == ["alpha"]
    assert payload["removed_keys"] == ["zeta"]
    assert list(payload["semantic_drift"]["per_key"].keys()) == [
        "alpha",
        "config.max_mutations",
        "constitution.policy_hash",
        "runtime.checkpoint.last",
        "traits.error_handler",
        "zeta",
    ]
    assert payload["semantic_drift"]["class_counts"] == {
        "config_drift": 1,
        "governance_drift": 1,
        "trait_drift": 1,
        "runtime_artifact_drift": 1,
        "uncategorized_drift": 2,
    }


def test_user_console_uses_external_script_for_csp_compatibility() -> None:
    handler = _handler_class()
    html = handler._user_console()

    assert '<script src="/ui/aponi.js"></script>' in html
    assert "id=\"instability\"" in html
    assert "paint('replay', '/replay/divergence')" in handler._user_console_js()


def test_risk_instability_uses_weighted_deterministic_formula() -> None:
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
                payload = handler._risk_instability()

    # drift density = 3/4 = 0.75
    # instability = 0.35*0.75 + 0.25*0.1 + 0.20*0.2 + 0.20*0.05 = 0.3375
    assert payload["instability_index"] == 0.3375
    assert payload["instability_velocity"] == 0.0
    assert payload["instability_acceleration"] == 0.0
    assert payload["inputs"]["timeline_window"] == 4
    assert payload["inputs"]["semantic_drift_density"] == 0.75


def test_risk_instability_defaults_to_zero_without_timeline() -> None:
    handler = _handler_class()
    risk_summary = {
        "escalation_frequency": 0.0,
        "override_frequency": 0.0,
        "replay_failure_rate": 0.0,
        "aggression_trend_variance": 0.0,
        "determinism_drift_index": 0.0,
    }
    with patch.object(handler, "_risk_summary", return_value=risk_summary):
        with patch.object(handler, "_evolution_timeline", return_value=[]):
            with patch.object(handler, "_semantic_drift_weighted_density", return_value={"density": 0.0, "window": 0, "considered": 0}):
                payload = handler._risk_instability()

    assert payload["instability_index"] == 0.0
    assert payload["instability_velocity"] == 0.0
    assert payload["instability_acceleration"] == 0.0
    assert payload["inputs"]["timeline_window"] == 0


def test_risk_instability_reports_velocity_and_acceleration() -> None:
    handler = _handler_class()
    risk_summary = {
        "escalation_frequency": 0.0,
        "override_frequency": 0.0,
        "replay_failure_rate": 0.0,
        "aggression_trend_variance": 0.0,
        "determinism_drift_index": 0.0,
    }
    # three fixed windows of 20 entries: densities 0.25, 0.5, 0.75
    timeline = (
        [{"risk_tier": "low"}] * 15 + [{"risk_tier": "high"}] * 5
        + [{"risk_tier": "low"}] * 10 + [{"risk_tier": "critical"}] * 10
        + [{"risk_tier": "low"}] * 5 + [{"risk_tier": "unknown"}] * 15
    )
    with patch.object(handler, "_risk_summary", return_value=risk_summary):
        with patch.object(handler, "_evolution_timeline", return_value=timeline):
            with patch.object(handler, "_semantic_drift_weighted_density", return_value={"density": 0.0, "window": 10, "considered": 0}):
                payload = handler._risk_instability()

    assert payload["inputs"]["momentum_window"] == 20
    assert payload["instability_velocity"] == 0.25
    assert payload["instability_acceleration"] == 0.0


def test_policy_simulation_compares_current_and_candidate_policy() -> None:
    handler = _handler_class()
    with patch.object(handler, "_mutation_rate_state", return_value={"ok": True}):
        with patch.object(handler, "_intelligence_snapshot", return_value={"determinism_score": 0.91}):
            payload = handler._policy_simulation({"policy": ["governance_policy_v1.json"]})

    assert payload["ok"] is True
    assert payload["current_policy"]["health"] in {"PASS", "WARN", "BLOCK"}
    assert payload["simulated_policy"]["health"] in {"PASS", "WARN", "BLOCK"}


def test_policy_simulation_rejects_invalid_score_input() -> None:
    handler = _handler_class()
    payload = handler._policy_simulation({"determinism_score": ["not-a-number"]})

    assert payload["ok"] is False
    assert payload["error"] == "invalid_determinism_score"


def test_epoch_chain_anchor_is_emitted_in_replay_diff() -> None:
    epoch = {
        "bundles": [{"id": "b-1"}],
        "initial_state": {"config.max_mutations": 60},
        "final_state": {"config.max_mutations": 30},
    }
    with patch("ui.aponi_dashboard.ReplayEngine") as replay_mock:
        replay_mock.return_value.reconstruct_epoch.return_value = epoch
        handler = _handler_class()
        with patch.object(handler, "_evolution_timeline", return_value=[{"epoch": "epoch-1", "mutation_id": "m1", "timestamp": "t1", "risk_tier": "low", "fitness_score": 0.5}]):
            payload = handler._replay_diff("epoch-1")

    assert payload["ok"] is True
    assert "anchor" in payload["epoch_chain_anchor"]
    assert payload["epoch_chain_anchor"]["anchor"].startswith("sha256:")


def test_velocity_spike_anomaly_flag_sets_on_large_velocity() -> None:
    handler = _handler_class()
    risk_summary = {
        "escalation_frequency": 0.0,
        "override_frequency": 0.0,
        "replay_failure_rate": 0.0,
        "aggression_trend_variance": 0.0,
        "determinism_drift_index": 0.0,
    }
    timeline = ([{"risk_tier": "low"}] * 20) + ([{"risk_tier": "low"}] * 20) + ([{"risk_tier": "high"}] * 20)
    with patch.object(handler, "_risk_summary", return_value=risk_summary):
        with patch.object(handler, "_evolution_timeline", return_value=timeline):
            with patch.object(handler, "_semantic_drift_weighted_density", return_value={"density": 0.0, "window": 10, "considered": 0}):
                payload = handler._risk_instability()

    assert payload["instability_velocity"] == 1.0
    assert payload["velocity_spike_anomaly"] is True
    assert payload["velocity_anomaly_mode"] == "absolute_delta"
    assert payload["confidence_interval"]["sample_size"] == 20


def test_alerts_evaluate_emits_expected_severity_buckets() -> None:
    handler = _handler_class()
    instability_payload = {
        "instability_index": 0.72,
        "instability_velocity": 0.3,
        "velocity_spike_anomaly": True,
        "velocity_anomaly_mode": "absolute_delta",
    }
    risk_summary = {
        "escalation_frequency": 0.0,
        "override_frequency": 0.0,
        "replay_failure_rate": 0.06,
        "aggression_trend_variance": 0.0,
        "determinism_drift_index": 0.0,
    }

    with patch.object(handler, "_risk_instability", return_value=instability_payload):
        with patch.object(handler, "_risk_summary", return_value=risk_summary):
            alerts = handler._alerts_evaluate()

    assert alerts["critical"][0]["code"] == "instability_critical"
    assert alerts["warning"][0]["code"] == "replay_failure_warning"
    assert alerts["info"][0]["code"] == "instability_velocity_spike"


def test_alerts_evaluate_returns_empty_when_below_thresholds() -> None:
    handler = _handler_class()
    with patch.object(
        handler,
        "_risk_instability",
        return_value={"instability_index": 0.1, "instability_velocity": 0.0, "velocity_spike_anomaly": False},
    ):
        with patch.object(handler, "_risk_summary", return_value={"replay_failure_rate": 0.0}):
            alerts = handler._alerts_evaluate()

    assert alerts["critical"] == []
    assert alerts["warning"] == []
    assert alerts["info"] == []
