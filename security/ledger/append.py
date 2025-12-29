from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict

LEDGER_PATH = os.path.join("security", "ledger", "ledger.jsonl")


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _read_last_entry_hash(path: str) -> str:
    if not os.path.exists(path):
        return "0" * 64
    last = None
    with open(path, "rb") as f:
        for line in f:
            if line.strip():
                last = line
    if not last:
        return "0" * 64
    try:
        obj = json.loads(last.decode("utf-8"))
        return obj.get("entry_hash") or "0" * 64
    except Exception:
        return "0" * 64


def append_entry(entry: Dict[str, Any], path: str = LEDGER_PATH) -> Dict[str, Any]:
    os.makedirs(os.path.dirname(path), exist_ok=True)

    prev = _read_last_entry_hash(path)
    entry = dict(entry)
    entry["prev_entry_hash"] = prev

    canonical = json.dumps(entry, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    entry_hash = _sha256_hex(canonical)
    entry["entry_hash"] = entry_hash

    line = (json.dumps(entry, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
    with open(path, "ab") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())

    return entry


__all__ = ["append_entry", "LEDGER_PATH"]
