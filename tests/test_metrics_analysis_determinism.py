# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from runtime import metrics
from runtime.evolution.lineage_v2 import LineageLedgerV2
from runtime.metrics_analysis import rolling_determinism_score


def test_rolling_determinism_score_aggregates_metrics_and_lineage(tmp_path: Path, monkeypatch) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    monkeypatch.setattr(metrics, "METRICS_PATH", metrics_path)

    ledger = LineageLedgerV2(tmp_path / "lineage_v2.jsonl")
    monkeypatch.setattr("runtime.metrics_analysis.LineageLedgerV2", lambda: ledger)

    metrics.log(
        "ReplayVerificationEvent",
        {
            "replay_passed": False,
            "replay_score": 0.4,
            "cause_buckets": {"digest_mismatch": True, "baseline_mismatch": False},
        },
    )
    ledger.append_event(
        "ReplayVerificationEvent",
        {
            "replay_passed": True,
            "replay_score": 1.0,
            "cause_buckets": {"digest_mismatch": False, "baseline_mismatch": False},
        },
    )

    summary = rolling_determinism_score(window=50)

    assert summary["sample_size"] == 2
    assert summary["rolling_score"] == 0.7
    assert summary["passed"] == 1
    assert summary["failed"] == 1
    assert summary["cause_buckets"]["digest_mismatch"] == 1
