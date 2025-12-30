# SPDX-License-Identifier: Apache-2.0
"""
Guarded DNA mutation helpers used by the mutation executor.

The helper intentionally constrains mutations to the agent dna.json file and
supports a minimal JSONPatch-style surface (set/add/replace/remove) for
top-level and nested keys. Unknown operations are skipped, and callers always
receive lineage metadata describing what happened.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from runtime import ROOT_DIR
from runtime.timeutils import now_iso


AGENTS_ROOT = ROOT_DIR / "app" / "agents"


def _dna_path(agent_fs_id: str) -> Path:
    return AGENTS_ROOT / agent_fs_id / "dna.json"


def _load_dna(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _checksum(payload: Dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _apply_ops(dna: Dict[str, Any], ops: List[Dict[str, Any]]) -> Tuple[int, int]:
    applied = 0
    skipped = 0
    for op in ops:
        if not isinstance(op, dict):
            skipped += 1
            continue
        path = op.get("path") or op.get("key")
        if not isinstance(path, str) or not path.strip():
            skipped += 1
            continue

        op_name = (op.get("op") or "set").lower()
        value = op.get("value")
        parts = [segment for segment in path.strip("/").split("/") if segment]
        if not parts:
            skipped += 1
            continue

        target: Dict[str, Any] = dna
        valid_path = True
        for segment in parts[:-1]:
            current = target.get(segment)
            if current is None:
                current = {}
                target[segment] = current
            if not isinstance(current, dict):
                valid_path = False
                break
            target = current
        if not valid_path:
            skipped += 1
            continue

        final_key = parts[-1]
        if op_name in {"add", "replace", "set"}:
            target[final_key] = value
            applied += 1
        elif op_name == "remove":
            if final_key in target:
                target.pop(final_key)
            applied += 1
        else:
            skipped += 1

    return applied, skipped


def apply_dna_mutation(agent_fs_id: str, ops: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Apply mutation operations to an agent's dna.json file in a guarded manner.

    The helper treats the mutation request as best-effort: invalid ops are
    skipped, the dna file is created if missing, and a lineage summary with a
    content checksum is returned regardless of whether any mutations were
    applied.
    """

    dna_file = _dna_path(agent_fs_id)
    dna_file.parent.mkdir(parents=True, exist_ok=True)
    dna_data = _load_dna(dna_file)

    applied, skipped = _apply_ops(dna_data, ops)
    if applied or not dna_file.exists():
        dna_file.write_text(json.dumps(dna_data, indent=2), encoding="utf-8")

    checksum = _checksum(dna_data)
    return {
        "agent": agent_fs_id,
        "applied": applied,
        "skipped": skipped,
        "checksum": checksum,
        "updated_at": now_iso(),
        "path": str(dna_file),
    }


__all__ = ["apply_dna_mutation"]
