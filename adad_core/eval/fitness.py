"""Deterministic fitness computation and append-only logging."""
from __future__ import annotations

from pathlib import Path
from time import monotonic
from typing import Iterable

from adad_core.io.atomic import append_jsonl

DATA = Path("data")
LOGS = DATA / "logs"


def evaluate_agent(agent_id: str, exec_ok: bool, extra_scores: Iterable[float]) -> float:
    """Compute a bounded fitness score.

    The score is intentionally simple and deterministic to keep
    evaluation cheap on mobile devices.
    """
    base = 0.0
    if exec_ok:
        base = 0.6 + 0.1 * sum(1 for s in extra_scores if s > 0.0)
    return min(1.0, max(0.0, base))


def log_fitness(agent_id: str, fitness: float, runtime_s: float, archetype: str = "default") -> None:
    """Append a fitness record to ``data/logs/fitness.jsonl``."""
    append_jsonl(LOGS / "fitness.jsonl", {
        "agent_id": agent_id,
        "fitness": fitness,
        "runtime": runtime_s,
        "archetype": archetype,
    })


def record_metric(kind: str, payload: dict) -> None:
    """Write a generic metrics payload to ``metrics.jsonl``."""
    entry = {"kind": kind, **payload}
    append_jsonl(LOGS / "metrics.jsonl", entry)


def timed(name: str):
    """Context manager/decorator hybrid to time small blocks."""
    class _Timer:
        def __enter__(self):
            self.start = monotonic()
            return self

        def __exit__(self, exc_type, exc, tb):
            self.duration = monotonic() - self.start
            record_metric("timing", {"name": name, "duration": self.duration})
            return False

    return _Timer()
