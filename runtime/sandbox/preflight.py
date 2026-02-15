# SPDX-License-Identifier: Apache-2.0
"""Deterministic sandbox preflight checks executed before mutation tests."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from runtime.sandbox.manifest import SandboxManifest
from runtime.sandbox.policy import SandboxPolicy

_DISALLOWED_ENV_KEYS = frozenset({"LD_PRELOAD", "PYTHONINSPECT"})
_DISALLOWED_TOKEN_FRAGMENTS = ("&&", "||", ";", "|", "`", "$(", "${", ">", "<")


def analyze_execution_plan(*, manifest: SandboxManifest, policy: SandboxPolicy) -> dict[str, Any]:
    """Return deterministic preflight verdict for execution plan safety."""
    violations: list[str] = []
    command = tuple(str(item) for item in manifest.command)

    if not command:
        violations.append("missing_command")
    for token in command:
        if any(fragment in token for fragment in _DISALLOWED_TOKEN_FRAGMENTS):
            violations.append(f"disallowed_command_token:{token}")
    for key, _ in manifest.env:
        if key in _DISALLOWED_ENV_KEYS:
            violations.append(f"disallowed_env:{key}")

    allowed_write_roots = tuple(PurePosixPath(root) for root in policy.write_path_allowlist)
    for mount in manifest.mounts:
        if isinstance(mount, (list, tuple)) and len(mount) == 2:
            target = str(mount[1])
        else:
            target = str(mount)
        normalized_target = PurePosixPath(target)
        if not any(normalized_target == root or root in normalized_target.parents for root in allowed_write_roots):
            violations.append(f"disallowed_mount_target:{target}")

    return {
        "ok": not violations,
        "reason": "ok" if not violations else violations[0],
        "violations": tuple(violations),
        "checks": {
            "command": command,
            "env_keys": tuple(key for key, _ in manifest.env),
            "mount_count": len(manifest.mounts),
        },
    }


__all__ = ["analyze_execution_plan"]
