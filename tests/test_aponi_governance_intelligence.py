# SPDX-License-Identifier: Apache-2.0

from unittest.mock import patch

from ui.aponi_dashboard import AponiDashboard


def _handler_class():
    dashboard = AponiDashboard(host="127.0.0.1", port=0)
    return dashboard._build_handler()


def test_governance_health_model_is_formalized_and_deterministic() -> None:
    handler = _handler_class()
    with patch.object(handler, "_rolling_determinism_score", return_value={"rolling_score": 0.99}):
        with patch.object(handler, "_mutation_rate_state", return_value={"ok": True, "max_mutations_per_hour": 60.0, "rate_per_hour": 6.0}):
            with patch("ui.aponi_dashboard.metrics.tail", return_value=[]):
                snapshot = handler._intelligence_snapshot()

    assert snapshot["governance_health"] == "PASS"
    assert snapshot["model_version"] == "v1.0.0"
    assert snapshot["model_inputs"]["threshold_pass"] == 0.98
    assert snapshot["model_inputs"]["threshold_warn"] == 0.90


def test_replay_divergence_counts_recent_replay_events() -> None:
    handler = _handler_class()
    entries = [
        {"event": "replay_divergence_detected"},
        {"event": "replay_check_failed"},
        {"event": "fitness_scored"},
    ]
    with patch("ui.aponi_dashboard.metrics.tail", return_value=entries):
        summary = handler._replay_divergence()

    assert summary["window"] == 200
    assert summary["divergence_event_count"] == 2
    assert len(summary["latest_events"]) == 2


def test_user_console_uses_external_script_for_csp_compatibility() -> None:
    handler = _handler_class()
    html = handler._user_console()

    assert "<script src=\"/ui/aponi.js\"></script>" in html
    assert "paint('replay', '/replay/divergence')" in handler._user_console_js()
