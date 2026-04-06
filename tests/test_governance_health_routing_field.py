# SPDX-License-Identifier: Apache-2.0
"""Tests: routing_health field in GET /governance/health — Phase 23 / PR-23-02"""
from __future__ import annotations

import json

import pytest
pytestmark = pytest.mark.regression_standard
from fastapi.testclient import TestClient

_TOKEN = "pr23-gh-token"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}


@pytest.fixture(autouse=True)
def _set_audit_env(monkeypatch):
    monkeypatch.setenv("ADAAD_AUDIT_TOKENS", json.dumps({_TOKEN: ["audit:read"]}))


@pytest.fixture
def client():
    from server import app
    return TestClient(app, raise_server_exceptions=True)


class TestGovernanceHealthRoutingField:
    def _data(self, client) -> dict:
        resp = client.get("/governance/health", headers=_AUTH)
        assert resp.status_code == 200
        return resp.json()["data"]

    def test_routing_health_field_present(self, client):
        d = self._data(client)
        assert "routing_health" in d

    def test_routing_health_available_is_bool(self, client):
        d = self._data(client)
        assert isinstance(d["routing_health"]["available"], bool)

    def test_routing_health_status_valid(self, client):
        d = self._data(client)
        assert d["routing_health"]["status"] in {"green", "amber", "red"}

    def test_routing_health_score_in_range(self, client):
        d = self._data(client)
        h = d["routing_health"]["health_score"]
        assert 0.0 <= h <= 1.0

    def test_routing_health_analytics_version(self, client):
        d = self._data(client)
        assert d["routing_health"]["analytics_version"] == "22.0"

    def test_existing_fields_unchanged(self, client):
        d = self._data(client)
        for key in ("epoch_id", "health_score", "status", "signal_breakdown",
                    "weight_snapshot_digest", "constitution_version",
                    "scoring_algorithm_version", "degraded", "dependency_degraded", "degradation_reasons"):
            assert key in d, f"missing existing field: {key}"

    def test_degradation_reasons_schema(self, client):
        d = self._data(client)
        assert isinstance(d["degradation_reasons"], list)
        for item in d["degradation_reasons"]:
            assert set(item.keys()) == {"component", "reason_code", "scope"}

    def test_routing_health_score_in_signal_breakdown(self, client):
        d = self._data(client)
        assert "routing_health_score" in d["signal_breakdown"]
