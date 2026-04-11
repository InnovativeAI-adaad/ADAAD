# SPDX-License-Identifier: Apache-2.0

# ADAAD-LANE: endpoint-contracts

import json
from urllib import request as urlrequest
from unittest.mock import patch
from runtime.governance.event_taxonomy import (
    EVENT_TYPE_CONSTITUTION_ESCALATION,
    EVENT_TYPE_AGM_STEP_01,
    EVENT_TYPE_BUDGET_MODE_CHANGED,
    EVENT_TYPE_OPERATOR_OVERRIDE,
    EVENT_TYPE_REPLAY_DIVERGENCE,
    EVENT_TYPE_REPLAY_FAILURE,
    normalize_agm_step,
    normalize_event_type,
    validate_event_type_for_agm_step,
)
from runtime.governance.policy_artifact import GovernanceModelMetadata, GovernancePolicy, GovernanceThresholds
from ui import aponi_dashboard
from ui.aponi_dashboard import AponiDashboard, _skill_capability_matrix
import pytest
pytestmark = pytest.mark.regression_standard

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
def test_user_console_uses_external_script_for_csp_compatibility() -> None:
    handler = _handler_class()
    html = handler._user_console()
    script = handler._user_console_js()

    assert '<script src="/ui/aponi.js"></script>' in html
    assert "id=\"instability\"" in html
    assert "id=\"controlPanel\"" in html
    assert "id=\"controlStageLabel\"" in html
    assert "id=\"controlStageProgress\"" in html
    assert "paint('replay', '/replay/divergence')" in script
    assert "const STORAGE_KEY = 'aponi.control.panel.v1';" in script
    assert "const MODE_STORAGE_KEY = 'aponi.user.mode.v1';" in script
    assert "id=\"modeSwitcher\"" in html
    assert "metadata: { mode: selectedMode }" in script
    assert "reorderHomeCards(mode);" in script
    assert "const CONTROL_STATES = {" in script
    assert "function createControlStateMachine()" in script
    assert "failed: ['select', 'configure']" in script
    assert "function validateConfiguration(payload)" in script
    assert "window.aponiControlMachine = createControlStateMachine();" in script
    assert "const DRAFT_STORAGE_KEY = 'aponi.control.draft.v1';" in script
    assert "registerUndoAction({" in script
    assert "/control/queue/cancel" in script
    assert "/control/telemetry" in script
    assert "fetch('/control/capability-matrix'" in script
    assert "Promise.allSettled([" in script
    assert "statusLabel = response.ok ?" in script
    assert "const commandPayload = readCommandPayload();" in script
    assert "[HTTP ${response.status}]" in script
    assert "if (!response.ok) throw new Error(`endpoint returned HTTP ${response.status}`);" in script
    assert "Failed to load skill profiles:" in script
    assert "Agent ID is required before queue submission." in script
    assert "id=\"controlCapabilities\" class=\"floating-select\" multiple" in html
    assert "id=\"controlAbility\" class=\"floating-select\"" in html
    assert "id=\"controlTask\" class=\"floating-select\"" in html
    assert "id=\"controlGeneralPrompt\"" in html
    assert "id=\"controlPromptRun\"" in html
    assert "function ensureSelectOption(selectEl, value)" in script
    assert 'id="actionCardTemplate"' in html
    assert 'id="tasksActions"' in html
    assert 'id="insightsActions"' in html
    assert "function toCardModelFromTemplate(" in script
    assert "function toCardModelFromInsightRecommendation(" in script
    assert "function toCardModelFromHistoryRerun(" in script
    assert "cardElement.classList.add('executing');" in script
    assert "refreshActionCards()," in script
    assert "id=\"executionPanel\"" in html
    assert "id=\"executionSummary\"" in html
    assert "id=\"executionRaw\"" in html
    assert "Cancel action" in html
    assert "Fork action" in html
    assert "const EXECUTION_POLL_MS = 1500;" in script
    assert "Raw execution event payload" in html
    assert "endpoint_todo: '/control/execution (pending)'" in script
    assert "function wireExecutionActions()" in script
    assert "hydrateForkDraft(executionState.activeEntry);" in script
    assert "execution_backend: 'queue_bridge'" in script
    assert "scheduleNextQueueRefresh();" in script
    assert "function computeAdaptiveDelay(baseDelayMs, elapsedMs, failureCount)" in script
    assert "emitUXEvent('refresh_metrics', { loop: 'main', status: 'success'" in script
    assert "History" in html
    assert "Built agent pipeline" in script
    assert "Queued governed intent" in script
    assert "Show raw JSON" in script
    assert 'data-action="rerun"' in script
    assert 'data-action="fork"' in script
    assert "id=\"uxSummary\"" in html
    assert "id=\"sessionBriefCard\"" in html
    assert "id=\"briefFrequency\"" in html
    assert "id=\"briefMuteScope\"" in html
    assert "const UX_SESSION_KEY = 'aponi.ux.session.v1';" in script
    assert "const BRIEF_SETTINGS_KEY = 'aponi.brief.settings.v1';" in script
    assert "renderSessionBrief(brief || {});" in script
    assert "buildBriefNudges(briefPayload)" in script
    assert "runBriefCta(chipLabel)" in script
    assert "frequencyMultiplier = settings.frequency === 'high' ? 0.7 : (settings.frequency === 'low' ? 1.8 : 1.0);" in script
    assert "function normalizeInsights(payload)" in script
    assert "function renderInsights(items)" in script
    assert "paint('uxSummary', '/ux/summary')" in script
    assert "'/ux/events'" in script
    assert "Expand insight details" in script
    assert "/control/auth-token" in script
    assert "X-APONI-Nonce" in script
    assert "function analyzeCockpitPrompt()" in script
    assert "/control/cockpit/plan" in script
def test_dashboard_script_uses_safe_dom_rendering_primitives() -> None:
    handler = _handler_class()
    script = handler._user_console_js()

    assert "function safeText(value)" in script
    assert "function el(tag, options = {})" in script
    assert "function clearNode(node)" in script
    assert "const SAFE_ATTRS = Object.freeze(new Set(" in script
    assert "const SAFE_TAGS = Object.freeze(new Set(" in script
    assert "SECURITY: Do not use innerHTML" in script
    assert "window.trustedTypes?.createPolicy('default'" in script
    assert "innerHTML =" not in script
    assert script.count("createElement(") == 1
    assert "if (typeof tag !== 'string') throw new Error('Invalid tag type');" in script
def test_cancel_control_command_writes_cancellation_entry(tmp_path, monkeypatch) -> None:
    queue_path = tmp_path / "queue.jsonl"
    monkeypatch.setattr("ui.aponi_dashboard.CONTROL_QUEUE_PATH", queue_path)

    queued = aponi_dashboard._queue_control_command({"type": "create_agent", "agent_id": "triage_agent"})
    result = aponi_dashboard._cancel_control_command(str(queued["command_id"]))

    assert result["ok"] is True
    assert result["backend_supported"] is True
    assert result["cancellation_entry"]["status"] == "canceled"
    assert result["cancellation_entry"]["payload"]["type"] == "cancel_intent"
def test_cancel_control_command_returns_not_found(tmp_path, monkeypatch) -> None:
    queue_path = tmp_path / "queue.jsonl"
    monkeypatch.setattr("ui.aponi_dashboard.CONTROL_QUEUE_PATH", queue_path)

    result = aponi_dashboard._cancel_control_command("cmd-missing")

    assert result == {"ok": False, "error": "queue_empty"}
def test_environment_health_snapshot_reports_required_surfaces(tmp_path, monkeypatch) -> None:
    sources_path = tmp_path / "free_sources.json"
    sources_path.write_text(json.dumps({"_schema_version": "1", "wikipedia": {"provider": "Wikimedia"}}), encoding="utf-8")
    profiles_path = tmp_path / "profiles.json"
    profiles_path.write_text(json.dumps({"_schema_version": "1", "triage-basic": {"knowledge_domains": ["release_notes"], "abilities": ["summarize"], "allowed_capabilities": ["wikipedia"]}}), encoding="utf-8")
    queue_path = tmp_path / "aponi_queue.jsonl"
    monkeypatch.setattr("ui.aponi_dashboard.FREE_CAPABILITY_SOURCES_PATH", sources_path)
    monkeypatch.setattr("ui.aponi_dashboard.SKILL_PROFILES_PATH", profiles_path)
    monkeypatch.setattr("ui.aponi_dashboard.CONTROL_QUEUE_PATH", queue_path)

    from ui.aponi_dashboard import _environment_health_snapshot

    health = _environment_health_snapshot()
    assert health["required_files"]["free_sources"]["exists"] is True
    assert health["required_files"]["free_sources"]["ok"] is True
    assert health["required_files"]["skill_profiles"]["exists"] is True
    assert health["required_files"]["skill_profiles"]["ok"] is True
    assert health["free_sources_count"] == 1
    assert health["skill_profiles_count"] == 1
    assert health["queue_parent_exists"] is True
def test_environment_health_snapshot_reports_schema_mismatch(tmp_path, monkeypatch) -> None:
    sources_path = tmp_path / "free_sources.json"
    sources_path.write_text(json.dumps({"_schema_version": "2", "wikipedia": {"provider": "Wikimedia"}}), encoding="utf-8")
    profiles_path = tmp_path / "profiles.json"
    profiles_path.write_text(json.dumps({"_schema_version": "2", "triage-basic": {"knowledge_domains": ["release_notes"], "abilities": ["summarize"], "allowed_capabilities": ["wikipedia"]}}), encoding="utf-8")
    queue_path = tmp_path / "aponi_queue.jsonl"
    monkeypatch.setattr("ui.aponi_dashboard.FREE_CAPABILITY_SOURCES_PATH", sources_path)
    monkeypatch.setattr("ui.aponi_dashboard.SKILL_PROFILES_PATH", profiles_path)
    monkeypatch.setattr("ui.aponi_dashboard.CONTROL_QUEUE_PATH", queue_path)

    from ui.aponi_dashboard import _environment_health_snapshot

    health = _environment_health_snapshot()
    assert health["required_files"]["free_sources"]["ok"] is False
    assert health["required_files"]["skill_profiles"]["ok"] is False
def test_replay_diff_export_includes_bundle_export_metadata() -> None:
    handler = _handler_class()
    diff = {"ok": True, "epoch_id": "epoch-1", "changed_keys": [], "added_keys": [], "removed_keys": []}
    bundle = {"bundle_id": "evidence-1234", "export_metadata": {"digest": "sha256:abc"}}
    with patch.object(handler, "_replay_diff", return_value=diff):
        with patch.object(handler, "_bundle_builder") as builder:
            builder.build_bundle.return_value = bundle
            payload = handler._replay_diff_export("epoch-1")

    assert payload["ok"] is True
    assert payload["bundle_id"] == "evidence-1234"
    assert payload["export_metadata"]["digest"] == "sha256:abc"
def test_epoch_export_includes_bundle_export_metadata() -> None:
    handler = _handler_class()
    epoch = {"bundles": [{"id": "bundle-1"}], "initial_state": {}, "final_state": {}}
    bundle = {"bundle_id": "evidence-5678", "export_metadata": {"digest": "sha256:def"}}
    with patch.object(handler, "_replay_engine") as replay:
        replay.reconstruct_epoch.return_value = epoch
        with patch.object(handler, "_bundle_builder") as builder:
            builder.build_bundle.return_value = bundle
            payload = handler._epoch_export("epoch-1")

    assert payload["ok"] is True
    assert payload["epoch_id"] == "epoch-1"
    assert payload["bundle_id"] == "evidence-5678"
    assert payload["export_metadata"]["digest"] == "sha256:def"
def test_validate_ux_event_requires_type_session_and_feature() -> None:
    invalid = aponi_dashboard._validate_ux_event({"event_type": "interaction"})
    assert invalid["ok"] is False
    assert invalid["error"] == "missing_session_id"

    valid = aponi_dashboard._validate_ux_event({
        "event_type": "interaction",
        "session_id": "ux-1",
        "feature": "queue_submit",
        "metadata": {"x": 1},
    })
    assert valid["ok"] is True
    assert valid["event"]["event_type"] == "interaction"
def test_ux_summary_aggregates_recent_metrics_events() -> None:
    entries = [
        {"event": "aponi_ux_event", "payload": {"event_type": "feature_entry", "session_id": "s1", "feature": "dashboard_loaded"}},
        {"event": "aponi_ux_event", "payload": {"event_type": "interaction", "session_id": "s1", "feature": "queue_submit"}},
        {"event": "aponi_ux_event", "payload": {"event_type": "interaction", "session_id": "s2", "feature": "history_filter"}},
        {"event": "other_event", "payload": {}},
    ]
    with patch("ui.aponi_dashboard.metrics.tail", return_value=entries):
        summary = aponi_dashboard._ux_summary(window=50)

    assert summary["window"] == 50
    assert summary["event_count"] == 3
    assert summary["unique_sessions"] == 2
    assert summary["counts"]["interaction"] == 2


def test_build_session_brief_payload_reflects_runtime_state_fields() -> None:
    payload = aponi_dashboard._build_session_brief_payload(
        state={
            "locked": True,
            "reason": "tier1_failed",
            "blocker_count": 3,
            "open_findings_count": 2,
            "evidence_complete": False,
            "readiness_score": 0.41,
        },
        intelligence={"replay_mode": "strict"},
        risk={"replay_failure_rate": 0.08},
        replay={"divergence_event_count": 4},
    )

    assert payload["ok"] is True
    assert payload["summary"]["gate_status"] == "locked"
    assert payload["summary"]["replay_divergence_count"] == 4
    assert payload["summary"]["blocker_count"] == 3
    assert payload["summary"]["open_findings_count"] == 2
    assert payload["summary"]["evidence_complete"] is False
    assert payload["summary"]["replay_mode"] == "strict"
    assert payload["alerts"][0]["code"] == "gate_locked"
    assert payload["recommendations"][0]["deterministic_score"] >= payload["recommendations"][1]["deterministic_score"]


def test_session_brief_endpoint_uses_live_runtime_state(tmp_path, monkeypatch) -> None:
    dashboard = aponi_dashboard.AponiDashboard(host="127.0.0.1", port=0)
    dashboard.start({"status": "ok", "blocker_count": 1, "open_findings_count": 1, "evidence_complete": True})
    try:
        assert dashboard._server is not None
        port = dashboard._server.server_port
        with patch("ui.aponi_dashboard._read_gate_state", return_value={"locked": True, "reason": "manual_lock", "protocol": "cryovant.v1"}):
            with urlrequest.urlopen(f"http://127.0.0.1:{port}/dork/session-brief", timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
    finally:
        dashboard.stop()

    assert payload["ok"] is True
    assert payload["summary"]["gate_status"] == "locked"
    assert payload["summary"]["blocker_count"] == 1
    assert payload["summary"]["open_findings_count"] == 1
