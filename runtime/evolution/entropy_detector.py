# SPDX-License-Identifier: Apache-2.0
"""Entropy source detection for mutation requests."""

from __future__ import annotations

from app.agents.mutation_request import MutationRequest
from runtime.evolution.entropy_metadata import EntropyMetadata, estimate_entropy_bits, normalize_sources


def detect_entropy_metadata(
    request: MutationRequest,
    *,
    mutation_id: str,
    epoch_id: str,
    sandbox_nondeterministic: bool = False,
) -> EntropyMetadata:
    sources: list[str] = []
    if request.random_seed:
        sources.append("prng")
    if request.generation_ts:
        sources.append("clock")
    if request.capability_scopes:
        sources.append("environment")
    if sandbox_nondeterministic:
        sources.append("sandbox_nondeterminism")
    sources.append("mutation_ops")
    normalized = normalize_sources(sources)
    bits = estimate_entropy_bits(
        op_count=len(request.ops),
        target_count=len(request.targets),
        uses_random_seed=bool(request.random_seed),
    )
    if sandbox_nondeterministic:
        bits += 8
    deterministic = "network" not in normalized and "sandbox_nondeterminism" not in normalized
    return EntropyMetadata(
        mutation_id=mutation_id,
        epoch_id=epoch_id,
        sources=normalized,
        estimated_bits=bits,
        deterministic=deterministic,
    )


__all__ = ["detect_entropy_metadata"]
