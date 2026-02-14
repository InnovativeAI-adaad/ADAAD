# SPDX-License-Identifier: Apache-2.0

import pytest

from runtime.governance.foundation.determinism import SeededDeterminismProvider
from runtime.sandbox.executor import HardenedSandboxExecutor
from runtime.test_sandbox import TestSandboxResult, TestSandboxStatus


class _FakeSandbox:
    def run_tests_with_retry(self, args=None, retries=1):
        return TestSandboxResult(
            ok=True,
            output="ok",
            returncode=0,
            duration_s=0.1,
            timeout_s=60,
            sandbox_dir="/tmp/x",
            stdout="ok",
            stderr="",
            status=TestSandboxStatus.OK,
            retries=retries,
            memory_mb=12.5,
            observed_syscalls=("open", "read"),
            attempted_write_paths=("reports",),
            attempted_network_hosts=(),
        )


class _ViolationSandbox:
    def __init__(self, *, syscalls=("open",), write_paths=(), hosts=()):
        self.syscalls = tuple(syscalls)
        self.write_paths = tuple(write_paths)
        self.hosts = tuple(hosts)

    def run_tests_with_retry(self, args=None, retries=1):
        return TestSandboxResult(
            ok=True,
            output="ok",
            returncode=0,
            duration_s=0.1,
            timeout_s=60,
            sandbox_dir="/tmp/x",
            stdout="ok",
            stderr="",
            status=TestSandboxStatus.OK,
            retries=retries,
            memory_mb=12.5,
            observed_syscalls=self.syscalls,
            attempted_write_paths=self.write_paths,
            attempted_network_hosts=self.hosts,
        )


def test_hardened_executor_records_evidence():
    executor = HardenedSandboxExecutor(_FakeSandbox(), provider=SeededDeterminismProvider("seed"))
    result = executor.run_tests_with_retry(mutation_id="m1", epoch_id="e1", replay_seed="0000000000000001")
    assert result.ok
    assert executor.last_evidence_hash.startswith("sha256:")
    assert executor.last_evidence_payload["resource_usage_hash"].startswith("sha256:")


def test_hardened_executor_rejects_observed_syscall_violation():
    executor = HardenedSandboxExecutor(_ViolationSandbox(syscalls=("socket",)), provider=SeededDeterminismProvider("seed"))
    with pytest.raises(RuntimeError, match="sandbox_syscall_violation"):
        executor.run_tests_with_retry(mutation_id="m1", epoch_id="e1", replay_seed="0000000000000001")


def test_hardened_executor_rejects_observed_write_path_violation():
    executor = HardenedSandboxExecutor(_ViolationSandbox(write_paths=("tmp/bad.txt",)), provider=SeededDeterminismProvider("seed"))
    with pytest.raises(RuntimeError, match="sandbox_write_path_violation"):
        executor.run_tests_with_retry(mutation_id="m1", epoch_id="e1", replay_seed="0000000000000001")


def test_hardened_executor_rejects_observed_network_violation():
    executor = HardenedSandboxExecutor(_ViolationSandbox(hosts=("api.example",)), provider=SeededDeterminismProvider("seed"))
    with pytest.raises(RuntimeError, match="sandbox_network_violation"):
        executor.run_tests_with_retry(mutation_id="m1", epoch_id="e1", replay_seed="0000000000000001")


def test_hardened_executor_rejects_missing_syscall_telemetry():
    executor = HardenedSandboxExecutor(_ViolationSandbox(syscalls=()), provider=SeededDeterminismProvider("seed"))
    with pytest.raises(RuntimeError, match="sandbox_missing_syscall_telemetry"):
        executor.run_tests_with_retry(mutation_id="m1", epoch_id="e1", replay_seed="0000000000000001")
