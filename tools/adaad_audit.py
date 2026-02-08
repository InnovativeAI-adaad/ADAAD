# SPDX-License-Identifier: Apache-2.0
"""
Constitutional audit CLI for ADAAD metrics.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

try:
    from runtime import metrics
except ModuleNotFoundError:  # pragma: no cover - fallback for direct script execution
    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from runtime import metrics


def _parse_timestamp(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")


def _load_entries() -> List[Dict[str, Any]]:
    if not metrics.METRICS_PATH.exists():
        return []
    entries: List[Dict[str, Any]] = []
    for line in metrics.METRICS_PATH.read_text(encoding="utf-8").splitlines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def _filter_entries(
    entries: Iterable[Dict[str, Any]],
    agent_id: Optional[str],
    tier: Optional[str],
    start: Optional[str],
    end: Optional[str],
    include_rejections: bool = False,
) -> List[Dict[str, Any]]:
    start_dt = _parse_timestamp(start) if start else None
    end_dt = _parse_timestamp(end) if end else None
    filtered: List[Dict[str, Any]] = []
    for entry in entries:
        payload = entry.get("payload") or {}
        event = entry.get("event")
        if event != "constitutional_evaluation":
            if not include_rejections or event not in {
                "mutation_rejected_preflight",
                "mutation_rejected_constitutional",
            }:
                continue
        if agent_id and payload.get("agent_id") != agent_id:
            continue
        if tier and payload.get("tier") != tier:
            continue
        ts = entry.get("timestamp")
        if ts and (start_dt or end_dt):
            ts_dt = _parse_timestamp(ts)
            if start_dt and ts_dt < start_dt:
                continue
            if end_dt and ts_dt > end_dt:
                continue
        filtered.append(entry)
    return filtered


def _summarize_violations(entries: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    preflight_counts: Dict[str, int] = {}
    constitutional_counts: Dict[str, int] = {}
    for entry in entries:
        if entry.get("event") == "mutation_rejected_preflight":
            payload = entry.get("payload") or {}
            reason = payload.get("reason", "unknown")
            preflight_counts[reason] = preflight_counts.get(reason, 0) + 1
        if entry.get("event") == "mutation_rejected_constitutional":
            payload = entry.get("payload") or {}
            failures = payload.get("blocking_failures") or []
            for failure in failures:
                constitutional_counts[failure] = constitutional_counts.get(failure, 0) + 1
    return {
        "preflight": preflight_counts,
        "constitutional": constitutional_counts,
    }


def _format_table(entries: List[Dict[str, Any]]) -> str:
    headers = ["timestamp", "agent", "tier", "passed", "blocking", "warnings"]
    rows = []
    for entry in entries:
        payload = entry.get("payload") or {}
        rows.append(
            [
                entry.get("timestamp", ""),
                payload.get("agent_id", ""),
                payload.get("tier", ""),
                str(payload.get("passed")),
                ",".join(payload.get("blocking_failures") or []),
                ",".join(payload.get("warnings") or []),
            ]
        )
    widths = [len(header) for header in headers]
    for row in rows:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))
    lines = []
    header_line = " | ".join(header.ljust(widths[i]) for i, header in enumerate(headers))
    separator = "-+-".join("-" * width for width in widths)
    lines.append(header_line)
    lines.append(separator)
    for row in rows:
        lines.append(" | ".join(row[i].ljust(widths[i]) for i in range(len(headers))))
    return "\n".join(lines)


def run_audit(
    agent_id: Optional[str],
    tier: Optional[str],
    start: Optional[str],
    end: Optional[str],
    output: str,
) -> str:
    entries = _load_entries()
    filtered = _filter_entries(entries, agent_id, tier, start, end)
    summary_entries = _filter_entries(
        entries,
        agent_id,
        tier,
        start,
        end,
        include_rejections=True,
    )
    violations = _summarize_violations(summary_entries)
    if output == "json":
        return json.dumps({"evaluations": filtered, "violations": violations}, indent=2)
    table = _format_table(filtered)
    summary = json.dumps(violations, indent=2)
    return f"{table}\n\nViolations:\n{summary}"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="ADAAD constitutional audit")
    parser.add_argument("--agent-id", help="Filter by agent id")
    parser.add_argument("--tier", help="Filter by tier (PRODUCTION/STABLE/SANDBOX)")
    parser.add_argument("--start", help="Filter evaluations starting at timestamp (YYYY-MM-DDTHH:MM:SSZ)")
    parser.add_argument("--end", help="Filter evaluations ending at timestamp (YYYY-MM-DDTHH:MM:SSZ)")
    parser.add_argument("--output", choices=["json", "table"], default="table")
    args = parser.parse_args(argv)
    report = run_audit(args.agent_id, args.tier, args.start, args.end, args.output)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
