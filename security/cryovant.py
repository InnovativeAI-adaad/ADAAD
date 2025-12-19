from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from security.ledger.ledger import append_record, ensure_ledger


class CryovantError(Exception):
    """Raised when Cryovant gatekeeping fails."""


class Cryovant:
    def __init__(self, ledger_dir: Path, keys_dir: Path) -> None:
        self.ledger_dir = ledger_dir
        self.keys_dir = keys_dir
        ensure_ledger(self.ledger_dir)
        self.keys_dir.mkdir(parents=True, exist_ok=True)
        self._lock_keys_dir()

    def _lock_keys_dir(self) -> None:
        try:
            self.keys_dir.chmod(0o700)
        except PermissionError:
            # On some Android shells chmod may be a no-op; continue best-effort.
            pass

    def touch_ledger(self) -> Path:
        return ensure_ledger(self.ledger_dir)

    def append_event(self, record: Dict[str, Any]) -> Path:
        return append_record(self.ledger_dir, record)

    def validate_agent_metadata(self, agent_dir: Path) -> bool:
        if not agent_dir.exists():
            return True

        files = {p.name for p in agent_dir.iterdir() if p.is_file()}
        non_meta_files = [p for p in files if p not in {".keep", "meta.json", "dna.json", "certificate.json"}]
        if non_meta_files:
            return False

        required = {"meta.json", "dna.json", "certificate.json"}
        if files == {".keep"}:
            return True
        return required.issubset(files)

    def gate_cycle(self, agent_roots: Iterable[Path]) -> None:
        for agent_root in agent_roots:
            if not self.validate_agent_metadata(agent_root):
                raise CryovantError(f"Agent metadata missing or invalid in {agent_root}")

    def certify(self, agent_id: str, lineage_hash: str, outcome: str, actor: str = "cryovant") -> Path:
        record = {
            "action": "certify",
            "actor": actor,
            "outcome": outcome,
            "agent_id": agent_id,
            "lineage_hash": lineage_hash,
            "signature_id": f"{agent_id}-{lineage_hash}",
        }
        return self.append_event(record)


def secure_append_jsonl(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(obj, ensure_ascii=False) + "\n")
