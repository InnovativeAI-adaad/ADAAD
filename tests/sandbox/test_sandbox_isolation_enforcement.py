# SPDX-License-Identifier: Apache-2.0

import pytest

from runtime.governance.foundation.determinism import SeededDeterminismProvider
from runtime.sandbox.executor import HardenedSandboxExecutor
from runtime.sandbox.isolation import ProcessIsolationBackend
from runtime.sandbox.manifest import SandboxManifest
from runtime.sandbox.policy import default_sandbox_policy
from runtime.sandbox.preflight import analyze_execution_plan
from runtime.test_sandbox import TestSandboxResult, TestSandboxStatus


class _TrackingSandbox:
    def __init__(self) -> None:
        self.calls = 0

    def run_tests_with_retry(self, args=None, retries=1):
        self.calls += 1
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
            memory_mb=16.0,
            observed_syscalls=("open", "read"),
            attempted_write_paths=("reports/safe.txt",),
            attempted_network_hosts=(),
        )


def test_backend_failure_blocks_mutation_execution_before_tests_run():
    sandbox = _TrackingSandbox()
    backend = ProcessIsolationBackend(seccomp_profile_id="")
    executor = HardenedSandboxExecutor(
        sandbox,
        provider=SeededDeterminismProvider("seed"),
        isolation_backend=backend,
    )

    with pytest.raises(RuntimeError, match="sandbox_policy_unenforceable:syscall_allowlist"):
        executor.run_tests_with_retry(mutation_id="m1", epoch_id="e1", replay_seed="0000000000000001")

    assert sandbox.calls == 0


def test_preflight_blocks_disallowed_command_before_tests_run():
    sandbox = _TrackingSandbox()
    executor = HardenedSandboxExecutor(sandbox, provider=SeededDeterminismProvider("seed"))

    with pytest.raises(RuntimeError, match="sandbox_preflight_violation"):
        executor.run_tests_with_retry(
            mutation_id="m1",
            epoch_id="e1",
            replay_seed="0000000000000001",
            args=("-x", "--tb=short", "&&"),
        )

    assert sandbox.calls == 0


def test_preflight_rejects_disallowed_mount_targets():
    policy = default_sandbox_policy()
    manifest = SandboxManifest(
        mutation_id="m1",
        epoch_id="e1",
        replay_seed="0000000000000001",
        command=("-x",),
        env=(("PYTHONDONTWRITEBYTECODE", "1"),),
        mounts=("tmp",),
        allowed_write_paths=policy.write_path_allowlist,
        allowed_network_hosts=policy.network_egress_allowlist,
        cpu_seconds=policy.cpu_seconds,
        memory_mb=policy.memory_mb,
        disk_mb=policy.disk_mb,
        timeout_s=policy.timeout_s,
        deterministic_clock=True,
        deterministic_random=True,
    )

    preflight = analyze_execution_plan(manifest=manifest, policy=policy)
    assert preflight["ok"] is False
    assert preflight["reason"].startswith("disallowed_mount_target")
