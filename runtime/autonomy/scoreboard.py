# SPDX-License-Identifier: Apache-2.0
"""Metrics-driven scoreboard views for autonomy improvements."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from runtime import metrics
from runtime.governance.foundation import safe_get, safe_str


def build_scoreboard_views(limit: int = 1000) -> dict[str, Any]:
    try:
        parsed_limit = max(int(limit), 0)
    except (TypeError, ValueError):
        parsed_limit = 0

    try:
        entries = metrics.tail(limit=parsed_limit)
    except OSError:
        entries = []
    perf_by_agent: dict[str, list[int]] = defaultdict(list)
    mutation_outcomes: Counter[str] = Counter()
    sandbox_failures: Counter[str] = Counter()

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        event = safe_str(safe_get(entry, "event"))
        payload = safe_get(entry, "payload", default={})
        if not isinstance(payload, dict):
            payload = {}

        if event == "autonomy_action":
            agent = safe_str(safe_get(payload, "agent"), default="unknown")
            try:
                duration = int(safe_get(payload, "duration_ms", default=0) or 0)
            except (TypeError, ValueError):
                duration = 0
            perf_by_agent[agent].append(duration)

        if event in {"mutation_executed", "mutation_failed", "mutation_rejected_constitutional"}:
            mutation_outcomes[event] += 1

        if event in {"mutation_rejected_preflight", "sandbox_validation_failed"}:
            reason = safe_str(safe_get(payload, "reason"), default="unknown")
            sandbox_failures[reason] += 1

    performance_view: dict[str, dict[str, float]] = {}
    for agent, durations in sorted(perf_by_agent.items()):
        if not durations:
            continue
        performance_view[agent] = {
            "calls": float(len(durations)),
            "avg_duration_ms": round(sum(durations) / len(durations), 2),
            "max_duration_ms": float(max(durations)),
        }

    return {
        "performance_by_agent": performance_view,
        "mutation_outcomes": dict(mutation_outcomes),
        "sandbox_failure_reasons": dict(sandbox_failures),
        "entries_considered": len(entries),
    }
