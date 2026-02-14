# SPDX-License-Identifier: Apache-2.0

from runtime.sandbox.fs_rules import enforce_write_path_allowlist
from runtime.sandbox.network_rules import enforce_network_egress_allowlist
from runtime.sandbox.resources import enforce_resource_quotas
from runtime.sandbox.syscall_filter import enforce_syscall_allowlist


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
