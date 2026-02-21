# SPDX-License-Identifier: Apache-2.0
"""
Transactional mutation wrapper for multi-target mutations.
"""

from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Literal

from app.agents.mutation_request import MutationTarget
from runtime.governance.foundation import canonical_json, sha256_prefixed_digest
from runtime.timeutils import now_iso
from runtime.tools.mutation_fs import MutationApplyResult, MutationTargetError, apply_target, resolve_agent_root
from runtime.tools.rollback_certificate import issue_rollback_certificate


@dataclass
class MutationRecord:
    target: MutationTarget
    result: MutationApplyResult


class MutationTransaction:
    def __init__(
        self,
        agent_id: str,
        agents_root: Path | None = None,
        *,
        epoch_id: str = "",
        forward_certificate_digest: str = "",
    ) -> None:
        self.agent_id = agent_id
        self.agent_root = resolve_agent_root(agent_id, agents_root)
        self.tx_id = uuid.uuid4().hex
        self.epoch_id = epoch_id
        self.forward_certificate_digest = forward_certificate_digest
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

    def _rollback_snapshot_digest(self, paths: List[Path]) -> str:
        snapshot = []
        for path in sorted(paths):
            snapshot.append(
                {
                    "path": str(path.relative_to(self.agent_root)),
                    "exists": path.exists(),
                    "digest": sha256_prefixed_digest(path.read_bytes()) if path.exists() else "",
                }
            )
        return sha256_prefixed_digest(canonical_json(snapshot))

    def rollback(self) -> None:
        touched = sorted({*self._backups.keys(), *self._created})
        prior_state_digest = self._rollback_snapshot_digest(touched)

        for created in self._created:
            try:
                if created.exists():
                    created.unlink()
            except Exception:
                continue
        restored_from_backup = 0
        for original, backup in self._backups.items():
            try:
                if backup.exists():
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(backup, original)
                    restored_from_backup += 1
            except Exception:
                continue
        if self.rollback_dir.exists():
            shutil.rmtree(self.rollback_dir, ignore_errors=True)

        restored_state_digest = self._rollback_snapshot_digest(touched)
        issue_rollback_certificate(
            mutation_id=self.tx_id,
            epoch_id=self.epoch_id,
            prior_state_digest=prior_state_digest,
            restored_state_digest=restored_state_digest,
            trigger_reason="transaction_rollback",
            actor_class="MutationTransaction",
            completeness_checks={
                "backups_restored": restored_from_backup == len(self._backups),
                "created_paths_removed": all(not created.exists() for created in self._created),
                "records_count": len(self._records),
                "rollback_finished_at": now_iso(),
            },
            agent_id=self.agent_id,
            forward_certificate_digest=self.forward_certificate_digest,
        )

    def __enter__(self) -> "MutationTransaction":
        return self

    def __exit__(self, exc_type, exc, tb) -> Literal[False]:
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
