# SPDX-License-Identifier: Apache-2.0
"""
Lightweight metrics analysis helpers for mutation outcomes.
"""

from __future__ import annotations

import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
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


def _build_lineage_ledger(path: str | Path | None = None) -> Any:
    """Create the lineage ledger lazily to avoid import cycles at module import time."""
    from runtime.evolution.lineage_v2 import LEDGER_V2_PATH, LineageLedgerV2

    env_path = os.environ.get("ADAAD_LINEAGE_PATH", "").strip()
    default_path = Path("data/lineage_v2.jsonl")
    raw_default = LEDGER_V2_PATH if isinstance(LEDGER_V2_PATH, Path) else default_path
    ledger_path = Path(path) if path else (Path(env_path) if env_path else raw_default)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    return LineageLedgerV2(ledger_path)


def rolling_determinism_score(window: int = 200) -> Dict[str, Any]:
    """
    Compute a rolling replay determinism score from recent ReplayVerificationEvent entries.
    """
    if window <= 0:
        window = 1
    replay_entries: List[Dict[str, Any]] = []
    for entry in metrics.tail(window):
        if entry.get("event") == "ReplayVerificationEvent":
            replay_entries.append(entry)

    lineage_entries = _build_lineage_ledger().read_all()
    for entry in lineage_entries[-window:]:
        if entry.get("type") != "ReplayVerificationEvent":
            continue
        replay_entries.append(
            {
                "event": "ReplayVerificationEvent",
                "payload": entry.get("payload") or {},
                "timestamp": "",
                "source": "lineage",
            }
        )
    if not replay_entries:
        return {
            "window": window,
            "sample_size": 0,
            "rolling_score": 1.0,
            "passed": 0,
            "failed": 0,
            "cause_buckets": {},
        }

    score_sum = 0.0
    passed = 0
    failed = 0
    buckets: Counter[str] = Counter()
    for entry in replay_entries:
        payload = entry.get("payload") or {}
        score_sum += float(payload.get("replay_score", 1.0 if payload.get("replay_passed") else 0.0))
        if payload.get("replay_passed"):
            passed += 1
        else:
            failed += 1
        cause_buckets = payload.get("cause_buckets") or {}
        if isinstance(cause_buckets, dict):
            for bucket, active in cause_buckets.items():
                if active:
                    buckets[str(bucket)] += 1

    sample_size = len(replay_entries)
    return {
        "window": window,
        "sample_size": sample_size,
        "rolling_score": round(score_sum / sample_size, 4),
        "passed": passed,
        "failed": failed,
        "cause_buckets": dict(buckets.most_common()),
    }


__all__ = [
    "mutation_rate_snapshot",
    "summarize_preflight_rejections",
    "top_preflight_rejections",
    "rolling_determinism_score",
]
