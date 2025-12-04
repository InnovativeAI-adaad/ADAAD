# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved
"""Sandboxed mutation execution helpers.

The goal of this module is to provide a predictable, resource-limited
execution surface for agent mutation tests. It uses a thread pool to
keep latency low while applying conservative CPU and memory limits so a
faulty mutation cannot starve the orchestrator.
"""
from __future__ import annotations

import concurrent.futures
import resource
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional


@dataclass
class MutationResult:
    success: bool
    details: Dict[str, Any]
    runtime_seconds: float


@contextmanager
def _apply_limits(cpu_seconds: int, memory_mb: int):
    """Apply soft rlimits for CPU time and address space and restore after use."""
    original_cpu = resource.getrlimit(resource.RLIMIT_CPU)
    original_as = resource.getrlimit(resource.RLIMIT_AS)
    try:
        target_cpu_soft = min(original_cpu[1], cpu_seconds)
        target_cpu_hard = min(original_cpu[1], cpu_seconds + 1 if original_cpu[1] != resource.RLIM_INFINITY else cpu_seconds + 1)
        byte_limit = memory_mb * 1024 * 1024
        target_as_soft = min(original_as[1], byte_limit)
        target_as_hard = min(original_as[1], byte_limit)
        resource.setrlimit(resource.RLIMIT_CPU, (target_cpu_soft, target_cpu_hard))
        resource.setrlimit(resource.RLIMIT_AS, (target_as_soft, target_as_hard))
        yield
    finally:
        resource.setrlimit(resource.RLIMIT_CPU, original_cpu)
        resource.setrlimit(resource.RLIMIT_AS, original_as)


class SandboxExecutor:
    def __init__(self, max_workers: int = 2, cpu_seconds: int = 1, memory_mb: int = 256) -> None:
        self.max_workers = max_workers
        self.cpu_seconds = cpu_seconds
        self.memory_mb = memory_mb
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="dream")
        self.success_history: list[float] = []

    def __enter__(self) -> "SandboxExecutor":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.pool.shutdown(wait=True)

    def _run_safely(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        with _apply_limits(self.cpu_seconds, self.memory_mb):
            return fn(*args, **kwargs)

    def execute(self, fn: Callable[..., Any], *args: Any, timeout: Optional[float] = 5.0, **kwargs: Any) -> MutationResult:
        start = time.time()
        future = self.pool.submit(self._run_safely, fn, *args, **kwargs)
        try:
            output = future.result(timeout=timeout)
            return MutationResult(success=True, details={"output": output}, runtime_seconds=time.time() - start)
        except Exception as exc:  # noqa: BLE001 - surfacing sandbox failures
            future.cancel()
            return MutationResult(
                success=False,
                details={"error": str(exc.__class__.__name__), "message": str(exc)},
                runtime_seconds=time.time() - start,
            )

    def mutate(self, mutate_fn: Callable[[str], str], src: str, timeout: Optional[float] = 5.0) -> MutationResult:
        return self.execute(mutate_fn, src, timeout=timeout)

    def mutate_file(self, path: str, transform: Callable[[str], str], timeout: float | None = 5.0) -> MutationResult:
        target = Path(path)
        source = target.read_text(encoding="utf-8", errors="ignore")

        def _apply(content: str) -> str:
            return transform(content)

        result = self.mutate(_apply, source, timeout=timeout)
        if result.success:
            target.write_text(result.details["output"], encoding="utf-8")
            self.success_history.append(1.0)
        else:
            self.success_history.append(0.0)
        return result

    def fitness_score(self) -> float:
        """Return a moving average fitness score based on recent successes."""
        if not self.success_history:
            return 0.0
        window = self.success_history[-20:]
        return sum(window) / len(window)

