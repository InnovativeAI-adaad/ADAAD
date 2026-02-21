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
    from runtime.autonomy.scoreboard import build_scoreboard_views
    from runtime.governance.foundation import coerce_log_entry, safe_get, safe_list, safe_str
except ModuleNotFoundError:  # pragma: no cover - fallback for direct script execution
    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from runtime import metrics
    from runtime.autonomy.scoreboard import build_scoreboard_views
    from runtime.governance.foundation import coerce_log_entry, safe_get, safe_list, safe_str


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
        normalized = coerce_log_entry(entry)
        payload = safe_get(entry, "payload", default={})
        event = safe_str(safe_get(entry, "event"), default=normalized["status"])
        if event != "constitutional_evaluation":
            if not include_rejections or event not in {
                "mutation_rejected_preflight",
                "mutation_rejected_constitutional",
            }:
                continue
        if agent_id and safe_get(payload, "agent_id", default="") != agent_id:
            continue
        if tier and safe_get(payload, "tier", default="") != tier:
            continue
        ts = safe_str(safe_get(entry, "timestamp"), default=normalized["timestamp"])
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
        if safe_get(entry, "event", default="") == "mutation_rejected_preflight":
            payload = safe_get(entry, "payload", default={})
            reason = safe_str(safe_get(payload, "reason"), default="unknown")
            preflight_counts[reason] = preflight_counts.get(reason, 0) + 1
        if safe_get(entry, "event", default="") == "mutation_rejected_constitutional":
            payload = safe_get(entry, "payload", default={})
            failures = safe_list(safe_get(payload, "blocking_failures"))
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
        payload = safe_get(entry, "payload", default={})
        rows.append(
            [
                safe_str(safe_get(entry, "timestamp")),
                safe_str(safe_get(payload, "agent_id")),
                safe_str(safe_get(payload, "tier")),
                str(safe_get(payload, "passed")),
                ",".join(safe_list(safe_get(payload, "blocking_failures"))),
                ",".join(safe_list(safe_get(payload, "warnings"))),
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


def _format_applicability_matrix(entry: Dict[str, Any]) -> str:
    payload = safe_get(entry, "payload", default={})
    matrix = safe_list(safe_get(payload, "applicability_matrix"))
    headers = ["rule", "applicable", "scope_match", "trigger_match", "change_type_match", "fail_behavior"]
    rows = []
    for row in matrix:
        if not isinstance(row, dict):
            continue
        rows.append(
            [
                safe_str(safe_get(row, "rule")),
                str(bool(safe_get(row, "applicable"))),
                str(bool(safe_get(row, "scope_match"))),
                str(bool(safe_get(row, "trigger_match"))),
                str(bool(safe_get(row, "change_type_match"))),
                json.dumps(safe_get(row, "fail_behavior", default={}), sort_keys=True),
            ]
        )
    widths = [len(header) for header in headers]
    for row in rows:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))
    lines = [
        f"PR applicability matrix for agent={safe_str(safe_get(payload, 'agent_id'))} tier={safe_str(safe_get(payload, 'tier'))}",
        " | ".join(header.ljust(widths[i]) for i, header in enumerate(headers)),
        "-+-".join("-" * width for width in widths),
    ]
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


def run_pr_applicability(agent_id: Optional[str], tier: Optional[str], output: str) -> str:
    entries = _load_entries()
    filtered = _filter_entries(entries, agent_id, tier, None, None)
    if not filtered:
        return json.dumps({"error": "no_constitutional_evaluations_found"}, indent=2)
    latest = sorted(filtered, key=lambda item: safe_str(safe_get(item, "timestamp")))[-1]
    if output == "json":
        return json.dumps(
            {
                "timestamp": safe_str(safe_get(latest, "timestamp")),
                "payload": safe_get(latest, "payload", default={}),
            },
            indent=2,
        )
    return _format_applicability_matrix(latest)



def run_autonomy_scoreboard(limit: int, output: str) -> str:
    scoreboard = build_scoreboard_views(limit=limit)
    if output == "json":
        return json.dumps(scoreboard, indent=2)
    return (
        f"performance_by_agent: {json.dumps(scoreboard.get('performance_by_agent', {}), indent=2)}\n"
        f"mutation_outcomes: {json.dumps(scoreboard.get('mutation_outcomes', {}), indent=2)}\n"
        f"sandbox_failure_reasons: {json.dumps(scoreboard.get('sandbox_failure_reasons', {}), indent=2)}"
    )

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="ADAAD constitutional audit")
    parser.add_argument(
        "--action",
        choices=["constitutional-audit", "autonomy-scoreboard", "pr-applicability"],
        default="constitutional-audit",
        help="Choose constitutional audit or autonomy scoreboard reporting.",
    )
    parser.add_argument("--limit", type=int, default=1000, help="Tail limit used by autonomy-scoreboard action.")
    parser.add_argument("--agent-id", help="Filter by agent id")
    parser.add_argument("--tier", help="Filter by tier (PRODUCTION/STABLE/SANDBOX)")
    parser.add_argument("--start", help="Filter evaluations starting at timestamp (YYYY-MM-DDTHH:MM:SSZ)")
    parser.add_argument("--end", help="Filter evaluations ending at timestamp (YYYY-MM-DDTHH:MM:SSZ)")
    parser.add_argument("--output", choices=["json", "table"], default="table")
    args = parser.parse_args(argv)
    if args.action == "autonomy-scoreboard":
        report = run_autonomy_scoreboard(limit=args.limit, output=args.output)
    elif args.action == "pr-applicability":
        report = run_pr_applicability(args.agent_id, args.tier, args.output)
    else:
        report = run_audit(args.agent_id, args.tier, args.start, args.end, args.output)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
