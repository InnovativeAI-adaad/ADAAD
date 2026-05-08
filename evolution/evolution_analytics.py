# SPDX-License-Identifier: Apache-2.0
"""Evolution analytics and reporting utilities."""

from __future__ import annotations


def summarize_cycles(records: list[dict[str, float]]) -> dict[str, float]:
    if not records:
        return {"avg_fitness": 0.0, "success_rate": 0.0, "avg_efficiency": 0.0, "avg_revenue_alignment": 0.0}
    total = len(records)
    success = sum(1 for r in records if r.get("status") == "pass")
    return {
        "avg_fitness": sum(r.get("fitness", 0.0) for r in records) / total,
        "success_rate": success / total,
        "avg_efficiency": sum(r.get("efficiency", 0.0) for r in records) / total,
        "avg_revenue_alignment": sum(r.get("revenue", 0.0) for r in records) / total,
    }
