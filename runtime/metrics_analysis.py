# SPDX-License-Identifier: Apache-2.0
"""
Lightweight metrics analysis helpers for mutation outcomes.
"""

from __future__ import annotations

import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Tuple

from runtime import metrics

MUTATION_EVENT_TYPES = {
    "mutation_approved_constitutional",
    "mutation_rejected_constitutional",
    "mutation_planned",
    "mutation_executed",
    "mutation_failed",
    "mutation_noop",
}


def _parse_timestamp(value: str | None) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
        return parsed.replace(tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


def mutation_rate_snapshot(
    window_sec: int,
    max_entries: int = 1000,
    event_types: Iterable[str] | None = None,
    now: float | None = None,
) -> Dict[str, Any]:
    """
    Compute the recent mutation rate over a sliding time window.
    """
    if window_sec <= 0:
        window_sec = 1
    event_filter = set(event_types) if event_types is not None else set(MUTATION_EVENT_TYPES)
    now_ts = now if now is not None else time.time()
    cutoff = now_ts - window_sec
    entries = metrics.tail(max_entries)
    count = 0
    for entry in entries:
        if entry.get("event") not in event_filter:
            continue
        entry_ts = _parse_timestamp(entry.get("timestamp"))
        if entry_ts is None or entry_ts < cutoff:
            continue
        count += 1
    rate_per_hour = count * 3600.0 / window_sec
    return {
        "window_sec": window_sec,
        "window_start_ts": cutoff,
        "window_end_ts": now_ts,
        "count": count,
        "rate_per_hour": rate_per_hour,
        "event_types": sorted(event_filter),
        "entries_considered": len(entries),
    }


def summarize_preflight_rejections(limit: int = 500) -> Dict[str, Any]:
    """
    Summarize preflight rejection reasons over the most recent metrics entries.
    """
    entries = metrics.tail(limit)
    counts: Counter[str] = Counter()
    for entry in entries:
        if entry.get("event") != "mutation_rejected_preflight":
            continue
        payload = entry.get("payload") or {}
        reason = payload.get("reason") or "unknown"
        counts[reason] += 1
    total = sum(counts.values())
    return {
        "window": limit,
        "total": total,
        "reasons": dict(counts.most_common()),
    }


def top_preflight_rejections(limit: int = 500, top_n: int = 5) -> List[Tuple[str, int]]:
    """
    Return the most frequent preflight rejection reasons.
    """
    summary = summarize_preflight_rejections(limit)
    reasons = summary.get("reasons", {})
    return list(reasons.items())[:top_n]


__all__ = [
    "mutation_rate_snapshot",
    "summarize_preflight_rejections",
    "top_preflight_rejections",
]
