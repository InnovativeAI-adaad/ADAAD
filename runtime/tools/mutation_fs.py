# SPDX-License-Identifier: Apache-2.0
"""
Filesystem helpers for guarded multi-target mutation operations.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
import tempfile
from pathlib import Path
from typing import Any, Dict, Tuple

from app.agents.mutation_request import MutationTarget
from runtime import ROOT_DIR
from runtime.tools.mutation_guard import _apply_ops


ALLOWED_TARGETS = {
    "dna": ("dna.json",),
    "config": ("config/",),
    "skills": ("skills/",),
}


class MutationTargetError(ValueError):
    pass


@dataclass
class MutationApplyResult:
    path: Path
    applied: int
    skipped: int
    checksum: str


def _hash_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def file_hash(path: Path) -> str:
    if not path.exists():
        return ""
    return _hash_bytes(path.read_bytes())


def resolve_agent_root(agent_id: str, agents_root: Path | None = None) -> Path:
    root = agents_root or (ROOT_DIR / "app" / "agents")
    return root / agent_id.replace(":", "/")


def _normalize_target_path(agent_root: Path, target_path: str) -> Path:
    candidate = Path(target_path)
    if candidate.is_absolute():
        raise MutationTargetError("absolute_path_forbidden")
    resolved = (agent_root / candidate).resolve()
    if agent_root.resolve() not in resolved.parents and resolved != agent_root.resolve():
        raise MutationTargetError("path_traversal_detected")
    return resolved


def _validate_target(target: MutationTarget, agent_root: Path) -> Path:
    if not target.path:
        raise MutationTargetError("missing_path")
    if not target.target_type:
        raise MutationTargetError("missing_target_type")
    normalized = _normalize_target_path(agent_root, target.path)
    allowlist = ALLOWED_TARGETS.get(target.target_type)
    if not allowlist:
        raise MutationTargetError("target_type_not_allowed")
    rel = normalized.relative_to(agent_root).as_posix()
    allowed = False
    for allowed_prefix in allowlist:
        if allowed_prefix.endswith("/") and rel.startswith(allowed_prefix):
            allowed = True
            break
        if rel == allowed_prefix:
            allowed = True
            break
    if not allowed:
        raise MutationTargetError("path_not_allowed")
    if normalized.suffix == ".py":
        raise MutationTargetError("python_mutation_not_allowed")
    if normalized.exists() and normalized.stat().st_mode & 0o111:
        raise MutationTargetError("executable_mutation_not_allowed")
    if normalized.suffix not in {".json", ""}:
        raise MutationTargetError("non_json_target_forbidden")
    return normalized


def apply_target(target: MutationTarget, agent_root: Path) -> Tuple[MutationApplyResult, Dict[str, Any]]:
    path = _validate_target(target, agent_root)
    original_bytes = path.read_bytes() if path.exists() else b"{}"
    original_hash = _hash_bytes(original_bytes)
    if target.hash_preimage and target.hash_preimage != original_hash:
        raise MutationTargetError("hash_preimage_mismatch")
    try:
        data = json.loads(original_bytes.decode("utf-8")) if original_bytes else {}
    except json.JSONDecodeError as exc:
        raise MutationTargetError(f"invalid_json:{exc}") from exc

    applied, skipped = _apply_ops(data, target.ops)
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(data, indent=2, ensure_ascii=False)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(path.parent)) as handle:
        handle.write(serialized)
        temp_path = Path(handle.name)
    temp_path.replace(path)
    checksum = _hash_bytes(serialized.encode("utf-8"))
    return MutationApplyResult(path=path, applied=applied, skipped=skipped, checksum=checksum), data


__all__ = [
    "MutationApplyResult",
    "MutationTargetError",
    "apply_target",
    "file_hash",
    "resolve_agent_root",
]
