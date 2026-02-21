# SPDX-License-Identifier: Apache-2.0

import json
from unittest.mock import patch

from runtime.governance.event_taxonomy import (
    EVENT_TYPE_CONSTITUTION_ESCALATION,
    EVENT_TYPE_OPERATOR_OVERRIDE,
    EVENT_TYPE_REPLAY_DIVERGENCE,
    EVENT_TYPE_REPLAY_FAILURE,
    normalize_event_type,
)
from runtime.governance.policy_artifact import GovernanceModelMetadata, GovernancePolicy, GovernanceThresholds
from ui import aponi_dashboard
from ui.aponi_dashboard import AponiDashboard, _skill_capability_matrix

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
    assert "[HTTP ${response.status}]" in script
    assert "if (!response.ok) throw new Error(`endpoint returned HTTP ${response.status}`);" in script
    assert "Failed to load skill profiles:" in script
    assert "Agent ID is required before queue submission." in script
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
    assert "setInterval(refreshControlQueue, EXECUTION_POLL_MS);" in script
    assert "History" in html
    assert "Built agent pipeline" in script
    assert "Queued governed intent" in script
    assert "Show raw JSON" in script
    assert 'data-action="rerun"' in script
    assert 'data-action="fork"' in script
    assert "id=\"uxSummary\"" in html
    assert "const UX_SESSION_KEY = 'aponi.ux.session.v1';" in script
    assert "function normalizeInsights(payload)" in script
    assert "function renderInsights(items)" in script
    assert "id=\"uxSummary\"" in html
    assert "'/ux/events'" in script
    assert "Expand insight details" in script

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

def test_loaders_ignore_schema_version_metadata(tmp_path, monkeypatch) -> None:
    sources_path = tmp_path / "free_sources.json"
    sources_path.write_text(json.dumps({"_schema_version": "1", "wikipedia": {"provider": "Wikimedia"}}), encoding="utf-8")
    profiles_path = tmp_path / "profiles.json"
    profiles_path.write_text(json.dumps({"_schema_version": "1", "triage-basic": {"knowledge_domains": ["release_notes"], "abilities": ["summarize"], "allowed_capabilities": ["wikipedia"]}}), encoding="utf-8")
    monkeypatch.setattr("ui.aponi_dashboard.FREE_CAPABILITY_SOURCES_PATH", sources_path)
    monkeypatch.setattr("ui.aponi_dashboard.SKILL_PROFILES_PATH", profiles_path)

    from ui.aponi_dashboard import _load_free_capability_sources, _load_skill_profiles

    sources = _load_free_capability_sources()
    profiles = _load_skill_profiles()

    assert "_schema_version" not in sources
    assert "_schema_version" not in profiles


def test_capability_matrix_uses_canonical_capabilities_key(tmp_path, monkeypatch) -> None:
    sources_path = tmp_path / "free_sources.json"
    profiles_path = tmp_path / "profiles.json"
    sources_path.write_text(
        json.dumps({"_schema_version": "1", "wikipedia": {"provider": "Wikimedia"}}),
        encoding="utf-8",
    )
    profiles_path.write_text(
        json.dumps(
            {
                "_schema_version": "1",
                "triage-basic": {
                    "knowledge_domains": ["release_notes"],
                    "abilities": ["summarize"],
                    "allowed_capabilities": ["wikipedia"],
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("ui.aponi_dashboard.FREE_CAPABILITY_SOURCES_PATH", sources_path)
    monkeypatch.setattr("ui.aponi_dashboard.SKILL_PROFILES_PATH", profiles_path)

    matrix = _skill_capability_matrix()
    profile = matrix["triage-basic"]
    assert "capabilities" in profile
    assert profile["capabilities"] == ["wikipedia"]
    assert "allowed_capabilities" not in profile

def test_control_command_validation_requires_strict_profile_and_known_capabilities(tmp_path, monkeypatch) -> None:
    sources_path = tmp_path / "free_sources.json"
    sources_path.write_text(json.dumps({"_schema_version": "1", "wikipedia": {"provider": "Wikimedia"}}), encoding="utf-8")
    profiles_path = tmp_path / "profiles.json"
    profiles_path.write_text(json.dumps({"_schema_version": "1", "triage-basic": {"knowledge_domains": ["release_notes"], "abilities": ["summarize"], "allowed_capabilities": ["wikipedia"]}}), encoding="utf-8")
    monkeypatch.setattr("ui.aponi_dashboard.FREE_CAPABILITY_SOURCES_PATH", sources_path)
    monkeypatch.setattr("ui.aponi_dashboard.SKILL_PROFILES_PATH", profiles_path)
    handler = _handler_class()

    invalid = handler._validate_control_command(
        {
            "type": "create_agent",
            "agent_id": "Agent#1",
            "governance_profile": "standard",
            "mode": "builder",
            "capabilities": ["unknown"],
            "skill_profile": "triage-basic",
            "knowledge_domain": "release_notes",
            "purpose": "Assist with triage",
        }
    )
    assert invalid["ok"] is False

    valid = handler._validate_control_command(
        {
            "type": "create_agent",
            "agent_id": "triage_agent",
            "governance_profile": "strict",
            "mode": "builder",
            "capabilities": ["wikipedia"],
            "skill_profile": "triage-basic",
            "knowledge_domain": "release_notes",
            "purpose": "Assist with triage",
        }
    )
    assert valid["ok"] is True
    assert valid["command"]["capabilities"] == ["wikipedia"]

def test_control_command_validation_rejects_unknown_skill_profile(tmp_path, monkeypatch) -> None:
    sources_path = tmp_path / "free_sources.json"
    sources_path.write_text(json.dumps({"_schema_version": "1", "wikipedia": {"provider": "Wikimedia"}}), encoding="utf-8")
    profiles_path = tmp_path / "profiles.json"
    profiles_path.write_text(json.dumps({"_schema_version": "1", "triage-basic": {"knowledge_domains": ["release_notes"], "abilities": ["summarize"], "allowed_capabilities": ["wikipedia"]}}), encoding="utf-8")
    monkeypatch.setattr("ui.aponi_dashboard.FREE_CAPABILITY_SOURCES_PATH", sources_path)
    monkeypatch.setattr("ui.aponi_dashboard.SKILL_PROFILES_PATH", profiles_path)
    handler = _handler_class()

    invalid = handler._validate_control_command(
        {
            "type": "run_task",
            "agent_id": "triage_agent",
            "governance_profile": "strict",
            "mode": "builder",
            "skill_profile": "unknown-profile",
            "knowledge_domain": "release_notes",
            "capabilities": ["wikipedia"],
            "task": "summarize release risk",
            "ability": "summarize",
        }
    )

    assert invalid["ok"] is False
    assert invalid["error"] == "invalid_skill_profile"

def test_control_command_validation_rejects_capability_outside_profile(tmp_path, monkeypatch) -> None:
    sources_path = tmp_path / "free_sources.json"
    sources_path.write_text(json.dumps({"wikipedia": {"provider": "Wikimedia"}, "crossref": {"provider": "Crossref"}}), encoding="utf-8")
    profiles_path = tmp_path / "profiles.json"
    profiles_path.write_text(json.dumps({"triage-basic": {"knowledge_domains": ["release_notes"], "abilities": ["summarize"], "allowed_capabilities": ["wikipedia"]}}), encoding="utf-8")
    monkeypatch.setattr("ui.aponi_dashboard.FREE_CAPABILITY_SOURCES_PATH", sources_path)
    monkeypatch.setattr("ui.aponi_dashboard.SKILL_PROFILES_PATH", profiles_path)
    handler = _handler_class()

    invalid = handler._validate_control_command(
        {
            "type": "run_task",
            "agent_id": "triage_agent",
            "governance_profile": "strict",
            "mode": "builder",
            "skill_profile": "triage-basic",
            "knowledge_domain": "release_notes",
            "capabilities": ["crossref"],
            "task": "summarize release risk",
            "ability": "summarize",
        }
    )

    assert invalid["ok"] is False
    assert invalid["error"] == "capability_not_allowed_for_skill"

def test_control_command_validation_enforces_knowledge_domain_membership(tmp_path, monkeypatch) -> None:
    sources_path = tmp_path / "free_sources.json"
    sources_path.write_text(json.dumps({"wikipedia": {"provider": "Wikimedia"}}), encoding="utf-8")
    profiles_path = tmp_path / "profiles.json"
    profiles_path.write_text(json.dumps({"triage-basic": {"knowledge_domains": ["release_notes"], "abilities": ["summarize"], "allowed_capabilities": ["wikipedia"]}}), encoding="utf-8")
    monkeypatch.setattr("ui.aponi_dashboard.FREE_CAPABILITY_SOURCES_PATH", sources_path)
    monkeypatch.setattr("ui.aponi_dashboard.SKILL_PROFILES_PATH", profiles_path)
    handler = _handler_class()

    invalid = handler._validate_control_command(
        {
            "type": "run_task",
            "agent_id": "triage_agent",
            "governance_profile": "strict",
            "mode": "builder",
            "skill_profile": "triage-basic",
            "knowledge_domain": "lineage",
            "capabilities": ["wikipedia"],
            "task": "summarize release risk",
            "ability": "summarize",
        }
    )

    assert invalid["ok"] is False
    assert invalid["error"] == "invalid_knowledge_domain"

def test_control_command_validation_enforces_ability_membership(tmp_path, monkeypatch) -> None:
    sources_path = tmp_path / "free_sources.json"
    sources_path.write_text(json.dumps({"wikipedia": {"provider": "Wikimedia"}}), encoding="utf-8")
    profiles_path = tmp_path / "profiles.json"
    profiles_path.write_text(json.dumps({"triage-basic": {"knowledge_domains": ["release_notes"], "abilities": ["summarize"], "allowed_capabilities": ["wikipedia"]}}), encoding="utf-8")
    monkeypatch.setattr("ui.aponi_dashboard.FREE_CAPABILITY_SOURCES_PATH", sources_path)
    monkeypatch.setattr("ui.aponi_dashboard.SKILL_PROFILES_PATH", profiles_path)
    handler = _handler_class()

    invalid = handler._validate_control_command(
        {
            "type": "run_task",
            "agent_id": "triage_agent",
            "governance_profile": "strict",
            "mode": "builder",
            "skill_profile": "triage-basic",
            "knowledge_domain": "release_notes",
            "capabilities": ["wikipedia"],
            "task": "summarize release risk",
            "ability": "audit",
        }
    )

    assert invalid["ok"] is False
    assert invalid["error"] == "invalid_ability"

def test_control_command_validation_caps_capability_count(tmp_path, monkeypatch) -> None:
    sources = {f"s{i}": {"provider": f"p{i}"} for i in range(12)}
    sources_path = tmp_path / "free_sources.json"
    sources_path.write_text(json.dumps(sources), encoding="utf-8")
    profiles_path = tmp_path / "profiles.json"
    profiles_path.write_text(json.dumps({"triage-basic": {"knowledge_domains": ["release_notes"], "abilities": ["summarize"], "allowed_capabilities": list(sources.keys())}}), encoding="utf-8")
    monkeypatch.setattr("ui.aponi_dashboard.FREE_CAPABILITY_SOURCES_PATH", sources_path)
    monkeypatch.setattr("ui.aponi_dashboard.SKILL_PROFILES_PATH", profiles_path)
    handler = _handler_class()

    invalid = handler._validate_control_command(
        {
            "type": "run_task",
            "agent_id": "triage_agent",
            "governance_profile": "strict",
            "mode": "builder",
            "skill_profile": "triage-basic",
            "knowledge_domain": "release_notes",
            "capabilities": list(sources.keys())[:9],
            "task": "summarize release risk",
            "ability": "summarize",
        }
    )

    assert invalid["ok"] is False
    assert invalid["error"] == "capabilities_limit_exceeded"

def test_control_command_validation_deduplicates_capabilities(tmp_path, monkeypatch) -> None:
    sources_path = tmp_path / "free_sources.json"
    sources_path.write_text(json.dumps({"wikipedia": {"provider": "Wikimedia"}}), encoding="utf-8")
    profiles_path = tmp_path / "profiles.json"
    profiles_path.write_text(json.dumps({"triage-basic": {"knowledge_domains": ["release_notes"], "abilities": ["summarize"], "allowed_capabilities": ["wikipedia"]}}), encoding="utf-8")
    monkeypatch.setattr("ui.aponi_dashboard.FREE_CAPABILITY_SOURCES_PATH", sources_path)
    monkeypatch.setattr("ui.aponi_dashboard.SKILL_PROFILES_PATH", profiles_path)
    handler = _handler_class()

    valid = handler._validate_control_command(
        {
            "type": "run_task",
            "agent_id": "triage_agent",
            "governance_profile": "strict",
            "mode": "builder",
            "skill_profile": "triage-basic",
            "knowledge_domain": "release_notes",
            "capabilities": ["wikipedia", "wikipedia"],
            "task": "summarize release risk",
            "ability": "summarize",
        }
    )

    assert valid["ok"] is True
    assert valid["command"]["capabilities"] == ["wikipedia"]

def test_queue_control_command_appends_deterministic_entry(tmp_path, monkeypatch) -> None:
    queue_path = tmp_path / "aponi_queue.jsonl"
    monkeypatch.setattr("ui.aponi_dashboard.CONTROL_QUEUE_PATH", queue_path)
    from ui.aponi_dashboard import _queue_control_command

    entry = _queue_control_command(
        {
            "type": "run_task",
            "agent_id": "triage_agent",
            "governance_profile": "strict",
            "mode": "builder",
            "skill_profile": "triage-basic",
            "knowledge_domain": "release_notes",
            "capabilities": ["wikipedia"],
            "task": "summarize release risk",
            "ability": "summarize",
        }
    )

    assert entry["queue_index"] == 1
    assert entry["command_id"].startswith("cmd-000001-")
    assert entry["previous_digest"] == ""
    lines = queue_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1

def test_verify_control_queue_detects_tamper(tmp_path, monkeypatch) -> None:
    queue_path = tmp_path / "aponi_queue.jsonl"
    monkeypatch.setattr("ui.aponi_dashboard.CONTROL_QUEUE_PATH", queue_path)
    from ui.aponi_dashboard import _queue_control_command, _read_control_queue, _verify_control_queue

    _queue_control_command({"type": "create_agent", "agent_id": "triage_agent", "governance_profile": "strict", "skill_profile": "triage-basic", "knowledge_domain": "release_notes", "capabilities": ["wikipedia"], "purpose": "triage"})
    _queue_control_command({"type": "run_task", "agent_id": "triage_agent", "governance_profile": "strict", "skill_profile": "triage-basic", "knowledge_domain": "release_notes", "capabilities": ["wikipedia"], "task": "summarize", "ability": "summarize"})

    entries = _read_control_queue()
    ok_state = _verify_control_queue(entries)
    assert ok_state["ok"] is True

    entries[1]["command_id"] = "cmd-corrupted"
    bad_state = _verify_control_queue(entries)
    assert bad_state["ok"] is False
    assert any("unexpected_command_id" in issue for issue in bad_state["issues"])

    entries[0]["payload"] = "corrupted"
    bad_payload_state = _verify_control_queue(entries)
    assert bad_payload_state["ok"] is False
    assert "invalid_payload_type" in bad_payload_state["issues"]

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

def test_control_policy_summary_and_templates_are_deterministic(tmp_path, monkeypatch) -> None:
    sources_path = tmp_path / "free_sources.json"
    sources_path.write_text(json.dumps({"wikipedia": {"provider": "Wikimedia"}}), encoding="utf-8")
    profiles_path = tmp_path / "profiles.json"
    profiles_path.write_text(
        json.dumps(
            {
                "triage-basic": {
                    "knowledge_domains": ["release_notes"],
                    "abilities": ["summarize"],
                    "allowed_capabilities": ["wikipedia"],
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("ui.aponi_dashboard.FREE_CAPABILITY_SOURCES_PATH", sources_path)
    monkeypatch.setattr("ui.aponi_dashboard.SKILL_PROFILES_PATH", profiles_path)

    from ui.aponi_dashboard import _control_intent_templates, _control_policy_summary

    summary = _control_policy_summary()
    templates = _control_intent_templates()

    assert summary["max_capabilities_per_intent"] >= 1
    assert summary["skill_profiles"] == ["triage-basic"]
    assert templates["triage-basic"]["run_task"]["ability"] == "summarize"
    assert templates["triage-basic"]["create_agent"]["knowledge_domain"] == "release_notes"

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


def test_cancel_control_command_writes_cancellation_entry(tmp_path, monkeypatch) -> None:
    queue_path = tmp_path / "queue.jsonl"
    monkeypatch.setattr("ui.aponi_dashboard.CONTROL_QUEUE_PATH", queue_path)

    queued = aponi_dashboard._queue_control_command({"type": "create_agent", "agent_id": "triage_agent"})
    result = aponi_dashboard._cancel_control_command(str(queued["command_id"]))

    assert result["ok"] is True
    assert result["backend_supported"] is True
    assert result["cancellation_entry"]["status"] == "canceled"
    assert result["cancellation_entry"]["payload"]["type"] == "cancel_intent"


def test_cancel_control_command_returns_queue_empty(tmp_path, monkeypatch) -> None:
    queue_path = tmp_path / "queue.jsonl"
    monkeypatch.setattr("ui.aponi_dashboard.CONTROL_QUEUE_PATH", queue_path)

    result = aponi_dashboard._cancel_control_command("cmd-missing")

    assert result == {"ok": False, "error": "queue_empty"}


def test_control_command_validation_rejects_invalid_mode(tmp_path, monkeypatch) -> None:
    sources_path = tmp_path / "free_sources.json"
    sources_path.write_text(json.dumps({"_schema_version": "1", "wikipedia": {"provider": "Wikimedia"}}), encoding="utf-8")
    profiles_path = tmp_path / "profiles.json"
    profiles_path.write_text(json.dumps({"_schema_version": "1", "triage-basic": {"knowledge_domains": ["release_notes"], "abilities": ["summarize"], "allowed_capabilities": ["wikipedia"]}}), encoding="utf-8")
    monkeypatch.setattr("ui.aponi_dashboard.FREE_CAPABILITY_SOURCES_PATH", sources_path)
    monkeypatch.setattr("ui.aponi_dashboard.SKILL_PROFILES_PATH", profiles_path)
    handler = _handler_class()

    invalid = handler._validate_control_command(
        {
            "type": "run_task",
            "agent_id": "triage_agent",
            "governance_profile": "strict",
            "mode": "unsupported",
            "skill_profile": "triage-basic",
            "knowledge_domain": "release_notes",
            "capabilities": ["wikipedia"],
            "task": "summarize release risk",
            "ability": "summarize",
        }
    )

    assert invalid["ok"] is False
    assert invalid["error"] == "invalid_mode"


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


def test_execution_control_validation_requires_dedicated_contract() -> None:
    handler = _handler_class()

    invalid = handler._validate_execution_control_command(
        {
            "type": "run_task",
            "action": "cancel",
            "target_command_id": "cmd-000001-a1b2c3d4e5f6",
        }
    )

    assert invalid["ok"] is False
    assert invalid["error"] == "unsupported_type"


def test_execution_control_validation_accepts_cancel_and_fork() -> None:
    handler = _handler_class()

    cancel_valid = handler._validate_execution_control_command(
        {
            "type": "execution_control",
            "action": "cancel",
            "target_command_id": "cmd-000001-a1b2c3d4e5f6",
            "reason": "operator cancelled",
        }
    )
    fork_valid = handler._validate_execution_control_command(
        {
            "type": "execution_control",
            "action": "fork",
            "target_command_id": "cmd-000222-001122334455",
        }
    )

    assert cancel_valid["ok"] is True
    assert cancel_valid["command"]["action"] == "cancel"
    assert cancel_valid["command"]["reason"] == "operator cancelled"
    assert fork_valid["ok"] is True
    assert fork_valid["command"]["action"] == "fork"


def test_execution_control_validation_rejects_invalid_target_command_id() -> None:
    handler = _handler_class()

    invalid = handler._validate_execution_control_command(
        {
            "type": "execution_control",
            "action": "cancel",
            "target_command_id": "not-a-command-id",
        }
    )

    assert invalid["ok"] is False
    assert invalid["error"] == "invalid_target_command_id"


def test_execution_control_validation_accepts_hex_command_id() -> None:
    handler = _handler_class()

    valid = handler._validate_execution_control_command(
        {
            "type": "execution_control",
            "action": "cancel",
            "target_command_id": "cmd-000001-a1b2c3d4e5f6",
        }
    )

    assert valid["ok"] is True
    assert valid["command"]["target_command_id"] == "cmd-000001-a1b2c3d4e5f6"


def test_find_control_queue_entry_returns_latest_match(tmp_path, monkeypatch) -> None:
    queue_path = tmp_path / "queue.jsonl"
    monkeypatch.setattr("ui.aponi_dashboard.CONTROL_QUEUE_PATH", queue_path)

    first = aponi_dashboard._queue_control_command({"type": "run_task", "agent_id": "triage_agent", "governance_profile": "strict", "mode": "builder", "skill_profile": "triage-basic", "knowledge_domain": "release_notes", "capabilities": ["wikipedia"], "task": "t1", "ability": "summarize"})
    second = aponi_dashboard._queue_control_command({"type": "run_task", "agent_id": "triage_agent", "governance_profile": "strict", "mode": "builder", "skill_profile": "triage-basic", "knowledge_domain": "release_notes", "capabilities": ["wikipedia"], "task": "t2", "ability": "summarize"})

    found = aponi_dashboard._find_control_queue_entry(str(second["command_id"]))

    assert found is not None
    assert found["command_id"] == second["command_id"]
    assert found["command_id"] != first["command_id"]


def test_execution_control_validation_rejects_non_hex_suffix() -> None:
    handler = _handler_class()

    invalid = handler._validate_execution_control_command(
        {
            "type": "execution_control",
            "action": "cancel",
            "target_command_id": "cmd-000001-zzzzzzzzzzzz",
        }
    )

    assert invalid["ok"] is False
    assert invalid["error"] == "invalid_target_command_id"
