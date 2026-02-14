# SPDX-License-Identifier: Apache-2.0

import pytest

from runtime.sandbox.executor import HardenedSandboxExecutor
from runtime.sandbox.fs_rules import enforce_write_path_allowlist
from runtime.sandbox.network_rules import enforce_network_egress_allowlist
from runtime.sandbox.resources import enforce_resource_quotas
from runtime.sandbox.syscall_filter import enforce_syscall_allowlist
from runtime.test_sandbox import TestSandboxResult, TestSandboxStatus


class _ObservedViolationSandbox:
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
            observed_syscalls=("open", "socket"),
            attempted_write_paths=("reports/safe.txt", "tmp/unsafe.txt"),
            attempted_network_hosts=("api.example",),
        )


def test_syscall_allowlist_enforced():
    ok, denied = enforce_syscall_allowlist(("open", "read", "socket"), ("open", "read"))
    assert not ok
    assert denied == ("socket",)


def test_write_path_allowlist_enforced():
    ok, violations = enforce_write_path_allowlist(("reports/file.txt", "tmp/bad.txt"), ("reports",))
    assert not ok
    assert violations == ("tmp/bad.txt",)


def test_network_allowlist_enforced():
    ok, violations = enforce_network_egress_allowlist(("localhost", "api.example"), ("localhost",))
    assert not ok
    assert violations == ("api.example",)


def test_resource_quota_enforced():
    verdict = enforce_resource_quotas(
        observed_cpu_s=2.0,
        observed_memory_mb=128.0,
        observed_disk_mb=0.5,
        observed_duration_s=3.0,
        cpu_limit_s=1,
        memory_limit_mb=512,
        disk_limit_mb=1,
        timeout_s=10,
    )
    assert not verdict["passed"]
    assert not verdict["cpu_ok"]


def test_executor_policy_enforcement_uses_observed_telemetry():
    executor = HardenedSandboxExecutor(_ObservedViolationSandbox())
    with pytest.raises(RuntimeError, match="sandbox_syscall_violation"):
        executor.run_tests_with_retry(mutation_id="m1", epoch_id="e1", replay_seed="0000000000000001")
