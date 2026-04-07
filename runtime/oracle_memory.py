# SPDX-License-Identifier: Apache-2.0
"""Oracle memory subsystem for normalized query intelligence."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


_RISK_KEYWORDS = ("divergence", "blocker", "fail", "risk", "replay", "locked")
_OPPORTUNITY_KEYWORDS = ("improv", "opportun", "promot", "growth", "strategy", "horizon")


@dataclass(frozen=True)
class OracleTheme:
    motif: str
    count: int


def _normalize(text: str) -> str:
    return " ".join((text or "").lower().split())


def _theme_for_record(record: Mapping[str, Any]) -> str:
    query_type = _normalize(str(record.get("query_type", "")))
    query = _normalize(str(record.get("normalized_query") or record.get("query", "")))
    if "divergence" in query or "divergence" in query_type:
        return "divergence_concerns"
    if "blocker" in query or "blocked" in query or "gate" in query_type:
        return "blocker_families"
    if "strategy" in query or "performance" in query or "horizon" in query:
        return "strategy_evolution"
    return "general_oracle"


def summarize_oracle_memory(records: Sequence[Mapping[str, Any]], window: int = 10) -> dict[str, Any]:
    """Build deterministic trend intelligence from oracle history."""
    recent = list(records)[-max(1, int(window)) :]
    themes = Counter(_theme_for_record(r) for r in recent)
    query_types = Counter(_normalize(str(r.get("query_type", "generic"))) for r in recent)

    recurring_risk = []
    improving = []
    stagnating = []
    opportunities = []
    for theme, count in themes.items():
        if count < 2:
            continue
        if "divergence" in theme or "blocker" in theme:
            recurring_risk.append({"motif": theme, "count": count})
        if theme == "strategy_evolution":
            improving.append({"area": "strategy_evolution", "signal": "improving", "count": count})
        if theme == "general_oracle":
            stagnating.append({"area": "general_oracle", "signal": "stagnating", "count": count})
    for qtype, count in query_types.items():
        if count >= 2 and any(k in qtype for k in _OPPORTUNITY_KEYWORDS):
            opportunities.append({"cluster": qtype, "count": count})

    trend = "stable"
    if recurring_risk and not opportunities:
        trend = "risk_elevating"
    elif opportunities and not recurring_risk:
        trend = "opportunity_expanding"
    elif opportunities and recurring_risk:
        trend = "mixed_signal"

    return {
        "window": len(recent),
        "call_count": len(recent),
        "themes": [{"motif": k, "count": v} for k, v in themes.most_common()],
        "trend_indicators": {
            "recurring_risk_motifs": recurring_risk,
            "strategy_areas": {
                "improving": improving,
                "stagnating": stagnating,
            },
            "emerging_opportunity_clusters": opportunities,
            "overall_trend": trend,
        },
        "since_last_10_summary": (
            f"Last {len(recent)} calls: "
            f"{', '.join(f'{k}×{v}' for k, v in themes.most_common(3)) or 'no oracle activity'}."
        ),
    }

