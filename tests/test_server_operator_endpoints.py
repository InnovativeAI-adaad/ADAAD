# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations
import pytest
pytestmark = pytest.mark.regression_standard

from dataclasses import dataclass
import json
import subprocess

from fastapi.testclient import TestClient

import server


class _FakeLedger:
    def read_all(self):
        return [
            {
                "type": "MutationBundleEvent",
                "ts": "2026-01-01T00:00:00Z",
                "payload": {
                    "epoch_id": "epoch-1",
                    "bundle_id": "mut-1",
                    "impact": 0.9,
                    "risk_tier": "low",
                    "applied": True,
                },
            }
        ]

    def list_epoch_ids(self):
        return ["epoch-1"]

    def read_epoch(self, epoch_id: str):
        return [
            {
                "type": "EpochStartEvent",
                "ts": "2026-01-01T00:00:00Z",
                "payload": {"epoch_id": epoch_id},
            },
            {
                "type": "MutationBundleEvent",
                "ts": "2026-01-01T00:01:00Z",
                "payload": {"epoch_id": epoch_id, "bundle_id": "mut-1", "impact": 0.9},
            },
        ]

    def get_expected_epoch_digest(self, epoch_id: str):
        return "sha256:" + "1" * 64

    def compute_incremental_epoch_digest(self, epoch_id: str):
        return "sha256:" + "2" * 64


def test_operator_mutations_endpoint_schema(monkeypatch) -> None:
    monkeypatch.setattr(server, "LineageLedgerV2", _FakeLedger)

    with TestClient(server.app) as client:
        response = client.get("/api/mutations")

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert payload
    server.MutationView.model_validate(payload[0])


def test_operator_epochs_endpoint_schema(monkeypatch) -> None:
    monkeypatch.setattr(server, "LineageLedgerV2", _FakeLedger)

    with TestClient(server.app) as client:
        response = client.get("/api/epochs")

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert payload
    server.EpochView.model_validate(payload[0])


def test_constitution_status_endpoint_schema(monkeypatch) -> None:
    monkeypatch.setattr(server.constitution, "CONSTITUTION_VERSION", "0.2.0")
    monkeypatch.setattr(server.constitution, "POLICY_HASH", "abc123")
    monkeypatch.setattr(server.constitution, "boot_sanity_check", lambda: {"ok": True})

    with TestClient(server.app) as client:
        response = client.get("/api/constitution/status")

    assert response.status_code == 200
    server.ConstitutionStatus.model_validate(response.json())


@dataclass(frozen=True)
class _Decision:
    strategy: object
    proposal: object
    critique: object

    @property
    def outcome(self) -> str:
        return "execute"


def test_system_intelligence_endpoint_schema(monkeypatch) -> None:
    @dataclass(frozen=True)
    class _Part:
        value: str

    class _Router:
        def route(self, _context):
            return _Decision(strategy=_Part("strategy"), proposal=_Part("proposal"), critique=_Part("critique"))

    monkeypatch.setattr(server, "rolling_determinism_score", lambda window=100: {"rolling_score": 1.0, "sample_size": 1})
    monkeypatch.setattr(server, "mutation_rate_snapshot", lambda window_sec=3600: {"rate_per_hour": 1.0, "count": 1})
    monkeypatch.setattr(server, "IntelligenceRouter", _Router)

    with TestClient(server.app) as client:
        response = client.get("/api/system/intelligence")

    assert response.status_code == 200
    server.SystemIntelligenceView.model_validate(response.json())


def test_post_proposal_delegates_to_mcp_validation_and_queue(monkeypatch) -> None:
    class _Request:
        authority_level = "governor-review"

    observed: dict[str, object] = {}

    def _fake_validate(payload):
        observed["payload"] = payload
        return _Request(), {"passed": True, "verdicts": []}

    def _fake_append(*, proposal_id: str, request):
        observed["proposal_id"] = proposal_id
        observed["request"] = request
        return {"hash": "queuehash"}

    class _Provider:
        def next_id(self, *, label: str, length: int):
            observed["label"] = label
            observed["length"] = length
            return "proposal-123"

    monkeypatch.setattr(server, "validate_proposal", _fake_validate)
    monkeypatch.setattr(server, "append_proposal", _fake_append)
    monkeypatch.setattr(server, "default_provider", lambda: _Provider())

    with TestClient(server.app) as client:
        response = client.post("/api/mutations/proposals", json={"intent": "optimize"})

    assert response.status_code == 200
    payload = response.json()
    server.ProposalResponse.model_validate(payload)
    assert observed["payload"] == {"intent": "optimize"}
    assert observed["proposal_id"] == "proposal-123"




def test_post_proposal_returns_structured_grok_rejection(monkeypatch) -> None:
    class _Err(Exception):
        status_code = 403
        code = "grok_disabled"
        detail = "grok-integrator is disabled in governance runtime profile"

    def _fake_validate(_payload):
        raise _Err()

    monkeypatch.setattr(server, "validate_proposal", _fake_validate)

    with TestClient(server.app) as client:
        response = client.post("/api/mutations/proposals", json={"agent_id": "grok-integrator", "intent": "optimize"})

    assert response.status_code == 403
    payload = response.json()["detail"]
    assert payload["reason"] == "grok_disabled"
    assert payload["structured"]["component"] == "grok-integrator"

def test_mock_endpoints_disabled_by_default() -> None:
    with TestClient(server.app) as client:
        response = client.get("/api/status")

    assert response.status_code == 404
    assert response.json() == {"detail": "mock_endpoints_disabled"}


def test_api_health_includes_version_and_runtime_profile() -> None:
    with TestClient(server.app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload.get("version"), str)
    runtime_profile = payload.get("runtime_profile")
    assert isinstance(runtime_profile, dict)
    assert "present" in runtime_profile


def test_trigger_mutation_cycle_returns_operation_id_and_persists_status(monkeypatch, tmp_path) -> None:
    observed: dict[str, object] = {}
    events: list[dict[str, object]] = []
    journal_events: list[dict[str, object]] = []
    status_file = tmp_path / "mutation_status.json"
    log_dir = tmp_path / "epoch_logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(server, "MUTATION_EPOCH_STATUS_PATH", status_file)
    monkeypatch.setattr(server, "MUTATION_EPOCH_LOG_DIR", log_dir)
    monkeypatch.setattr(server, "_MUTATION_EPOCH_TASKS", {})
    monkeypatch.setattr(server, "_MUTATION_STDIO_LOG_LIMIT_BYTES", 128)

    def _fake_run(*args, **kwargs):
        observed["kwargs"] = kwargs
        return subprocess.CompletedProcess(args=args[0], returncode=0)

    def _fake_metrics_log(*, event_type, payload, level="INFO", **_kwargs):
        events.append({"event_type": event_type, "payload": payload, "level": level})

    def _fake_append_tx(*, tx_type, payload, **_kwargs):
        journal_events.append({"tx_type": tx_type, "payload": payload})
        return {"ok": True}

    monkeypatch.setattr(server.subprocess, "run", _fake_run)
    monkeypatch.setattr(server.metrics, "log", _fake_metrics_log)
    monkeypatch.setattr(server.journal, "append_tx", _fake_append_tx)

    with TestClient(server.app) as client:
        response = client.post("/api/mutations/trigger-epoch")

    assert response.status_code == 200
    payload = response.json()
    operation_id = payload["operation_id"]
    assert operation_id.startswith("epoch-op-")
    assert payload["status_endpoint"].endswith(operation_id)
    status_doc = json.loads(status_file.read_text(encoding="utf-8"))
    assert status_doc[operation_id]["status"] == "succeeded"
    assert status_doc[operation_id]["return_code"] == 0
    kwargs = observed["kwargs"]
    assert kwargs["timeout"] == server._MUTATION_EPOCH_TIMEOUT_SECONDS
    assert kwargs["check"] is True
    assert events[-1]["event_type"] == "mutation_epoch_task_completed"
    assert journal_events[-1]["tx_type"] == "mutation_epoch_task_completed.v1"

    with TestClient(server.app) as client:
        status_response = client.get(f"/api/mutations/epoch-status/{operation_id}")
    assert status_response.status_code == 200
    assert status_response.json()["operation"]["status"] == "succeeded"


def test_trigger_mutation_cycle_handles_timeout(monkeypatch, tmp_path) -> None:
    status_file = tmp_path / "mutation_status.json"
    log_dir = tmp_path / "epoch_logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(server, "MUTATION_EPOCH_STATUS_PATH", status_file)
    monkeypatch.setattr(server, "MUTATION_EPOCH_LOG_DIR", log_dir)
    monkeypatch.setattr(server, "_MUTATION_EPOCH_TASKS", {})
    monkeypatch.setattr(server, "_MUTATION_STDIO_LOG_LIMIT_BYTES", 128)
    monkeypatch.setattr(server.metrics, "log", lambda **_kwargs: None)
    monkeypatch.setattr(server.journal, "append_tx", lambda **_kwargs: {"ok": True})

    def _timeout_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"])

    monkeypatch.setattr(server.subprocess, "run", _timeout_run)

    with TestClient(server.app) as client:
        response = client.post("/api/mutations/trigger-epoch")

    assert response.status_code == 200
    operation_id = response.json()["operation_id"]
    status_doc = json.loads(status_file.read_text(encoding="utf-8"))
    assert status_doc[operation_id]["status"] == "failed"
    assert status_doc[operation_id]["timed_out"] is True
    assert status_doc[operation_id]["error_type"] == "TimeoutExpired"


def test_post_proposal_alias_uses_same_handler(monkeypatch) -> None:
    class _Request:
        authority_level = "governor-review"

    def _fake_validate(payload):
        return _Request(), {"passed": True, "verdicts": []}

    def _fake_append(*, proposal_id: str, request):
        return {"hash": "queuehash"}

    class _Provider:
        def next_id(self, *, label: str, length: int):
            return "proposal-999"

    monkeypatch.setattr(server, "validate_proposal", _fake_validate)
    monkeypatch.setattr(server, "append_proposal", _fake_append)
    monkeypatch.setattr(server, "default_provider", lambda: _Provider())

    with TestClient(server.app) as client:
        response = client.post("/mutation/propose", json={"intent": "optimize"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["proposal_id"] == "proposal-999"
    assert payload["ok"] is True


def test_get_lint_preview_returns_bridge_output(monkeypatch) -> None:
    observed: dict[str, object] = {}

    class _Bridge:
        def analyze(self, payload):
            observed["payload"] = payload
            return {"preview_authoritative": False, "annotations": [], "gate": "queue_append_constitutional_evaluation", "throttle": False}

    monkeypatch.setattr(server, "MutationLintingBridge", _Bridge)

    with TestClient(server.app) as client:
        response = client.get(
            "/api/lint/preview",
            params={
                "agent_id": "agent.test",
                "target_path": "app/example.py",
                "python_content": "print('ok')",
                "metadata": '{"change_reason":"test"}',
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["preview_authoritative"] is False
    assert observed["payload"]["agent_id"] == "agent.test"


def test_post_lint_preview_accepts_json_body(monkeypatch) -> None:
    observed: dict[str, object] = {}

    class _Bridge:
        def analyze(self, payload):
            observed["payload"] = payload
            return {
                "preview_authoritative": False,
                "annotations": [{"field": "target_path", "message": "path reviewed"}],
                "gate": "queue_append_constitutional_evaluation",
                "throttle": False,
            }

    monkeypatch.setattr(server, "MutationLintingBridge", _Bridge)

    with TestClient(server.app) as client:
        response = client.post(
            "/api/lint/preview",
            json={
                "agent_id": "agent.test",
                "target_path": "app/example.py",
                "python_content": "print('ok')",
                "metadata": {"change_reason": "test"},
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["preview_authoritative"] is False
    assert observed["payload"] == {
        "agent_id": "agent.test",
        "target_path": "app/example.py",
        "python_content": "print('ok')",
        "metadata": {"change_reason": "test"},
    }


def test_post_proposal_emits_aponi_editor_submission_event(monkeypatch) -> None:
    class _Request:
        authority_level = "governor-review"

    observed: dict[str, object] = {}

    def _fake_validate(payload):
        observed["payload"] = payload
        return _Request(), {"passed": True, "verdicts": []}

    def _fake_append(*, proposal_id: str, request):
        observed["proposal_id"] = proposal_id
        observed["request"] = request
        return {"hash": "queuehash"}

    class _Provider:
        def next_id(self, *, label: str, length: int):
            return "proposal-123"

        def format_utc(self, fmt: str):
            return "2026-01-01T00:00:00Z"

    metric_calls: list[dict[str, object]] = []
    journal_calls: list[dict[str, object]] = []

    monkeypatch.setattr(server, "validate_proposal", _fake_validate)
    monkeypatch.setattr(server, "append_proposal", _fake_append)
    monkeypatch.setattr(server, "default_provider", lambda: _Provider())
    monkeypatch.setattr(server.metrics, "log", lambda **kwargs: metric_calls.append(kwargs))
    monkeypatch.setattr(server.journal, "append_tx", lambda *, tx_type, payload, tx_id=None: journal_calls.append({"tx_type": tx_type, "payload": payload, "tx_id": tx_id}))

    headers = {
        "X-Aponi-Session-Id": "session-1",
        "X-Aponi-Submission-Origin": "editor_ui",
        "X-Aponi-Actor-Id": "operator-42",
        "X-Aponi-Actor-Role": "editor",
    }

    with TestClient(server.app) as client:
        response = client.post("/api/mutations/proposals", json={"intent": "optimize"}, headers=headers)

    assert response.status_code == 200
    assert metric_calls
    assert journal_calls

    metric_event = next(event for event in metric_calls if event["event_type"] == "aponi_editor_proposal_submitted.v1")
    assert metric_event["event_type"] == "aponi_editor_proposal_submitted.v1"
    event_payload = metric_event["payload"]
    assert event_payload["proposal_id"] == "proposal-123"
    assert event_payload["session_id"] == "session-1"
    assert event_payload["actor_context"] == {
        "actor_id": "operator-42",
        "actor_role": "editor",
        "authn_scheme": "unspecified",
    }
    assert event_payload["endpoint_path"] == "/api/mutations/proposals"
    assert event_payload["timestamp"] == "2026-01-01T00:00:00Z"
    assert "intent" not in event_payload

    journal_event = journal_calls[-1]
    assert journal_event["tx_type"] == "aponi_editor_proposal_submitted.v1"
    assert journal_event["payload"] == event_payload


def test_post_proposal_skips_aponi_editor_event_without_editor_context(monkeypatch) -> None:
    class _Request:
        authority_level = "governor-review"

    def _fake_validate(payload):
        return _Request(), {"passed": True, "verdicts": []}

    def _fake_append(*, proposal_id: str, request):
        return {"hash": "queuehash"}

    class _Provider:
        def next_id(self, *, label: str, length: int):
            return "proposal-123"

        def format_utc(self, fmt: str):
            return "2026-01-01T00:00:00Z"

    metric_calls: list[dict[str, object]] = []
    journal_calls: list[dict[str, object]] = []

    monkeypatch.setattr(server, "validate_proposal", _fake_validate)
    monkeypatch.setattr(server, "append_proposal", _fake_append)
    monkeypatch.setattr(server, "default_provider", lambda: _Provider())
    monkeypatch.setattr(server.metrics, "log", lambda **kwargs: metric_calls.append(kwargs))
    monkeypatch.setattr(server.journal, "append_tx", lambda *, tx_type, payload, tx_id=None: journal_calls.append({"tx_type": tx_type, "payload": payload, "tx_id": tx_id}))

    with TestClient(server.app) as client:
        response = client.post("/api/mutations/proposals", json={"intent": "optimize"})

    assert response.status_code == 200
    assert all(event["event_type"] != "aponi_editor_proposal_submitted.v1" for event in metric_calls)
    assert journal_calls == []


def test_entitlement_blocks_mutation_feature_for_free_plan(monkeypatch) -> None:
    server.metrics.reset_conversion_funnel()
    with TestClient(server.app) as client:
        response = client.post(
            "/api/nexus/agents/agent-1/mutate",
            json={"mutation_type": "dna_patch", "payload": {"dna": []}, "signature": "x", "nonce": "n", "timestamp": "2026-01-01T00:00:00Z", "challenge_id": "c"},
            headers={"X-ADAAD-Plan": "free"},
        )

    assert response.status_code == 402
    assert response.json()["reason"] == "feature_disabled"
    assert response.json()["upgrade_prompt"]["recommended_plan"] == "pro"


def test_admin_usage_endpoints_return_snapshot(monkeypatch) -> None:
    monkeypatch.setenv("ADAAD_AUDIT_TOKENS", json.dumps({"audit-token": ["audit:read"]}))
    server.metrics.reset_billable_usage()
    server.metrics.reset_conversion_funnel()

    with TestClient(server.app) as client:
        usage_response = client.get("/api/admin/usage", headers={"Authorization": "Bearer audit-token"})
        plan_response = client.get("/api/admin/usage/plan/pro", headers={"Authorization": "Bearer audit-token"})

    assert usage_response.status_code == 200
    usage_payload = usage_response.json()
    assert usage_payload["data"]["usage"]["counters"]["governance_approvals"] >= 0
    assert "conversion_funnel" in usage_payload["data"]
    assert "plan_limits" in usage_payload["data"]

    assert plan_response.status_code == 200
    plan_payload = plan_response.json()
    assert plan_payload["data"]["plan"] == "pro"
    assert "limits" in plan_payload["data"]
    assert "conversion_funnel" in plan_payload["data"]


def test_conversion_funnel_tracks_upgrade_and_activation_moments(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ADAAD_AUDIT_TOKENS", json.dumps({"audit-token": ["audit:read"]}))
    monkeypatch.setenv("ADAAD_HMAC_KEYS", json.dumps({"default": "dev-secret"}))
    server.metrics.reset_billable_usage()
    server.metrics.reset_conversion_funnel()

    replay_file = tmp_path / "epoch-1.replay_manifest.v1.json"
    replay_file.write_text(json.dumps({"epoch_id": "epoch-1", "proof": "ok"}), encoding="utf-8")
    monkeypatch.setattr(server, "REPLAY_PROOFS_DIR", tmp_path)

    with TestClient(server.app) as client:
        denied = client.post(
            "/api/nexus/agents/agent-1/mutate",
            json={"mutation_type": "dna_patch", "payload": {"dna": []}, "signature": "x", "nonce": "n", "timestamp": "2026-01-01T00:00:00Z", "challenge_id": "c"},
            headers={"X-ADAAD-Plan": "free"},
        )
        assert denied.status_code == 402

        upgrade = client.post(
            "/api/admin/usage/upgrade-intent",
            headers={"Authorization": "Bearer audit-token"},
            json={"plan": "pro", "reason": "feature_disabled", "surface": "paywall"},
        )
        assert upgrade.status_code == 200

        runbook = client.post(
            "/api/admin/runbooks/production/complete",
            headers={"Authorization": "Bearer audit-token"},
            json={"runbook_id": "go-live", "completed_by": "ops@innovative.ai"},
        )
        assert runbook.status_code == 200

        replay = client.get(
            "/api/audit/epochs/epoch-1/replay-proof",
            headers={"Authorization": "Bearer audit-token", "X-ADAAD-Plan": "pro"},
        )
        assert replay.status_code == 200

        collaboration = client.post(
            "/api/mutations/proposals",
            json={"intent": "optimize"},
            headers={"X-ADAAD-Plan": "pro"},
        )
        assert collaboration.status_code == 200

        usage = client.get("/api/admin/usage", headers={"Authorization": "Bearer audit-token"})
        counters = usage.json()["data"]["conversion_funnel"]["counters"]

    assert counters["paywall_prompt_presented"] == 1
    assert counters["upgrade_prompt_engaged"] == 1
    assert counters["first_governance_replay_proof"] == 1
    assert counters["first_team_collaboration_event"] == 1
    assert counters["first_production_runbook_completion"] == 1
