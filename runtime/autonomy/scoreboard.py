# SPDX-License-Identifier: Apache-2.0
"""Metrics-driven scoreboard views for autonomy improvements."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from runtime import metrics


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
        event = entry.get("event")
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            payload = {}

        if event == "autonomy_action":
            agent = str(payload.get("agent") or "unknown")
            try:
                duration = int(payload.get("duration_ms") or 0)
            except (TypeError, ValueError):
                duration = 0
            perf_by_agent[agent].append(duration)

        if event in {"mutation_executed", "mutation_failed", "mutation_rejected_constitutional"}:
            mutation_outcomes[event] += 1

        if event in {"mutation_rejected_preflight", "sandbox_validation_failed"}:
            reason = str(payload.get("reason") or "unknown")
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
