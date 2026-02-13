# SPDX-License-Identifier: Apache-2.0
"""Deterministic entropy discipline for replay-safe identifiers and tokens."""

from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass

_DETERMINISTIC_NAMESPACE = uuid.UUID("f9fc4f79-7306-4d18-9f98-604948e76a2b")


@dataclass(frozen=True)
class EntropyBudget:
    """Tracks non-deterministic operations per cycle."""

    llm_calls: int = 0
    file_reads: int = 0
    web_fetches: int = 0
    random_samples: int = 0

    def exhausted(self) -> bool:
        return self.llm_calls > 10 or self.file_reads > 50 or self.web_fetches > 5 or self.random_samples > 100

    def consume(self, operation: str) -> "EntropyBudget":
        if operation == "llm":
            return EntropyBudget(self.llm_calls + 1, self.file_reads, self.web_fetches, self.random_samples)
        if operation == "file":
            return EntropyBudget(self.llm_calls, self.file_reads + 1, self.web_fetches, self.random_samples)
        if operation == "web":
            return EntropyBudget(self.llm_calls, self.file_reads, self.web_fetches + 1, self.random_samples)
        if operation == "random":
            return EntropyBudget(self.llm_calls, self.file_reads, self.web_fetches, self.random_samples + 1)
        return self


def derive_seed(epoch_id: str, bundle_id: str | None = None, agent_id: str | None = None) -> str:
    """Derive a canonical seed from stable replay inputs."""
    material = {
        "epoch_id": str(epoch_id or ""),
        "bundle_id": str(bundle_id or ""),
        "agent_id": str(agent_id or ""),
    }
    canonical = "|".join([material["epoch_id"], material["bundle_id"], material["agent_id"]])
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def deterministic_id(
    *,
    epoch_id: str,
    bundle_id: str | None = None,
    agent_id: str | None = None,
    label: str = "id",
) -> str:
    """Generate a deterministic UUID string for strict replay contexts."""
    seed = derive_seed(epoch_id=epoch_id, bundle_id=bundle_id, agent_id=agent_id)
    return str(uuid.uuid5(_DETERMINISTIC_NAMESPACE, f"{label}:{seed}"))


def deterministic_token(
    *,
    epoch_id: str,
    bundle_id: str | None = None,
    agent_id: str | None = None,
    label: str = "token",
    length: int = 16,
) -> str:
    """Generate a deterministic short token for content generation."""
    seed = derive_seed(epoch_id=epoch_id, bundle_id=bundle_id, agent_id=agent_id)
    digest = hashlib.sha256(f"{label}:{seed}".encode("utf-8")).hexdigest()
    return digest[:length]


def deterministic_token_with_budget(seed: str, context: str, *, budget: EntropyBudget) -> tuple[int, EntropyBudget]:
    """Generate reproducible integer token while tracking entropy budget."""
    if budget.exhausted():
        raise RuntimeError("entropy_budget_exhausted")
    digest = hashlib.sha256(f"{seed}::{context}".encode("utf-8")).hexdigest()
    return int(digest[:16], 16), budget.consume("random")


def _env_enabled(name: str) -> bool:
    value = os.getenv(name, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def deterministic_context(*, replay_mode: str = "off", recovery_tier: str | None = None) -> bool:
    """Return True when deterministic IDs/tokens must be used."""
    normalized_mode = (replay_mode or "off").strip().lower()
    normalized_tier = (recovery_tier or "").strip().lower()

    if normalized_mode in {"strict", "audit"}:
        return True
    if normalized_tier == "audit":
        return True

    return not _env_enabled("ADAAD_ALLOW_NONDETERMINISTIC_IDS")


__all__ = [
    "derive_seed",
    "EntropyBudget",
    "deterministic_id",
    "deterministic_token",
    "deterministic_token_with_budget",
    "deterministic_context",
]
