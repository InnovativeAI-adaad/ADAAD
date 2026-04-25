# SPDX-License-Identifier: Apache-2.0
"""Phase 160 — INNOV-66 · EBS tests."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from dorkllm.emergent_sentinel import EBSChainError, EmergentSentinel
from dorkllm.telemetry_hub import CGTHEventType, ConstitutionalGovernanceTelemetryHub


def _build_sentinel(tmp_path):
    hub = ConstitutionalGovernanceTelemetryHub(ledger_path=tmp_path / "cgth.jsonl")
    return EmergentSentinel(root=tmp_path, hub=hub), hub


def test_detect_deterministic_replay_equality(tmp_path):
    sentinel, _ = _build_sentinel(tmp_path)
    payload = {
        "signal": "governance_entropy_spike",
        "severity": "HIGH",
        "context": {"domain": "mutation", "score": 0.92},
    }
    first = sentinel.detect(payload)
    second = sentinel.detect(payload)

    assert first.alert_id == second.alert_id
    assert first.baseline_digest == second.baseline_digest
    assert first.severity == second.severity


def test_alert_chain_integrity_and_break_fail_closed(tmp_path):
    sentinel, _ = _build_sentinel(tmp_path)
    payload = {"signal": "replay_divergence", "severity": "HIGH", "context": {"count": 1}}
    sentinel.detect(payload)
    assert sentinel.alerts_chain()["chain_intact"] is True

    alerts_path = tmp_path / "ebs_alerts.jsonl"
    rows = alerts_path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(rows[-1])
    tampered["prev_hmac"] = "f" * 64
    rows[-1] = json.dumps(tampered, sort_keys=True)
    alerts_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    with pytest.raises(EBSChainError):
        sentinel.detect({"signal": "replay_divergence", "severity": "HIGH", "context": {"count": 2}})


def test_critical_emits_human0_before_alert_ledger_write(tmp_path):
    sentinel, hub = _build_sentinel(tmp_path)
    result = sentinel.detect({"signal": "chain_compromise", "severity": "CRITICAL", "context": {"zone": "alert"}})
    assert result.alert_written is True

    records = hub.query()
    human0_idx = next(i for i, rec in enumerate(records) if rec.event_type == CGTHEventType.HUMAN0_AUTHORISATION)
    perm_idx = next(i for i, rec in enumerate(records) if rec.event_type == CGTHEventType.PERM_SNAPSHOT)
    assert human0_idx < perm_idx


@pytest.fixture
def client(tmp_path, monkeypatch):
    from dorkllm import emergent_sentinel as sentinel_module
    from fastapi import FastAPI
    from app.api.emergent_sentinel import router as ebs_router

    monkeypatch.setenv("ADAAD_EBS_ROOT", str(tmp_path))
    monkeypatch.setattr(sentinel_module, "_DEFAULT", None)
    app = FastAPI()
    app.include_router(ebs_router)
    return TestClient(app)


def test_ebs_routes_return_200_and_json_sanity(client):
    detect_resp = client.post(
        "/api/governance/ebs/detect",
        json={"signal": "route_smoke", "severity": "HIGH", "context": {"k": "v"}},
    )
    assert detect_resp.status_code == 200
    detect_json = detect_resp.json()
    assert detect_json["ok"] is True
    assert set(detect_json["result"]).issuperset({"alert_id", "severity", "baseline_digest", "alert_written"})

    status_resp = client.get("/api/governance/ebs/status")
    assert status_resp.status_code == 200
    assert set(status_resp.json()).issuperset({"component", "baseline_events", "alert_events", "baseline_chain_intact", "alert_chain_intact"})

    baseline_resp = client.get("/api/governance/ebs/baseline/chain")
    assert baseline_resp.status_code == 200
    assert set(baseline_resp.json()).issuperset({"chain", "count", "chain_intact"})

    alert_resp = client.get("/api/governance/ebs/alerts/chain")
    assert alert_resp.status_code == 200
    assert set(alert_resp.json()).issuperset({"chain", "count", "chain_intact"})
