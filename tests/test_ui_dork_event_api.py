# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import ui as ui_api
from security.ledger import journal


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(ui_api.router)
    return TestClient(app)


def test_append_dork_event_persists_with_deterministic_seq(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ui_api, "_DORK_EVENT_LEDGER_PATH", tmp_path / "dork_events.jsonl")
    monkeypatch.setattr(journal, "LEDGER_FILE", tmp_path / "lineage.jsonl")
    ui_api._STREAM_SUBSCRIBERS.clear()

    payload = {
        "source": "ui",
        "event_type": "refresh",
        "severity": "info",
        "payload": {"panel": "overview"},
        "correlation_id": "corr-1",
        "epoch_id": "epoch-12",
        "ts": "2026-04-06T10:00:00Z",
    }
    with _client() as client:
        first = client.post("/api/ledger/log/events", json=payload)
        second = client.post("/api/ledger/log/events", json={**payload, "correlation_id": "corr-2"})

    assert first.status_code == 200
    assert second.status_code == 200
    first_event = first.json()["event"]
    second_event = second.json()["event"]
    assert first_event["seq"] == 1
    assert second_event["seq"] == 2
    assert first_event["ts"] == "2026-04-06T10:00:00Z"
    lines = (tmp_path / "dork_events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["correlation_id"] == "corr-1"


def test_append_dork_event_rejects_non_iso_timestamp(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ui_api, "_DORK_EVENT_LEDGER_PATH", tmp_path / "dork_events.jsonl")
    monkeypatch.setattr(journal, "LEDGER_FILE", tmp_path / "lineage.jsonl")
    ui_api._STREAM_SUBSCRIBERS.clear()

    payload = {
        "source": "ui",
        "event_type": "refresh",
        "severity": "info",
        "payload": {},
        "correlation_id": "corr-1",
        "epoch_id": "epoch-12",
        "ts": "not-a-timestamp",
    }
    with _client() as client:
        response = client.post("/api/ledger/log/events", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"] == "ts_must_be_iso8601"
