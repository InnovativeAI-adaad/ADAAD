# SPDX-License-Identifier: Apache-2.0
"""Deterministic scoring primitives for evolution/governance decisions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScoreBand:
    label: str
    threshold: float


DEFAULT_AUTHORITY_BANDS: tuple[ScoreBand, ...] = (
    ScoreBand(label="low-impact", threshold=0.20),
    ScoreBand(label="governor-review", threshold=0.50),
    ScoreBand(label="high-impact", threshold=1.00),
)


def clamp_score(score: float) -> float:
    """Normalize score to deterministic [0.0, 1.0] range."""

    return min(max(float(score), 0.0), 1.0)


def authority_threshold(level: str, bands: tuple[ScoreBand, ...] = DEFAULT_AUTHORITY_BANDS) -> float:
    """Resolve deterministic authority threshold for a level."""

    for band in bands:
        if band.label == level:
            return band.threshold
    return 0.0


__all__ = ["DEFAULT_AUTHORITY_BANDS", "ScoreBand", "authority_threshold", "clamp_score"]
