# SPDX-License-Identifier: Apache-2.0
"""Replay helpers for deterministic sandbox evidence verification."""

from __future__ import annotations

from typing import Any, Dict

from runtime.governance.foundation import sha256_prefixed_digest


REPLAY_HASH_FIELDS = (
    "manifest_hash",
    "stdout_hash",
    "stderr_hash",
    "syscall_trace_hash",
    "resource_usage_hash",
)


def replay_sandbox_execution(manifest: Dict[str, Any], evidence: Dict[str, Any]) -> Dict[str, Any]:
    """Verify persisted sandbox evidence hash invariants.

    Canonical replay contract (all values are read from persisted evidence fields):
    - manifest_hash: sha256(manifest argument)
    - stdout_hash: sha256(evidence["stdout"])
    - stderr_hash: sha256(evidence["stderr"])
    - syscall_trace_hash: sha256(evidence["syscall_trace"])
    - resource_usage_hash: sha256(evidence["resource_usage"])

    Returns `passed=True` only when every expected hash equals the corresponding
    observed hash present in evidence.
    """
    expected_manifest_hash = sha256_prefixed_digest(manifest)
    expected_stdout_hash = sha256_prefixed_digest(str(evidence.get("stdout") or ""))
    expected_stderr_hash = sha256_prefixed_digest(str(evidence.get("stderr") or ""))
    expected_syscall_trace_hash = sha256_prefixed_digest(list(evidence.get("syscall_trace") or ()))
    expected_resource_usage_hash = sha256_prefixed_digest(dict(evidence.get("resource_usage") or {}))

    observed_manifest_hash = str(evidence.get("manifest_hash") or "")
    observed_stdout_hash = str(evidence.get("stdout_hash") or "")
    observed_stderr_hash = str(evidence.get("stderr_hash") or "")
    observed_syscall_trace_hash = str(evidence.get("syscall_trace_hash") or "")
    observed_resource_usage_hash = str(evidence.get("resource_usage_hash") or "")

    checks = {
        "manifest_hash": expected_manifest_hash == observed_manifest_hash,
        "stdout_hash": expected_stdout_hash == observed_stdout_hash,
        "stderr_hash": expected_stderr_hash == observed_stderr_hash,
        "syscall_trace_hash": expected_syscall_trace_hash == observed_syscall_trace_hash,
        "resource_usage_hash": expected_resource_usage_hash == observed_resource_usage_hash,
    }
    passed = all(checks.values())
    return {
        "passed": passed,
        "checks": checks,
        "expected_manifest_hash": expected_manifest_hash,
        "observed_manifest_hash": observed_manifest_hash,
        "expected_stdout_hash": expected_stdout_hash,
        "observed_stdout_hash": observed_stdout_hash,
        "expected_stderr_hash": expected_stderr_hash,
        "observed_stderr_hash": observed_stderr_hash,
        "expected_syscall_trace_hash": expected_syscall_trace_hash,
        "observed_syscall_trace_hash": observed_syscall_trace_hash,
        "expected_resource_usage_hash": expected_resource_usage_hash,
        "observed_resource_usage_hash": observed_resource_usage_hash,
    }


__all__ = ["REPLAY_HASH_FIELDS", "replay_sandbox_execution"]
