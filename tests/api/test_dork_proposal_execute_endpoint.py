# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import ui as ui_api
from app.api.dependencies import require_audit_scope
from runtime.governance.dork_proposal_adapter import DorkProposalResult


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(ui_api.router)
    app.dependency_overrides[require_audit_scope] = lambda: {"scopes": ["audit:read"]}
    return TestClient(app, raise_server_exceptions=True)


def test_dork_execute_proposal_route_registration() -> None:
    app = FastAPI()
    app.include_router(ui_api.router)
    route_paths = {route.path for route in app.routes}
    assert "/api/dork/proposals/execute" in route_paths


def test_dork_execute_proposal_validation_error() -> None:
    with _client() as client:
        response = client.post(
            "/api/dork/proposals/execute",
            json={"trust_mode": "standard", "actor": "dork"},
        )
    assert response.status_code == 422


def test_dork_execute_proposal_response_contract(monkeypatch) -> None:
    monkeypatch.setattr(
        ui_api,
        "execute_dork_proposal",
        lambda **_kwargs: DorkProposalResult(
            proposal_id="dork-proposal-123",
            gate_decision_id="gate-abc",
            governance_decision="approve",
            queued_event_type="mcp_proposal_queued",
            queue_hash="sha256:123",
        ),
    )
    with _client() as client:
        response = client.post(
            "/api/dork/proposals/execute",
            json={
                "proposal": {"summary": "test", "targets": [], "authority_level": "governor-review"},
                "trust_mode": "standard",
                "actor": "dork",
            },
        )
    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "proposal_id": "dork-proposal-123",
        "gate_decision_id": "gate-abc",
        "governance_decision": "approve",
        "queued_event_type": "mcp_proposal_queued",
        "queue_hash": "sha256:123",
    }
