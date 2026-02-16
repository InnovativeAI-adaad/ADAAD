# SPDX-License-Identifier: Apache-2.0

import subprocess
from pathlib import Path

from runtime.evolution.lineage_v2 import LineageLedgerV2
from tools.profile_entropy_baseline import compute_report


def test_compute_report_recommended_budget_and_percentiles() -> None:
    summaries = [
        {"decision_events": 2, "overflow_count": 0, "consumed_avg": 5.0, "consumed_max": 7.0},
        {"decision_events": 2, "overflow_count": 1, "consumed_avg": 10.0, "consumed_max": 14.0},
        {"decision_events": 1, "overflow_count": 0, "consumed_avg": 12.0, "consumed_max": 20.0},
    ]
    drift = {"drift_detected": False}
    report = compute_report(summaries, drift, recommended_headroom=1.2, recommended_offset=10)

    assert report["epochs_considered"] == 3
    assert report["decision_events_total"] == 5
    assert report["overflow_total"] == 1
    assert report["consumed_max_p95"] > 14.0
    assert report["recommended_budget"] == int(report["consumed_max_p95"] * 1.2 + 10)


def test_compute_report_handles_empty_input() -> None:
    report = compute_report([], {"drift_detected": False})

    assert report["epochs_considered"] == 0
    assert report["decision_events_total"] == 0
    assert report["overflow_total"] == 0
    assert report["consumed_avg_p95"] == 0.0
    assert report["consumed_max_p95"] == 0.0
    assert report["recommended_budget"] == 10


def test_cli_fail_flags_return_non_zero_on_issues(tmp_path) -> None:
    ledger_path = tmp_path / "lineage_v2.jsonl"
    ledger = LineageLedgerV2(ledger_path)
    for idx, consumed in enumerate([5, 6, 7, 20, 24, 28], start=1):
        ledger.append_event(
            "MutationBundleEvent",
            {
                "epoch_id": f"epoch-{idx}",
                "accepted": True,
                "entropy_consumed": consumed,
                "entropy_budget": 10,
                "entropy_overflow": idx >= 5,
            },
        )

    cmd = [
        "python",
        "tools/profile_entropy_baseline.py",
        "--ledger",
        str(ledger_path),
        "--lookback",
        "10",
        "--fail-on-drift",
    ]
    run = subprocess.run(cmd, cwd=Path(__file__).resolve().parents[2], check=False, capture_output=True, text=True)
    assert run.returncode == 2

    cmd_overflow = [
        "python",
        "tools/profile_entropy_baseline.py",
        "--ledger",
        str(ledger_path),
        "--lookback",
        "10",
        "--fail-on-overflow",
    ]
    run_overflow = subprocess.run(
        cmd_overflow, cwd=Path(__file__).resolve().parents[2], check=False, capture_output=True, text=True
    )
    assert run_overflow.returncode == 3
