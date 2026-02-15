# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path
from urllib.request import urlopen

from runtime.evolution.evidence_bundle import EvidenceBundleBuilder
from runtime.evolution.lineage_v2 import LineageLedgerV2
from ui import aponi_dashboard


class _StaticBundleBuilder:
    def __init__(self, *args, **kwargs) -> None:
        return None

    def build_bundle(self, *, epoch_start: str, epoch_end: str | None = None, persist: bool = True):
        return {
            "bundle_id": f"evidence-{epoch_start}",
            "export_metadata": {
                "digest": "sha256:" + ("a" * 64),
                "canonical_ordering": "json_sort_keys",
                "immutable": True,
                "path": "reports/forensics/evidence.json",
            },
        }


def test_replay_diff_http_endpoint_includes_bundle_metadata(tmp_path, monkeypatch) -> None:
    ledger = LineageLedgerV2(tmp_path / "lineage_v2.jsonl")
    ledger.append_event("EpochStartEvent", {"epoch_id": "epoch-1", "state": {"x": 1}})
    ledger.append_bundle_with_digest(
        "epoch-1",
        {
            "bundle_id": "bundle-1",
            "impact": 0.1,
            "risk_tier": "low",
            "certificate": {"bundle_id": "bundle-1"},
            "strategy_set": [],
        },
    )
    ledger.append_event("EpochEndEvent", {"epoch_id": "epoch-1", "state": {"x": 2}})

    monkeypatch.setattr(aponi_dashboard, "LineageLedgerV2", lambda: ledger)
    monkeypatch.setattr(aponi_dashboard, "EvidenceBundleBuilder", _StaticBundleBuilder)

    dashboard = aponi_dashboard.AponiDashboard(host="127.0.0.1", port=0)
    dashboard.start({"status": "ok"})
    try:
        assert dashboard._server is not None
        port = dashboard._server.server_port
        with urlopen(f"http://127.0.0.1:{port}/replay/diff?epoch_id=epoch-1", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    finally:
        dashboard.stop()

    assert payload["ok"] is True
    assert payload["epoch_id"] == "epoch-1"
    assert payload["bundle_id"] == "evidence-epoch-1"
    assert payload["export_metadata"]["digest"].startswith("sha256:")


def test_replay_diff_http_endpoint_persists_export_bundle(tmp_path, monkeypatch) -> None:
    ledger = LineageLedgerV2(tmp_path / "lineage_v2.jsonl")
    ledger.append_event("EpochStartEvent", {"epoch_id": "epoch-2", "state": {"x": 3}})
    ledger.append_bundle_with_digest(
        "epoch-2",
        {
            "bundle_id": "bundle-2",
            "impact": 0.2,
            "risk_tier": "low",
            "certificate": {"bundle_id": "bundle-2"},
            "strategy_set": [],
        },
    )
    ledger.append_event("EpochEndEvent", {"epoch_id": "epoch-2", "state": {"x": 4}})

    class _ExportingBundleBuilder:
        def __init__(self, ledger: LineageLedgerV2, replay_engine) -> None:
            self._delegate = EvidenceBundleBuilder(
                ledger=ledger,
                replay_engine=replay_engine,
                export_dir=tmp_path / "forensics",
                schema_path=Path("schemas/evidence_bundle.v1.json"),
            )

        def build_bundle(self, *, epoch_start: str, epoch_end: str | None = None, persist: bool = True):
            return self._delegate.build_bundle(epoch_start=epoch_start, epoch_end=epoch_end, persist=persist)

    monkeypatch.setattr(aponi_dashboard, "LineageLedgerV2", lambda: ledger)
    monkeypatch.setattr(aponi_dashboard, "EvidenceBundleBuilder", _ExportingBundleBuilder)

    dashboard = aponi_dashboard.AponiDashboard(host="127.0.0.1", port=0)
    dashboard.start({"status": "ok"})
    try:
        assert dashboard._server is not None
        port = dashboard._server.server_port
        with urlopen(f"http://127.0.0.1:{port}/replay/diff?epoch_id=epoch-2", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    finally:
        dashboard.stop()

    assert payload["ok"] is True
    export_path = Path(payload["export_metadata"]["path"])
    assert export_path.exists()
    persisted = json.loads(export_path.read_text(encoding="utf-8"))
    assert persisted["bundle_id"] == payload["bundle_id"]
