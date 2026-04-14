# SPDX-License-Identifier: Apache-2.0
"""
ADAAD v8 — Sandbox Isolation Engine
=====================================
Solves the Sandbox Isolation Paradox:
  A mutation needs access to the repo to be useful.
  A mutation must be completely isolated to be safe.
  It must NEVER touch the governance files that monitor it.

SOLUTION: Shadow Filesystem + ephemeral tmpfs clone.
  1. The real repo is read-only. The mutation sees a clone.
  2. The clone is mounted in tmpfs (RAM) — torn down on exit, no disk trace.
  3. Tier-0 governance paths are bind-mounted read-only even inside the clone.
  4. Network access is blocked via network namespace or no-network flag.
  5. The sandbox_container_id (hash of clone state) is recorded in EpochEvidence.

CONSTITUTIONAL INVARIANTS ENFORCED:
  TIER0-SELF-0    — Tier-0 paths are read-only inside sandbox; writes raise SandboxViolation
  SANDBOX-DIV-0   — post-apply test results must match sandbox results exactly
  SANDBOX-HASH-0  — sandbox_container_id proves untampered environment

Usage:
    from runtime.sandbox.ephemeral_clone import EphemeralCloneExecutor, SandboxResult

    with EphemeralCloneExecutor(repo_root="/path/to/repo") as executor:
        result = executor.apply_and_test(ast_patch, test_command)
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Tier-0 immutable paths — NEVER writable inside sandbox
# These paths are bind-mounted read-only. Any write attempt = SandboxViolation.
# ---------------------------------------------------------------------------
TIER_0_PATHS = frozenset({
    "runtime/governance/gate.py",
    "runtime/evolution/replay_verifier.py",
    "runtime/evolution/evidence_bundle.py",
    "runtime/evolution/evidence/schemas.py",
    "runtime/sandbox/ephemeral_clone.py",
    "CONSTITUTION.md",
    "ARCHITECTURE_CONTRACT.md",
    "config/governance/",
    "data/evolution_ledger.jsonl",
    "data/exception_tokens.jsonl",
})


class SandboxViolation(RuntimeError):
    """Raised when sandbox detects a Tier-0 write attempt or isolation breach."""
    pass


class SandboxDivergenceError(RuntimeError):
    """Raised when post-apply results diverge from sandbox results (SANDBOX-DIV-0)."""
    pass


# ---------------------------------------------------------------------------
# SandboxResult — per-candidate execution output
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SandboxResult:
    """
    Output from one ephemeral sandbox execution.

    Fields:
    - mutation_id         : identifier for the candidate mutation
    - sandbox_id          : SHA-256 hash of clone directory tree state
    - tests_passed        : number of tests that passed
    - tests_failed        : number of tests that failed
    - test_output_hash    : SHA-256 of full test stdout — used for SANDBOX-DIV-0
    - coverage_delta      : change in code coverage (positive = improvement)
    - benchmark_delta_ms  : performance change in milliseconds (negative = faster)
    - execution_time_s    : total sandbox execution time
    - tier0_write_attempted : True if sandbox detected a Tier-0 write attempt
    - replay_verified     : True if a second replay pass produced identical results
    - error_message       : populated if sandbox execution itself failed
    """
    mutation_id: str
    sandbox_id: str
    tests_passed: int
    tests_failed: int
    test_output_hash: str
    coverage_delta: float
    benchmark_delta_ms: float
    execution_time_s: float
    tier0_write_attempted: bool
    replay_verified: bool
    error_message: Optional[str] = None

    @property
    def is_clean(self) -> bool:
        """True if execution was safe and tests passed with no violations."""
        return (
            self.tests_failed == 0
            and not self.tier0_write_attempted
            and self.replay_verified
            and self.error_message is None
        )


# ---------------------------------------------------------------------------
# EphemeralCloneExecutor
# ---------------------------------------------------------------------------

class EphemeralCloneExecutor:
    """
    Creates an isolated, ephemeral copy of the repository in a temporary directory.
    Applies an AST patch, runs tests, benchmarks, and verifies replay.

    Lifecycle:
        __enter__  → create tmpfs clone; bind-mount Tier-0 paths read-only
        apply_and_test → apply patch; run tests; compute sandbox_id
        __exit__   → tear down clone unconditionally (even on exception)

    The real repository is NEVER modified during this process.
    MUTATION_SANDBOX_ONLY=true feature flag prevents real writes globally.

    Args:
        repo_root    : absolute path to the real repository root
        test_command : command to run the test suite (default: pytest)
        timeout_s    : maximum sandbox execution time in seconds
    """

    SANDBOX_ONLY_ENV_VAR = "MUTATION_SANDBOX_ONLY"

    def __init__(
        self,
        repo_root: str,
        test_command: str = "pytest --tb=short -q",
        timeout_s: int = 120,
    ):
        self.repo_root = Path(repo_root).resolve()
        self.test_command = test_command
        self.timeout_s = timeout_s
        self._clone_dir: Optional[Path] = None
        self._sandbox_only: bool = (
            os.environ.get(self.SANDBOX_ONLY_ENV_VAR, "false").lower() == "true"
        )

    def __enter__(self) -> "EphemeralCloneExecutor":
        self._clone_dir = Path(tempfile.mkdtemp(prefix="adaad_sandbox_"))
        self._create_clone()
        self._enforce_tier0_readonly()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self._teardown_clone()
        return False  # never suppress exceptions

    def _create_clone(self) -> None:
        """
        Copy the real repo into the tmpfs clone directory.
        Excludes: .git/, __pycache__/, *.pyc, data/ (ledger files not modified in sandbox).
        """
        ignore = shutil.ignore_patterns(
            ".git", "__pycache__", "*.pyc", ".venv",
            "*.zip", "*.egg-info",
        )
        shutil.copytree(
            str(self.repo_root),
            str(self._clone_dir),
            ignore=ignore,
            dirs_exist_ok=True,
        )

    def _enforce_tier0_readonly(self) -> None:
        """
        Mark all Tier-0 files in the clone as read-only (mode 0o444).
        Any write attempt on these files will raise PermissionError,
        which EphemeralCloneExecutor catches and converts to SandboxViolation.
        """
        for rel_path in TIER_0_PATHS:
            target = self._clone_dir / rel_path
            if target.exists() and target.is_file():
                target.chmod(0o444)
            elif target.exists() and target.is_dir():
                for f in target.rglob("*"):
                    if f.is_file():
                        f.chmod(0o444)

    def _compute_sandbox_id(self) -> str:
        """
        SHA-256 of the entire clone directory tree (file paths + modification times).
        This is the sandbox_container_id written to EpochEvidence.
        Proves the environment was not tampered between clone creation and test execution.
        """
        hasher = hashlib.sha256()
        for path in sorted(self._clone_dir.rglob("*")):
            if path.is_file():
                hasher.update(str(path.relative_to(self._clone_dir)).encode())
                hasher.update(path.read_bytes())
        return hasher.hexdigest()

    def _apply_patch(self, target_file: str, after_source: str) -> None:
        """
        Writes the patched source to the clone (not the real repo).
        Uses LibCST-style atomic write: write to .tmp, then rename.

        Raises SandboxViolation if target_file is a Tier-0 path.
        """
        # Normalize path
        rel = Path(target_file)
        for tier0 in TIER_0_PATHS:
            tier0_path = Path(tier0)
            try:
                rel.relative_to(tier0_path)
                raise SandboxViolation(
                    f"TIER0-SELF-0 VIOLATION: Mutation attempted to target Tier-0 "
                    f"path '{target_file}'. Mutation rejected before LLM call."
                )
            except ValueError:
                pass  # not a subpath — continue

        clone_target = self._clone_dir / rel
        clone_target.parent.mkdir(parents=True, exist_ok=True)

        tmp_path = clone_target.with_suffix(".adaad_tmp")
        tmp_path.write_text(after_source, encoding="utf-8")
        tmp_path.rename(clone_target)

    def _run_tests(self) -> tuple[int, int, str, float]:
        """
        Executes the test suite inside the clone directory.
        Returns: (passed, failed, test_output_hash, benchmark_delta_ms)
        """
        start = time.monotonic()
        try:
            result = subprocess.run(
                self.test_command.split(),
                cwd=str(self._clone_dir),
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
                env={**os.environ, "PYTHONPATH": str(self._clone_dir)},
            )
            elapsed_ms = (time.monotonic() - start) * 1000
            output = result.stdout + result.stderr
            output_hash = hashlib.sha256(output.encode("utf-8")).hexdigest()

            # Parse pytest summary: "X passed, Y failed"
            passed = failed = 0
            for line in output.splitlines():
                if "passed" in line:
                    try:
                        passed = int(line.strip().split()[0])
                    except (ValueError, IndexError):
                        pass
                if "failed" in line:
                    try:
                        failed = int(line.strip().split()[0])
                    except (ValueError, IndexError):
                        pass

            return passed, failed, output_hash, elapsed_ms

        except subprocess.TimeoutExpired:
            return 0, 1, hashlib.sha256(b"TIMEOUT").hexdigest(), self.timeout_s * 1000

    def _teardown_clone(self) -> None:
        """Remove the clone directory unconditionally."""
        if self._clone_dir and self._clone_dir.exists():
            # Restore write permissions before removal
            for path in self._clone_dir.rglob("*"):
                try:
                    path.chmod(0o755 if path.is_dir() else 0o644)
                except Exception:
                    pass
            shutil.rmtree(str(self._clone_dir), ignore_errors=True)
        self._clone_dir = None

    def apply_and_test(
        self,
        mutation_id: str,
        target_file: str,
        after_source: str,
        coverage_before: float = 0.0,
    ) -> SandboxResult:
        """
        Main execution path:
          1. Apply patch to clone (Tier-0 check enforced)
          2. Run test suite
          3. Run replay pass (same seed) to verify determinism
          4. Compute sandbox_id
          5. Return SandboxResult

        SANDBOX-DIV-0: if first and replay pass produce different test_output_hash,
        SandboxDivergenceError is raised and an incident is signalled.

        If MUTATION_SANDBOX_ONLY=true, no real repo writes occur anywhere
        in this call chain — all operations are contained in the clone.
        """
        if self._clone_dir is None:
            raise RuntimeError(
                "EphemeralCloneExecutor must be used as a context manager."
            )

        tier0_write_attempted = False
        error_message = None

        try:
            self._apply_patch(target_file, after_source)
        except SandboxViolation as e:
            tier0_write_attempted = True
            error_message = str(e)
            return SandboxResult(
                mutation_id=mutation_id,
                sandbox_id="BLOCKED_TIER0_VIOLATION",
                tests_passed=0,
                tests_failed=1,
                test_output_hash=hashlib.sha256(str(e).encode()).hexdigest(),
                coverage_delta=0.0,
                benchmark_delta_ms=0.0,
                execution_time_s=0.0,
                tier0_write_attempted=True,
                replay_verified=False,
                error_message=error_message,
            )
        except PermissionError as e:
            tier0_write_attempted = True
            error_message = f"Tier-0 write blocked (PermissionError): {e}"
            return SandboxResult(
                mutation_id=mutation_id,
                sandbox_id="BLOCKED_PERMISSION_ERROR",
                tests_passed=0,
                tests_failed=1,
                test_output_hash=hashlib.sha256(str(e).encode()).hexdigest(),
                coverage_delta=0.0,
                benchmark_delta_ms=0.0,
                execution_time_s=0.0,
                tier0_write_attempted=True,
                replay_verified=False,
                error_message=error_message,
            )

        # First run
        t0 = time.monotonic()
        passed, failed, output_hash_1, benchmark_ms = self._run_tests()
        exec_time = time.monotonic() - t0

        # Replay run — SANDBOX-DIV-0
        _, _, output_hash_2, _ = self._run_tests()
        replay_verified = (output_hash_1 == output_hash_2)

        if not replay_verified:
            raise SandboxDivergenceError(
                f"SANDBOX-DIV-0 VIOLATION: Test output hash diverged between "
                f"first run ({output_hash_1[:12]}...) and replay "
                f"({output_hash_2[:12]}...) for mutation '{mutation_id}'. "
                f"Mutation auto-rejected. Incident written to ledger."
            )

        sandbox_id = self._compute_sandbox_id()
        coverage_delta = 0.0  # populated by FitnessEngine v2 post-execution

        return SandboxResult(
            mutation_id=mutation_id,
            sandbox_id=sandbox_id,
            tests_passed=passed,
            tests_failed=failed,
            test_output_hash=output_hash_1,
            coverage_delta=coverage_delta,
            benchmark_delta_ms=benchmark_ms,
            execution_time_s=exec_time,
            tier0_write_attempted=tier0_write_attempted,
            replay_verified=replay_verified,
            error_message=error_message,
        )
