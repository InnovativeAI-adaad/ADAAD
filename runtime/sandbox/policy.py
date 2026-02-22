# SPDX-License-Identifier: Apache-2.0
"""Sandbox policy profile with deterministic validation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Tuple

from runtime.governance.foundation import sha256_prefixed_digest


@dataclass(frozen=True)
class SandboxPolicy:
    profile_id: str
    syscall_allowlist: Tuple[str, ...]
    write_path_allowlist: Tuple[str, ...]
    network_egress_allowlist: Tuple[str, ...]
    dns_resolution_allowed: bool
    capability_drop: Tuple[str, ...]
    cpu_seconds: int
    memory_mb: int
    disk_mb: int
    timeout_s: int

    @property
    def policy_hash(self) -> str:
        return sha256_prefixed_digest(asdict(self))


def validate_policy(policy: SandboxPolicy) -> None:
    if not policy.profile_id:
        raise ValueError("invalid_policy_profile_id")
    if any(not item for item in policy.syscall_allowlist):
        raise ValueError("invalid_policy_syscall_allowlist")
    if policy.cpu_seconds <= 0 or policy.memory_mb <= 0 or policy.disk_mb <= 0 or policy.timeout_s <= 0:
        raise ValueError("invalid_policy_resource_bounds")


def policy_from_mapping(raw: Mapping[str, Any]) -> SandboxPolicy:
    return SandboxPolicy(
        profile_id=str(raw.get("profile_id") or ""),
        syscall_allowlist=tuple(sorted(str(x) for x in (raw.get("syscall_allowlist") or []))),
        write_path_allowlist=tuple(sorted(str(x) for x in (raw.get("write_path_allowlist") or []))),
        network_egress_allowlist=tuple(sorted(str(x) for x in (raw.get("network_egress_allowlist") or []))),
        dns_resolution_allowed=bool(raw.get("dns_resolution_allowed", False)),
        capability_drop=tuple(sorted(str(x) for x in (raw.get("capability_drop") or []))),
        cpu_seconds=int(raw.get("cpu_seconds", 1) or 1),
        memory_mb=int(raw.get("memory_mb", 1) or 1),
        disk_mb=int(raw.get("disk_mb", 1) or 1),
        timeout_s=int(raw.get("timeout_s", 1) or 1),
    )


def default_sandbox_policy() -> SandboxPolicy:
    return SandboxPolicy(
        profile_id="default-v1",
        syscall_allowlist=("close", "fstat", "mmap", "open", "read", "stat", "write"),
        write_path_allowlist=("reports", "runtime/lifecycle_states"),
        network_egress_allowlist=(),
        dns_resolution_allowed=False,
        capability_drop=("net_admin", "sys_admin"),
        cpu_seconds=60,
        memory_mb=1024,
        disk_mb=2048,
        timeout_s=60,
    )


__all__ = ["SandboxPolicy", "default_sandbox_policy", "policy_from_mapping", "validate_policy"]
