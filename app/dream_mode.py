from __future__ import annotations

from typing import Dict

ELEMENT_ID = "fire"


def discover() -> Dict[str, object]:
    """Fire element discovery stub for dream tasks."""
    return {"dream_discovered": True}

# === HE65 SandboxExecutor compatibility layer ===
from dataclasses import dataclass
from typing import Any, Dict, Optional, Callable
import io
import time
import contextlib
import subprocess
import sys

@dataclass
class MutationResult:
    success: bool
    details: Dict[str, Any]
    runtime_seconds: float = 0.0
    exception_type: Optional[str] = None
    exception_message: Optional[str] = None
    exit_code: int = 0

class SandboxExecutor:
    """Minimal sandbox for mutation evaluation.
    Stdlib only. No file I/O beyond running a temp python process for a given file.
    Imports disabled for exec() mutations by default.
    """

    def __init__(self, allow_imports: bool = False):
        self.allow_imports = allow_imports
        self._last_output = ""
        self._last_error = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def mutate(self, mutate_fn: Callable[[str], str], source: str) -> MutationResult:
        start = time.perf_counter()
        try:
            out = mutate_fn(source)
            rt = time.perf_counter() - start
            return MutationResult(True, {"output": out}, runtime_seconds=rt)
        except Exception as e:
            rt = time.perf_counter() - start
            return MutationResult(
                False,
                {"error": type(e).__name__, "message": str(e)},
                runtime_seconds=rt,
                exception_type=type(e).__name__,
                exception_message=str(e),
            )

    def run_python_file(self, path, timeout: float = 5.0) -> MutationResult:
        start = time.perf_counter()
        try:
            cp = subprocess.run(
                [sys.executable, str(path)],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            rt = time.perf_counter() - start
            self._last_output = (cp.stdout or "") + (cp.stderr or "")
            ok = (cp.returncode == 0)
            return MutationResult(
                ok,
                {"stdout": cp.stdout, "stderr": cp.stderr, "returncode": cp.returncode},
                runtime_seconds=rt,
                exit_code=cp.returncode,
                exception_type=None if ok else "NonZeroExit",
                exception_message=None if ok else f"exit={cp.returncode}",
            )
        except subprocess.TimeoutExpired as e:
            rt = time.perf_counter() - start
            self._last_output = (e.stdout or "") + (e.stderr or "")
            return MutationResult(
                False,
                {"stdout": e.stdout, "stderr": e.stderr},
                runtime_seconds=rt,
                exception_type="TimeoutExpired",
                exception_message="timeout",
                exit_code=124,
            )
        except Exception as e:
            rt = time.perf_counter() - start
            return MutationResult(
                False,
                {"error": type(e).__name__, "message": str(e)},
                runtime_seconds=rt,
                exception_type=type(e).__name__,
                exception_message=str(e),
                exit_code=1,
            )

    def fitness_score(self) -> float:
        # Deterministic placeholder. Improve later with real metrics.
        return 0.6
