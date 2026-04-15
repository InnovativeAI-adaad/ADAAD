# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import ui as ui_api
from app.api.dependencies import require_audit_scope
from runtime.governance import dork_proposal_adapter as adapter


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(ui_api.router)
    app.dependency_overrides[require_audit_scope] = lambda: {"scopes": ["audit:read"]}
    return TestClient(app, raise_server_exceptions=True)


def _write_profile(path: Path, *, enabled: bool) -> None:
    payload = {
        "dependency_lock": {"path": "requirements.txt", "sha256": "unused-in-endpoint-test"},
        "runtime_manifest": {"governance_modes": []},
        "agents": {
            "grok-integrator": {
                "enabled": enabled,
                "provider": "xai",
                "profile": "governance-observer",
                "metadata": {},
            }
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_dork_execute_proposal_profile_state_transitions(monkeypatch, tmp_path: Path) -> None:
    profile_path = tmp_path / "governance_runtime_profile.lock.json"
    credential_path = tmp_path / "grok_pat.vault"
    _write_profile(profile_path, enabled=False)

    monkeypatch.setattr(adapter, "_RUNTIME_PROFILE_LOCK_PATH", profile_path)
    monkeypatch.setattr(adapter, "_DEFAULT_GROK_CREDENTIAL_PATH", credential_path)
    monkeypatch.setattr(adapter, "validate_proposal", lambda payload: (payload, {"ok": True}))
    monkeypatch.setattr(
        adapter,
        "append_proposal",
        lambda *, proposal_id, request: {"event_type": "mcp_proposal_queued", "hash": f"sha256:{proposal_id}:{len(request)}"},
    )

    class _GateDecision:
        approved = True
        reason_codes = ()
        decision_id = "gate-decision-id"
        decision = "approve"

    class _Gate:
        def approve_mutation(self, **_kwargs):
            return _GateDecision()

    monkeypatch.setattr(adapter, "GovernanceGate", _Gate)

    payload = {
        "proposal": {"summary": "test", "targets": [], "authority_level": "governor-review"},
        "trust_mode": "standard",
        "actor": "dork",
    }

    with _client() as client:
        disabled_response = client.post("/api/dork/proposals/execute", json=payload)
        assert disabled_response.status_code == 423
        assert disabled_response.json()["detail"] == "grok_disabled"

        _write_profile(profile_path, enabled=True)
        creds_missing_response = client.post("/api/dork/proposals/execute", json=payload)
        assert creds_missing_response.status_code == 423
        assert creds_missing_response.json()["detail"] == "grok_credentials_missing"

        credential_path.write_text("ghp_test_token", encoding="utf-8")
        success_response = client.post("/api/dork/proposals/execute", json=payload)
        assert success_response.status_code == 200
        assert success_response.json()["ok"] is True
