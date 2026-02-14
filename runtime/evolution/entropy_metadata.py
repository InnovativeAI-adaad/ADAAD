# SPDX-License-Identifier: Apache-2.0
"""Deterministic entropy metadata primitives."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable


@dataclass(frozen=True)
class EntropyMetadata:
    mutation_id: str
    epoch_id: str
    sources: tuple[str, ...]
    estimated_bits: int
    deterministic: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def estimate_entropy_bits(*, op_count: int, target_count: int, uses_random_seed: bool) -> int:
    base = (max(0, int(op_count)) * 2) + max(0, int(target_count))
    if uses_random_seed:
        base += 16
    return base


def normalize_sources(sources: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({str(item).strip().lower() for item in sources if str(item).strip()}))


__all__ = ["EntropyMetadata", "estimate_entropy_bits", "normalize_sources"]
