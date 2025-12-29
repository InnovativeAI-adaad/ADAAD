from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, List, Tuple


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _read_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def _fsync_dir(dir_path: str) -> None:
    try:
        fd = os.open(dir_path, os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except Exception:
        pass


def _atomic_write_bytes(path: str, data: bytes) -> None:
    dir_path = os.path.dirname(path)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    _fsync_dir(dir_path)


def _ensure_agent_dir(agent_id: str) -> str:
    agent_dir = os.path.join("app", "agents", agent_id)
    real = os.path.realpath(agent_dir)
    root = os.path.realpath(os.path.join("app", "agents"))
    if not real.startswith(root + os.sep) and real != root:
        raise PermissionError("Mutation outside app/agents blocked.")
    return agent_dir


def _apply_ops(dna_obj: Dict[str, Any], ops: List[Dict[str, Any]]) -> Dict[str, Any]:
    import copy

    out = copy.deepcopy(dna_obj)

    def parse_ptr(p: str) -> List[str]:
        if not p.startswith("/"):
            raise ValueError("JSON pointer must start with '/'.")
        parts = p.split("/")[1:]
        return [x.replace("~1", "/").replace("~0", "~") for x in parts]

    def resolve_parent(obj: Any, parts: List[str]) -> Tuple[Any, str]:
        if not parts:
            raise ValueError("Path empty.")
        cur = obj
        for k in parts[:-1]:
            if isinstance(cur, list):
                cur = cur[int(k)]
            else:
                cur = cur[k]
        return cur, parts[-1]

    for op in ops:
        kind = op["op"]
        path = op["path"]
        value = op.get("value")
        parts = parse_ptr(path)
        parent, leaf = resolve_parent(out, parts)

        if kind in ("add", "replace"):
            if isinstance(parent, list):
                idx = int(leaf)
                if kind == "add":
                    parent.insert(idx, value)
                else:
                    parent[idx] = value
            else:
                parent[leaf] = value
        elif kind == "remove":
            if isinstance(parent, list):
                del parent[int(leaf)]
            else:
                del parent[leaf]
        else:
            raise ValueError(f"Unsupported op: {kind}")

    return out


def validate_he65_subset(dna_obj: Dict[str, Any]) -> None:
    if not isinstance(dna_obj, dict):
        raise ValueError("dna.json must be an object.")


def apply_dna_mutation(agent_id: str, ops: List[Dict[str, Any]]) -> Dict[str, Any]:
    agent_dir = _ensure_agent_dir(agent_id)
    dna_path = os.path.join(agent_dir, "dna.json")

    if not os.path.exists(dna_path):
        raise FileNotFoundError(f"Agent {agent_id} DNA not found.")

    old_bytes = _read_bytes(dna_path)
    parent_lineage = _sha256_bytes(old_bytes)

    old_obj = json.loads(old_bytes.decode("utf-8"))
    new_obj = _apply_ops(old_obj, ops)
    validate_he65_subset(new_obj)

    new_bytes = json.dumps(new_obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    child_lineage = _sha256_bytes(new_bytes)

    _atomic_write_bytes(dna_path, new_bytes)

    return {
        "agent_id": agent_id,
        "parent_lineage": parent_lineage,
        "child_lineage": child_lineage,
    }


__all__ = [
    "apply_dna_mutation",
    "validate_he65_subset",
]
