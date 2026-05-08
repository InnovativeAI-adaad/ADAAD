# SPDX-License-Identifier: Apache-2.0
"""Revenue-alignment scoring primitives."""

from __future__ import annotations


def score_revenue_alignment(*, market_impact: float, scalability: float, compute_efficiency: float) -> float:
    values = [market_impact, scalability, compute_efficiency]
    bounded = [min(1.0, max(0.0, v)) for v in values]
    return sum(bounded) / len(bounded)
