# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import ui as ui_api
from app.api.dependencies import require_audit_scope
from app.api.schemas.dork_intents import (
    DorkEvidenceRef,
    DorkExecutionMarker,
    DorkIntentBundle,
    DorkTrustMetadata,
)


def _bundle(*, intent: str, summary: str, response: dict[str, object]) -> DorkIntentBundle:
    return DorkIntentBundle(
        intent=intent,
        marker=DorkExecutionMarker(advisory_only=True, actionable_next_step=False),
        summary=summary,
        response=response,
        evidence_refs=[DorkEvidenceRef(source="tests", endpoint="/tests")],
        aponi_panels=["/ui/aponi/index.html"],
        bundle_digest="digest-1",
        trust_metadata=DorkTrustMetadata(
            data_sources_used=["tests:/tests"],
            snapshot_timestamp=datetime.now(timezone.utc),
            snapshot_freshness="fresh",
            mode="deterministic",
            confidence=1.0,
            uncertainty_reasons=[],
            trust_score=1.0,
            downgrade_reasons=[],
        ),
    )


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(ui_api.router)
    app.dependency_overrides[require_audit_scope] = lambda: {"scope": "audit:read"}
    return TestClient(app)


def test_console_route_returns_approved_outcome(monkeypatch) -> None:
    monkeypatch.setattr(
        ui_api,
        "_execute_dork_bundle",
        lambda _request: _bundle(intent="show_gate_status", summary="Gate is healthy.", response={"gate_locked": False}),
    )

    with _client() as client:
        response = client.post("/api/dork/console/route", json={"query": "show gate status"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["outcome"] == "approved"
    assert payload["outcome_reason"] == "advisory_clear"
    assert payload["bundle"]["intent"] == "show_gate_status"


def test_console_route_returns_governance_blocked(monkeypatch) -> None:
    monkeypatch.setattr(
        ui_api,
        "_execute_dork_bundle",
        lambda _request: _bundle(
            intent="prepare_mutation_review",
            summary="Mutation path blocked.",
            response={"transition": {"status": "warn", "reason": "mutation_blocked_fail_closed"}},
        ),
    )

    with _client() as client:
        response = client.post("/api/dork/console/route", json={"query": "prepare mutation review"})

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error_code"] == "governance_blocked"
    assert detail["detail"]["reason"] == "mutation_blocked_fail_closed"


def test_console_route_enforces_request_validation() -> None:
    with _client() as client:
        response = client.post("/api/dork/console/route", json={"query": ""})

    assert response.status_code == 422
