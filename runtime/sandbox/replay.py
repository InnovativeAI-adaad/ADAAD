# SPDX-License-Identifier: Apache-2.0
"""Replay helpers for deterministic sandbox evidence verification."""

from __future__ import annotations

from typing import Any, Dict

from runtime.governance.foundation import sha256_prefixed_digest


def replay_sandbox_execution(manifest: Dict[str, Any], evidence: Dict[str, Any]) -> Dict[str, Any]:
    expected_manifest_hash = sha256_prefixed_digest(manifest)
    expected_stdout_hash = sha256_prefixed_digest(str((evidence.get("result") or {}).get("stdout", "")))
    observed_manifest_hash = str(evidence.get("manifest_hash") or "")
    observed_stdout_hash = str(evidence.get("stdout_hash") or "")
    passed = expected_manifest_hash == observed_manifest_hash and expected_stdout_hash == observed_stdout_hash
    return {
        "passed": passed,
        "expected_manifest_hash": expected_manifest_hash,
        "observed_manifest_hash": observed_manifest_hash,
        "expected_stdout_hash": expected_stdout_hash,
        "observed_stdout_hash": observed_stdout_hash,
    }


__all__ = ["replay_sandbox_execution"]
