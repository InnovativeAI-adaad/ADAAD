# SPDX-License-Identifier: Apache-2.0

import pytest

from runtime.sandbox.executor import HardenedSandboxExecutor
from runtime.sandbox.fs_rules import enforce_write_path_allowlist
from runtime.sandbox.network_rules import enforce_network_egress_allowlist
from runtime.sandbox.policy import SandboxPolicy
from runtime.sandbox.resources import enforce_resource_quotas
from runtime.sandbox.syscall_filter import enforce_syscall_allowlist, syscall_trace_fingerprint
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


class _ObservedNetworkViolationSandbox:
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
            attempted_write_paths=("reports/safe.txt",),
            attempted_network_hosts=("api.example",),
        )


def test_syscall_allowlist_enforced():
    ok, denied = enforce_syscall_allowlist(("open", "read", "socket"), ("open", "read"))
    assert not ok
    assert denied == ("socket",)


def test_syscall_fingerprint_is_deterministic_for_equivalent_traces():
    fp1 = syscall_trace_fingerprint(("open", "read", "open", "write"))
    fp2 = syscall_trace_fingerprint(("write", "open", "read"))
    assert fp1 == fp2


def test_write_path_allowlist_enforced():
    ok, violations = enforce_write_path_allowlist(("reports/file.txt", "tmp/bad.txt"), ("reports",))
    assert not ok
    assert violations == ("tmp/bad.txt",)


def test_network_allowlist_enforced():
    ok, violations = enforce_network_egress_allowlist(("localhost", "10.0.0.2"), ("localhost",))
    assert not ok
    assert violations == ("10.0.0.2",)


def test_dns_is_blocked_by_default_even_when_domain_is_allowlisted():
    ok, violations = enforce_network_egress_allowlist(("api.example",), ("api.example",))
    assert not ok
    assert violations == ("dns",)


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


def test_executor_records_structured_fail_closed_violation_event():
    policy = SandboxPolicy(
        profile_id="default-v1",
        syscall_allowlist=("open", "read"),
        write_path_allowlist=("reports",),
        network_egress_allowlist=("api.example",),
        dns_resolution_allowed=False,
        capability_drop=("net_admin", "sys_admin"),
        cpu_seconds=60,
        memory_mb=1024,
        disk_mb=2048,
        timeout_s=60,
    )
    executor = HardenedSandboxExecutor(_ObservedNetworkViolationSandbox(), policy=policy)
    with pytest.raises(RuntimeError, match="sandbox_network_violation"):
        executor.run_tests_with_retry(mutation_id="m2", epoch_id="e1", replay_seed="0000000000000002")
    event = executor.last_evidence_payload["events"][0]
    assert event["event"] == "sandbox_integrity_violation"
    assert event["violation_type"] == "network_egress_allowlist"
    assert event["fail_closed"] is True
