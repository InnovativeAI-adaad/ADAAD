# SPDX-License-Identifier: Apache-2.0
"""
Lightweight metrics analysis helpers for mutation outcomes.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Tuple

from runtime import metrics


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


__all__ = ["summarize_preflight_rejections", "top_preflight_rejections"]
