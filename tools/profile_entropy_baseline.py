#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Profile entropy-envelope baseline across recent epochs."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from runtime.evolution.lineage_v2 import LineageLedgerV2
from runtime.evolution.telemetry_audit import detect_entropy_drift, get_epoch_entropy_envelope_summary


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * max(0.0, min(100.0, pct)) / 100.0
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return float(ordered[lower] * (1.0 - weight) + ordered[upper] * weight)


def _recommended_budget(consumed_max_p95: float, *, headroom: float = 1.2, floor_offset: int = 10) -> int:
    return int(math.floor(max(0.0, consumed_max_p95) * max(1.0, headroom) + max(0, floor_offset)))


def compute_report(
    summaries: list[dict[str, Any]],
    drift: dict[str, Any],
    *,
    recommended_headroom: float = 1.2,
    recommended_offset: int = 10,
) -> dict[str, Any]:
    consumed_avg = [float(item.get("consumed_avg", 0.0) or 0.0) for item in summaries]
    consumed_max = [float(item.get("consumed_max", 0.0) or 0.0) for item in summaries]
    overflow_total = int(sum(int(item.get("overflow_count", 0) or 0) for item in summaries))
    decision_total = int(sum(int(item.get("decision_events", 0) or 0) for item in summaries))

    consumed_avg_p50 = _percentile(consumed_avg, 50)
    consumed_avg_p95 = _percentile(consumed_avg, 95)
    consumed_avg_p99 = _percentile(consumed_avg, 99)
    consumed_max_p50 = _percentile(consumed_max, 50)
    consumed_max_p95 = _percentile(consumed_max, 95)
    consumed_max_p99 = _percentile(consumed_max, 99)

    return {
        "epochs_considered": len(summaries),
        "decision_events_total": decision_total,
        "overflow_total": overflow_total,
        "consumed_avg_p50": consumed_avg_p50,
        "consumed_avg_p95": consumed_avg_p95,
        "consumed_avg_p99": consumed_avg_p99,
        "consumed_max_p50": consumed_max_p50,
        "consumed_max_p95": consumed_max_p95,
        "consumed_max_p99": consumed_max_p99,
        "recommended_budget": _recommended_budget(
            consumed_max_p95,
            headroom=recommended_headroom,
            floor_offset=recommended_offset,
        ),
        "drift": drift,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Profile deterministic-envelope entropy baselines")
    parser.add_argument("--ledger", type=Path, default=None, help="Optional path to lineage_v2.jsonl")
    parser.add_argument("--lookback", type=int, default=100, help="Epoch lookback window")
    parser.add_argument("--min-decisions", type=int, default=1, help="Min decision events per epoch")
    parser.add_argument("--headroom", type=float, default=1.2, help="Budget multiplier for p95 consumed_max")
    parser.add_argument("--offset", type=int, default=10, help="Additional fixed budget offset")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument("--fail-on-drift", action="store_true", help="Exit non-zero when drift is detected")
    parser.add_argument("--fail-on-overflow", action="store_true", help="Exit non-zero when overflow_total > 0")
    args = parser.parse_args()

    ledger = LineageLedgerV2(args.ledger) if args.ledger else LineageLedgerV2()
    epoch_ids = ledger.list_epoch_ids()
    if args.lookback > 0:
        epoch_ids = epoch_ids[-args.lookback :]

    summaries = [get_epoch_entropy_envelope_summary(epoch_id, ledger=ledger) for epoch_id in epoch_ids]
    summaries = [item for item in summaries if int(item.get("decision_events", 0)) >= args.min_decisions]

    drift = detect_entropy_drift(
        lookback_epochs=args.lookback,
        ledger=ledger,
        min_decisions_per_epoch=args.min_decisions,
    )

    report = compute_report(
        summaries,
        drift,
        recommended_headroom=args.headroom,
        recommended_offset=args.offset,
    )

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("Entropy Envelope Baseline")
        print(f"- epochs_considered: {report['epochs_considered']}")
        print(f"- decision_events_total: {report['decision_events_total']}")
        print(f"- overflow_total: {report['overflow_total']}")
        print(
            "- consumed_avg p50/p95/p99: "
            f"{report['consumed_avg_p50']:.2f}/{report['consumed_avg_p95']:.2f}/{report['consumed_avg_p99']:.2f}"
        )
        print(
            "- consumed_max p50/p95/p99: "
            f"{report['consumed_max_p50']:.2f}/{report['consumed_max_p95']:.2f}/{report['consumed_max_p99']:.2f}"
        )
        print(f"- recommended_budget: {report['recommended_budget']}")
        print(f"- drift_detected: {bool(report['drift'].get('drift_detected', False))}")
        print(f"- drift_ratio: {float(report['drift'].get('drift_ratio', 0.0)):.2f}")

    drift_detected = bool(report.get("drift", {}).get("drift_detected", False))
    overflow_detected = int(report.get("overflow_total", 0) or 0) > 0
    if args.fail_on_drift and drift_detected:
        return 2
    if args.fail_on_overflow and overflow_detected:
        return 3

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
