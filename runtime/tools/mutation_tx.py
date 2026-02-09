# SPDX-License-Identifier: Apache-2.0
"""
Transactional mutation wrapper for multi-target mutations.
"""

from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from app.agents.mutation_request import MutationTarget
from runtime.tools.mutation_fs import MutationApplyResult, MutationTargetError, apply_target, resolve_agent_root


@dataclass
class MutationRecord:
    target: MutationTarget
    result: MutationApplyResult


class MutationTransaction:
    def __init__(self, agent_id: str, agents_root: Path | None = None) -> None:
        self.agent_id = agent_id
        self.agent_root = resolve_agent_root(agent_id, agents_root)
        self.tx_id = uuid.uuid4().hex
        self.rollback_dir = self.agent_root / ".rollback" / self.tx_id
        self.rollback_dir.mkdir(parents=True, exist_ok=True)
        self._records: List[MutationRecord] = []
        self._backups: Dict[Path, Path] = {}
        self._created: List[Path] = []
        self._committed = False

    def apply(self, target: MutationTarget) -> MutationApplyResult:
        path = (self.agent_root / target.path).resolve()
        if path.exists() and path not in self._backups:
            backup_path = self.rollback_dir / path.relative_to(self.agent_root)
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup_path)
            self._backups[path] = backup_path
        elif not path.exists():
            self._created.append(path)
        result, _ = apply_target(target, self.agent_root)
        self._records.append(MutationRecord(target=target, result=result))
        return result

    def verify(self) -> Dict[str, Any]:
        return {"ok": True, "mutations": len(self._records)}

    def commit(self) -> None:
        self._committed = True
        if self.rollback_dir.exists():
            shutil.rmtree(self.rollback_dir, ignore_errors=True)

    def rollback(self) -> None:
        for created in self._created:
            try:
                if created.exists():
                    created.unlink()
            except Exception:
                continue
        for original, backup in self._backups.items():
            try:
                if backup.exists():
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(backup, original)
            except Exception:
                continue
        if self.rollback_dir.exists():
            shutil.rmtree(self.rollback_dir, ignore_errors=True)

    def __enter__(self) -> "MutationTransaction":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            self.rollback()
            return False
        if not self._committed:
            self.rollback()
        return False

    @property
    def records(self) -> List[MutationRecord]:
        return list(self._records)


__all__ = ["MutationTransaction", "MutationRecord", "MutationTargetError"]
