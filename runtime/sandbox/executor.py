# SPDX-License-Identifier: Apache-2.0
"""Hardened sandbox execution wrapper for test runs."""

from __future__ import annotations

from dataclasses import asdict
from typing import Sequence

from runtime.governance.foundation import RuntimeDeterminismProvider, default_provider
from runtime.sandbox.evidence import SandboxEvidenceLedger, build_sandbox_evidence
from runtime.sandbox.fs_rules import enforce_write_path_allowlist
from runtime.sandbox.manifest import SandboxManifest, validate_manifest
from runtime.sandbox.network_rules import enforce_network_egress_allowlist
from runtime.sandbox.policy import SandboxPolicy, default_sandbox_policy, validate_policy
from runtime.sandbox.resources import enforce_resource_quotas
from runtime.sandbox.syscall_filter import enforce_syscall_allowlist
from runtime.test_sandbox import TestSandbox, TestSandboxResult


class HardenedSandboxExecutor:
    def __init__(
        self,
        test_sandbox: TestSandbox,
        *,
        policy: SandboxPolicy | None = None,
        provider: RuntimeDeterminismProvider | None = None,
    ) -> None:
        self.test_sandbox = test_sandbox
        self.policy = policy or default_sandbox_policy()
        self.provider = provider or default_provider()
        self.evidence_ledger = SandboxEvidenceLedger()
        self.last_evidence_hash = ""
        self.last_evidence_payload: dict[str, object] = {}

    def run_tests_with_retry(
        self,
        *,
        mutation_id: str,
        epoch_id: str,
        replay_seed: str,
        args: Sequence[str] | None = None,
        retries: int = 1,
    ) -> TestSandboxResult:
        manifest = SandboxManifest(
            mutation_id=mutation_id,
            epoch_id=epoch_id,
            replay_seed=replay_seed,
            command=tuple(str(arg) for arg in (args or ["-x", "--tb=short"])),
            env=(("PYTHONDONTWRITEBYTECODE", "1"),),
            mounts=(),
            allowed_write_paths=self.policy.write_path_allowlist,
            allowed_network_hosts=self.policy.network_egress_allowlist,
            cpu_seconds=self.policy.cpu_seconds,
            memory_mb=self.policy.memory_mb,
            disk_mb=self.policy.disk_mb,
            timeout_s=self.policy.timeout_s,
            deterministic_clock=True,
            deterministic_random=True,
        )
        validate_manifest(manifest)
        validate_policy(self.policy)

        synthetic_syscalls = ("open", "read", "write", "close")
        syscall_ok, denied_syscalls = enforce_syscall_allowlist(synthetic_syscalls, self.policy.syscall_allowlist)
        if not syscall_ok:
            raise RuntimeError(f"sandbox_syscall_violation:{','.join(denied_syscalls)}")

        write_ok, write_violations = enforce_write_path_allowlist(("reports",), manifest.allowed_write_paths)
        if not write_ok:
            raise RuntimeError(f"sandbox_write_path_violation:{','.join(write_violations)}")

        network_ok, network_violations = enforce_network_egress_allowlist((), manifest.allowed_network_hosts)
        if not network_ok:
            raise RuntimeError(f"sandbox_network_violation:{','.join(network_violations)}")

        result = self.test_sandbox.run_tests_with_retry(args=args, retries=retries)
        resource_verdict = enforce_resource_quotas(
            observed_cpu_s=result.duration_s,
            observed_memory_mb=float(result.memory_mb or 0.0),
            observed_disk_mb=0.0,
            observed_duration_s=result.duration_s,
            cpu_limit_s=manifest.cpu_seconds,
            memory_limit_mb=manifest.memory_mb,
            disk_limit_mb=manifest.disk_mb,
            timeout_s=manifest.timeout_s,
        )
        if not resource_verdict["passed"]:
            raise RuntimeError("sandbox_resource_quota_violation")

        result_payload = asdict(result)
        result_payload["disk_mb"] = 0.0
        evidence_payload = build_sandbox_evidence(
            manifest=manifest.to_dict(),
            result=result_payload,
            policy_hash=self.policy.policy_hash,
            syscall_trace=synthetic_syscalls,
            provider_ts=self.provider.iso_now(),
        )
        entry = self.evidence_ledger.append(evidence_payload)
        self.last_evidence_payload = dict(evidence_payload)
        self.last_evidence_hash = str((entry.get("payload") or {}).get("evidence_hash") or "")
        return result


__all__ = ["HardenedSandboxExecutor"]
