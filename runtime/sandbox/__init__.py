# SPDX-License-Identifier: Apache-2.0
"""Hardened sandbox isolation primitives."""

from runtime.sandbox.evidence import SandboxEvidenceLedger, build_sandbox_evidence
from runtime.sandbox.executor import HardenedSandboxExecutor
from runtime.sandbox.fs_rules import enforce_write_path_allowlist
from runtime.sandbox.isolation import ContainerIsolationBackend, ProcessIsolationBackend
from runtime.sandbox.manifest import SandboxManifest, manifest_from_mapping, validate_manifest
from runtime.sandbox.network_rules import enforce_network_egress_allowlist
from runtime.sandbox.preflight import analyze_execution_plan
from runtime.sandbox.policy import SandboxPolicy, default_sandbox_policy, policy_from_mapping, validate_policy
from runtime.sandbox.replay import replay_sandbox_execution
from runtime.sandbox.resources import enforce_resource_quotas
from runtime.sandbox.syscall_filter import enforce_syscall_allowlist

__all__ = [
    "HardenedSandboxExecutor",
    "SandboxEvidenceLedger",
    "SandboxManifest",
    "SandboxPolicy",
    "build_sandbox_evidence",
    "default_sandbox_policy",
    "enforce_syscall_allowlist",
    "enforce_write_path_allowlist",
    "enforce_network_egress_allowlist",
    "enforce_resource_quotas",
    "ProcessIsolationBackend",
    "ContainerIsolationBackend",
    "analyze_execution_plan",
    "manifest_from_mapping",
    "validate_manifest",
    "policy_from_mapping",
    "validate_policy",
    "replay_sandbox_execution",
]
