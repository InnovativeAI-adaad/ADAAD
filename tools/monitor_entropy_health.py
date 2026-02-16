#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Monitor entropy envelope health for recent epochs."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from runtime.evolution.lineage_v2 import LineageLedgerV2


def _parse_ts(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    candidate = raw.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _epoch_windows(entries: list[dict[str, Any]]) -> dict[str, dict[str, datetime]]:
    windows: dict[str, dict[str, datetime]] = {}
    for entry in entries:
        event_type = str(entry.get("type") or "")
        if event_type not in {"EpochStartEvent", "EpochEndEvent"}:
            continue
        payload = dict(entry.get("payload") or {})
        epoch_id = str(payload.get("epoch_id") or "").strip()
        if not epoch_id:
            continue
        ts = _parse_ts(payload.get("ts"))
        if ts is None:
            continue
        record = windows.setdefault(epoch_id, {})
        if event_type == "EpochStartEvent":
            current = record.get("start")
            if current is None or ts < current:
                record["start"] = ts
        else:
            current = record.get("end")
            if current is None or ts > current:
                record["end"] = ts
    return windows


def select_recent_epoch_ids(entries: list[dict[str, Any]], *, days: int, now: datetime | None = None) -> list[str]:
    reference_now = now.astimezone(timezone.utc) if now is not None else datetime.now(timezone.utc)
    cutoff = reference_now - timedelta(days=max(0, days))

    windows = _epoch_windows(entries)
    selected: list[str] = []
    for epoch_id, record in windows.items():
        start_ts = record.get("start")
        end_ts = record.get("end")
        if (start_ts and start_ts >= cutoff) or (end_ts and end_ts >= cutoff):
            selected.append(epoch_id)
    return selected


def build_health_report(entries: list[dict[str, Any]], epoch_ids: list[str]) -> dict[str, Any]:
    if not epoch_ids:
        return {
            "overflow_events": 0,
            "max_consumption_observed": 0,
            "budget_utilization_pct": 0.0,
            "status": "ok",
        }

    epoch_set = set(epoch_ids)
    overflow_events = 0
    max_consumption_observed = 0
    max_budget_observed = 0

    for entry in entries:
        payload = dict(entry.get("payload") or {})
        epoch_id = str(payload.get("epoch_id") or "")
        if epoch_id not in epoch_set:
            continue
        if "entropy_consumed" not in payload:
            continue

        consumed = max(0, int(payload.get("entropy_consumed", 0) or 0))
        budget = max(0, int(payload.get("entropy_budget", 0) or 0))
        overflow = bool(payload.get("entropy_overflow", False))

        max_consumption_observed = max(max_consumption_observed, consumed)
        max_budget_observed = max(max_budget_observed, budget)
        if overflow:
            overflow_events += 1

    budget_utilization_pct = 0.0
    if max_budget_observed > 0:
        budget_utilization_pct = round((max_consumption_observed / max_budget_observed) * 100.0, 2)

    status = "alert" if overflow_events > 0 else "ok"
    return {
        "overflow_events": overflow_events,
        "max_consumption_observed": max_consumption_observed,
        "budget_utilization_pct": budget_utilization_pct,
        "status": status,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor entropy health over a recent time window")
    parser.add_argument("--ledger", type=Path, default=None, help="Optional lineage_v2 ledger path")
    parser.add_argument("--days", type=int, default=7, help="Look back this many days by epoch timestamp")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args()

    ledger = LineageLedgerV2(args.ledger) if args.ledger else LineageLedgerV2()
    entries = ledger.read_all()
    epoch_ids = select_recent_epoch_ids(entries, days=args.days)
    report = build_health_report(entries, epoch_ids)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("Entropy Health Monitor")
        print(f"- overflow_events: {report['overflow_events']}")
        print(f"- max_consumption_observed: {report['max_consumption_observed']}")
        print(f"- budget_utilization_pct: {report['budget_utilization_pct']:.2f}")
        print(f"- status: {report['status']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
