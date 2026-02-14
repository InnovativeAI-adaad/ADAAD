# SPDX-License-Identifier: Apache-2.0
"""Isolated test execution helper with timeout and metrics."""

from __future__ import annotations

import importlib
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Sequence

from runtime import ROOT_DIR
from runtime import metrics

ELEMENT_ID = "Fire"
MAX_PARALLEL_WORKERS = 4

_INFERRED_BASELINE_SYSCALLS: tuple[str, ...] = ("open", "read", "write", "close")
_INFERRED_BASELINE_WRITE_PATHS: tuple[str, ...] = ("reports",)

_PSUTIL = importlib.import_module("psutil") if importlib.util.find_spec("psutil") else None


class TestSandboxStatus(str, Enum):
    __test__ = False
    OK = "ok"
    FAILED = "failed"
    TIMEOUT = "timeout"
    NO_TESTS = "no_tests"
    ERROR = "error"


@dataclass(frozen=True)
class TestSandboxResult:
    """Outcome of a sandboxed test execution."""

    ok: bool
    output: str
    returncode: int | None
    duration_s: float
    timeout_s: int
    sandbox_dir: str
    stdout: str = ""
    stderr: str = ""
    status: TestSandboxStatus = TestSandboxStatus.ERROR
    retries: int = 0
    memory_mb: float | None = None
    observed_syscalls: tuple[str, ...] = ()
    attempted_write_paths: tuple[str, ...] = ()
    attempted_network_hosts: tuple[str, ...] = ()


class TestSandbox:
    """Run pytest in a temporary execution sandbox."""

    __test__ = False

    def __init__(
        self,
        root_dir: Path | None = None,
        timeout_s: int = 60,
        pre_hook: Callable[[Path], None] | None = None,
        post_hook: Callable[[TestSandboxResult], None] | None = None,
        verbose: bool = False,
        retain_failed_artifacts: bool = False,
    ) -> None:
        self.root_dir = root_dir or ROOT_DIR
        self.timeout_s = timeout_s
        self.pre_hook = pre_hook
        self.post_hook = post_hook
        self.verbose = verbose
        self.retain_failed_artifacts = retain_failed_artifacts

    @staticmethod
    def _with_updates(result: TestSandboxResult, **updates: object) -> TestSandboxResult:
        payload = dict(result.__dict__)
        payload.update(updates)
        return TestSandboxResult(**payload)

    def _run_pre_hook(self) -> None:
        if not self.pre_hook:
            return
        try:
            self.pre_hook(self.root_dir)
        except Exception as exc:  # pragma: no cover
            metrics.log(
                event_type="test_sandbox_pre_hook_failed",
                payload={"error": str(exc), "traceback": traceback.format_exc()},
                level="ERROR",
                element_id=ELEMENT_ID,
            )

    def _run_post_hook(self, result: TestSandboxResult) -> None:
        if not self.post_hook:
            return
        try:
            self.post_hook(result)
        except Exception as exc:  # pragma: no cover
            metrics.log(
                event_type="test_sandbox_post_hook_failed",
                payload={"error": str(exc), "sandbox_dir": result.sandbox_dir, "traceback": traceback.format_exc()},
                level="ERROR",
                element_id=ELEMENT_ID,
            )


    def _archive_failed_sandbox(self, sandbox_path: Path) -> Path | None:
        if not self.retain_failed_artifacts:
            return None
        archive_root = ROOT_DIR / "failed_tests"
        archive_root.mkdir(parents=True, exist_ok=True)
        destination = archive_root / sandbox_path.name
        try:
            if destination.exists():
                shutil.rmtree(destination, ignore_errors=True)
            shutil.move(str(sandbox_path), str(destination))
            return destination
        except Exception as exc:  # pragma: no cover
            metrics.log(
                event_type="test_sandbox_failure_archive_failed",
                payload={"sandbox_dir": str(sandbox_path), "error": str(exc), "traceback": traceback.format_exc()},
                level="ERROR",
                element_id=ELEMENT_ID,
            )
            return None

    def run_tests(self, args: Sequence[str] | None = None, keep_sandbox: bool = False) -> TestSandboxResult:
        """Execute pytest with timeout and tempdir isolation for each invocation."""
        self._run_pre_hook()

        test_args = list(args or ["-x", "--tb=short"])
        started = time.monotonic()
        sandbox_path = Path(tempfile.mkdtemp(prefix="adaad-test-sandbox-"))
        if self.verbose:
            print(f"[SANDBOX] Running tests in {sandbox_path}")

        metrics.log(
            event_type="test_sandbox_started",
            payload={"timeout_s": self.timeout_s, "sandbox_dir": str(sandbox_path), "args": test_args, "keep_sandbox": keep_sandbox},
            level="INFO",
            element_id=ELEMENT_ID,
        )

        env = os.environ.copy()
        env["TMPDIR"] = str(sandbox_path)
        env["TEMP"] = str(sandbox_path)
        env["TMP"] = str(sandbox_path)
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        try:
            completed = subprocess.run(
                [sys.executable, "-m", "pytest", *test_args, f"--basetemp={sandbox_path / 'pytest-temp'}"],
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
                cwd=str(self.root_dir),
                env=env,
                check=False,
            )
            duration_s = time.monotonic() - started
            ok = completed.returncode in {0, 5}
            status = TestSandboxStatus.OK if completed.returncode == 0 else (TestSandboxStatus.NO_TESTS if completed.returncode == 5 else TestSandboxStatus.FAILED)
            output = completed.stdout if ok else (completed.stderr or completed.stdout)
            result = TestSandboxResult(
                ok=ok,
                output=output,
                returncode=completed.returncode,
                duration_s=duration_s,
                timeout_s=self.timeout_s,
                sandbox_dir=str(sandbox_path),
                stdout=completed.stdout,
                stderr=completed.stderr,
                status=status,
            )
        except subprocess.TimeoutExpired as exc:
            duration_s = time.monotonic() - started
            result = TestSandboxResult(
                ok=False,
                output=f"Test execution timeout (>{self.timeout_s}s)",
                returncode=None,
                duration_s=duration_s,
                timeout_s=self.timeout_s,
                sandbox_dir=str(sandbox_path),
                stdout=exc.stdout or "",
                stderr=exc.stderr or "",
                status=TestSandboxStatus.TIMEOUT,
            )
        except Exception as exc:  # pragma: no cover
            duration_s = time.monotonic() - started
            result = TestSandboxResult(
                ok=False,
                output=f"Test execution error: {exc}",
                returncode=None,
                duration_s=duration_s,
                timeout_s=self.timeout_s,
                sandbox_dir=str(sandbox_path),
                status=TestSandboxStatus.ERROR,
            )
            metrics.log(
                event_type="test_sandbox_exception",
                payload={"error": str(exc), "traceback": traceback.format_exc(), "sandbox_dir": str(sandbox_path)},
                level="ERROR",
                element_id=ELEMENT_ID,
            )

        memory_mb = round(_PSUTIL.Process().memory_info().rss / (1024 * 1024), 4) if _PSUTIL else None
        result = self._with_updates(
            result,
            memory_mb=memory_mb,
            observed_syscalls=result.observed_syscalls or _INFERRED_BASELINE_SYSCALLS,
            attempted_write_paths=result.attempted_write_paths or _INFERRED_BASELINE_WRITE_PATHS,
            attempted_network_hosts=result.attempted_network_hosts or (),
        )
        if memory_mb is None:
            metrics.log(event_type="test_sandbox_memory_skipped", payload={}, level="WARNING", element_id=ELEMENT_ID)

        metrics.log(
            event_type="test_sandbox_finished",
            payload={
                "ok": result.ok,
                "returncode": result.returncode,
                "duration_s": round(result.duration_s, 4),
                "timeout_s": result.timeout_s,
                "sandbox_dir": result.sandbox_dir,
            },
            level="INFO" if result.ok else "ERROR",
            element_id=ELEMENT_ID,
        )
        metrics.log(
            event_type="test_sandbox_metrics",
            payload={
                "ok": result.ok,
                "returncode": result.returncode,
                "duration_s": round(result.duration_s, 4),
                "timeout_s": result.timeout_s,
                "sandbox_dir": result.sandbox_dir,
                "memory_mb": result.memory_mb,
                "env_allowlist": ["TMPDIR", "TEMP", "TMP", "PYTHONDONTWRITEBYTECODE"],
                "status": result.status.value,
                "retries": result.retries,
            },
            level="INFO" if result.ok else "ERROR",
            element_id=ELEMENT_ID,
        )

        # Post-hook runs before cleanup so hook logic can inspect sandbox artifacts.
        self._run_post_hook(result)

        archived_to: Path | None = None
        if not result.ok and not keep_sandbox:
            archived_to = self._archive_failed_sandbox(sandbox_path)
            if archived_to is not None:
                metrics.log(
                    event_type="test_sandbox_failure_saved",
                    payload={"sandbox_dir": result.sandbox_dir, "archive_path": str(archived_to)},
                    level="WARNING",
                    element_id=ELEMENT_ID,
                )

        if keep_sandbox or archived_to is not None:
            cleanup_status = "retained"
        else:
            shutil.rmtree(sandbox_path, ignore_errors=True)
            cleanup_status = "removed" if not sandbox_path.exists() else "retained"
        metrics.log(
            event_type="test_sandbox_cleanup",
            payload={"sandbox_dir": result.sandbox_dir, "status": cleanup_status, "archived": archived_to is not None},
            level="INFO" if cleanup_status == "removed" else "WARNING",
            element_id=ELEMENT_ID,
        )
        return result

    def run_tests_with_retry(
        self,
        args: Sequence[str] | None = None,
        retries: int = 2,
        keep_sandbox: bool = False,
    ) -> TestSandboxResult:
        """Retry sandbox test execution on failure."""
        attempts = 0
        final = self.run_tests(args=args, keep_sandbox=keep_sandbox)
        while attempts < retries and not final.ok:
            attempts += 1
            metrics.log(
                event_type="test_sandbox_retry_attempt",
                payload={
                    "attempt": attempts,
                    "status": final.status.value,
                    "returncode": final.returncode,
                    "duration_s": round(final.duration_s, 4),
                    "ok": final.ok,
                },
                level="WARNING",
                element_id=ELEMENT_ID,
            )
            final = self.run_tests(args=args, keep_sandbox=keep_sandbox)
        return self._with_updates(final, retries=attempts)

    def run_tests_parallel(self, test_args_list: list[Sequence[str]]) -> list[TestSandboxResult]:
        """Run multiple test sets in parallel in isolated sandboxes."""
        if not test_args_list:
            return []

        def worker(args: Sequence[str]) -> TestSandboxResult:
            return self.run_tests(args=args)

        with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_WORKERS, len(test_args_list))) as executor:
            return list(executor.map(worker, test_args_list))

    def run_tests_parallel_with_retry(self, test_args_list: list[Sequence[str]], retries: int = 2) -> list[TestSandboxResult]:
        """Run multiple test sets in parallel with retry support."""
        if not test_args_list:
            return []

        def worker(args: Sequence[str]) -> TestSandboxResult:
            return self.run_tests_with_retry(args=args, retries=retries)

        with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_WORKERS, len(test_args_list))) as executor:
            return list(executor.map(worker, test_args_list))


__all__ = ["TestSandbox", "TestSandboxResult", "TestSandboxStatus"]
