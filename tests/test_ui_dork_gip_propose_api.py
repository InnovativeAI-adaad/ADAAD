# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import ui as ui_api


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(ui_api.router)
    app.dependency_overrides[ui_api.require_audit_scope] = lambda: {"scope": "audit"}
    return TestClient(app)


def test_gip_propose_stages_successfully(monkeypatch) -> None:
    class _Adapter:
        def __init__(self, repo_root):
            self.repo_root = repo_root

        def stage(self, *, simulation: bool, trigger: str, verified_sha: str):
            assert simulation is False
            assert trigger == "ADAAD"
            assert verified_sha == "a" * 40
            return {
                "status": "executed",
                "proposal_id": "grok-proposal-123",
            }

    monkeypatch.setattr(ui_api, "GovernanceProposalAdapter", _Adapter)

    with _client() as client:
        response = client.post(
            "/api/dork/gip/propose",
            json={"simulation": False, "trigger": "ADAAD", "verified_sha": "a" * 40},
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "executed",
        "proposal_id": "grok-proposal-123",
        "failure": None,
    }


def test_gip_propose_returns_blocked_governance_failure(monkeypatch) -> None:
    class _Adapter:
        def __init__(self, repo_root):
            self.repo_root = repo_root

        def stage(self, *, simulation: bool, trigger: str, verified_sha: str):
            return {
                "status": "blocked",
                "proposal_id": "grok-proposal-456",
                "failure": {
                    "code": "governance_gate_rejected",
                    "message": "Proposal submission rejected by GovernanceGate.",
                    "details": {"failed_rules": ["RULE-1"]},
                },
            }

    monkeypatch.setattr(ui_api, "GovernanceProposalAdapter", _Adapter)

    with _client() as client:
        response = client.post(
            "/api/dork/gip/propose",
            json={"simulation": False, "trigger": "DEVADAAD", "verified_sha": "b" * 40},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "blocked"
    assert payload["proposal_id"] == "grok-proposal-456"
    assert payload["failure"]["code"] == "governance_gate_rejected"


def test_gip_propose_rejects_invalid_payload_schema() -> None:
    with _client() as client:
        response = client.post(
            "/api/dork/gip/propose",
            json={"simulation": False, "trigger": "ADAAD", "verified_sha": "not-a-sha"},
        )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(item["loc"][-1] == "verified_sha" for item in detail)
