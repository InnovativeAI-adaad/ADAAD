# SPDX-License-Identifier: Apache-2.0

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
        )


def test_hardened_executor_records_evidence():
    executor = HardenedSandboxExecutor(_FakeSandbox(), provider=SeededDeterminismProvider("seed"))
    result = executor.run_tests_with_retry(mutation_id="m1", epoch_id="e1", replay_seed="0000000000000001")
    assert result.ok
    assert executor.last_evidence_hash.startswith("sha256:")
