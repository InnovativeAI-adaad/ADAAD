# SPDX-License-Identifier: Apache-2.0
"""Strict sandbox execution envelope with typed result schema."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class SandboxLimits:
    timeout_ms: int = 1_000
    memory_kb_limit: int = 262_144


@dataclass(frozen=True)
class SandboxResult:
    variant_id: str
    execution_time_ms: int
    memory_kb: int
    status: str
    invariant_results: dict[str, bool]
    fitness_score: float
    revenue_score: float

    def as_dict(self) -> dict[str, object]:
        return {
            "variant_id": self.variant_id,
            "execution_time_ms": self.execution_time_ms,
            "memory_kb": self.memory_kb,
            "status": self.status,
            "invariant_results": dict(self.invariant_results),
            "fitness_score": self.fitness_score,
            "revenue_score": self.revenue_score,
        }


class SandboxExecutor:
    """Executes a callable under lightweight deterministic policy checks."""

    def __init__(self, limits: SandboxLimits | None = None) -> None:
        self.limits = limits or SandboxLimits()

    def execute(
        self,
        runner: Callable[[], dict[str, object]],
        *,
        variant_id: str | None = None,
    ) -> SandboxResult:
        rid = variant_id or str(uuid.uuid4())
        start = time.perf_counter()
        status = "pass"
        payload: dict[str, object] = {}
        try:
            payload = runner()
        except TimeoutError:
            status = "timeout"
        except Exception:
            status = "fail"
        elapsed_ms = int((time.perf_counter() - start) * 1000)

        reported_memory = int(payload.get("memory_kb", 0)) if payload else 0
        invariant_results = payload.get("invariant_results", {}) if payload else {}
        if not isinstance(invariant_results, dict):
            invariant_results = {}
        invariant_results = {
            "signature_preserved": bool(invariant_results.get("signature_preserved", False)),
            "behavior_preserved": bool(invariant_results.get("behavior_preserved", False)),
        }

        if elapsed_ms > self.limits.timeout_ms:
            status = "timeout"
        if reported_memory > self.limits.memory_kb_limit:
            status = "fail"
        if not all(invariant_results.values()):
            status = "fail"

        return SandboxResult(
            variant_id=rid,
            execution_time_ms=elapsed_ms,
            memory_kb=reported_memory,
            status=status,
            invariant_results=invariant_results,
            fitness_score=float(payload.get("fitness_score", 0.0)) if payload else 0.0,
            revenue_score=float(payload.get("revenue_score", 0.0)) if payload else 0.0,
        )
