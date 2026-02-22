# SPDX-License-Identifier: Apache-2.0
"""
Transactional mutation wrapper for multi-target mutations.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Literal

from app.agents.mutation_request import MutationTarget
from runtime.evolution.entropy_discipline import deterministic_context
from runtime.governance.foundation import RuntimeDeterminismProvider, canonical_json, default_provider, require_replay_safe_provider, sha256_prefixed_digest
from runtime.timeutils import now_iso
from runtime.tools.mutation_fs import MutationApplyResult, MutationTargetError, apply_target, resolve_agent_root
from runtime.tools.rollback_certificate import issue_rollback_certificate


@dataclass
class MutationRecord:
    target: MutationTarget
    result: MutationApplyResult


class MutationVerificationError(MutationTargetError):
    """Raised when post-apply transaction invariants fail verification."""


class MutationTransaction:
    def __init__(
        self,
        agent_id: str,
        agents_root: Path | None = None,
        *,
        epoch_id: str = "",
        mutation_id: str = "",
        replay_seed: str = "",
        replay_mode: str = "off",
        recovery_tier: str | None = None,
        provider: RuntimeDeterminismProvider | None = None,
        forward_certificate_digest: str = "",
    ) -> None:
        self.agent_id = agent_id
        self.agent_root = resolve_agent_root(agent_id, agents_root)
        self.epoch_id = epoch_id
        self.mutation_id = mutation_id
        self.replay_seed = replay_seed
        self.replay_mode = replay_mode
        self.recovery_tier = recovery_tier
        self.provider = provider or default_provider()
        self.tx_id = self._build_transaction_id()
        self.forward_certificate_digest = forward_certificate_digest
        self.rollback_dir = self.agent_root / ".rollback" / self.tx_id
        self.rollback_dir.mkdir(parents=True, exist_ok=True)
        self._records: List[MutationRecord] = []
        self._backups: Dict[Path, Path] = {}
        self._created: List[Path] = []
        self._committed = False

    def _build_transaction_id(self) -> str:
        if deterministic_context(replay_mode=self.replay_mode, recovery_tier=self.recovery_tier):
            require_replay_safe_provider(
                self.provider,
                replay_mode=self.replay_mode,
                recovery_tier=self.recovery_tier,
            )
        return self.provider.next_id(
            label=(
                f"mutation-tx:{self.epoch_id}:{self.agent_id}:"
                f"{self.mutation_id or 'none'}:{self.replay_seed or 'none'}"
            ),
            length=32,
        )

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
        root = self.agent_root.resolve()
        path_resolution_ok = True
        touched_from_targets: set[str] = set()
        touched_from_results: set[str] = set()
        metadata_consistent = True
        metadata_checks: List[Dict[str, Any]] = []

        for record in self._records:
            target_resolved = (root / record.target.path).resolve()
            target_in_root = root in target_resolved.parents or target_resolved == root
            if not target_in_root:
                path_resolution_ok = False
            else:
                touched_from_targets.add(str(target_resolved.relative_to(root)))

            result_resolved = record.result.path.resolve()
            result_in_root = root in result_resolved.parents or result_resolved == root
            if not result_in_root:
                path_resolution_ok = False
                rel_path = str(result_resolved)
            else:
                rel_path = str(result_resolved.relative_to(root))
                touched_from_results.add(rel_path)

            checksum_matches = result_resolved.exists() and sha256_prefixed_digest(result_resolved.read_bytes()) == f"sha256:{record.result.checksum}"
            applied_valid = isinstance(record.result.applied, int) and record.result.applied >= 0
            skipped_valid = isinstance(record.result.skipped, int) and record.result.skipped >= 0
            ops_accounted = applied_valid and skipped_valid and (record.result.applied + record.result.skipped == len(record.target.ops))
            if not (checksum_matches and ops_accounted):
                metadata_consistent = False

            metadata_checks.append(
                {
                    "path": rel_path,
                    "checksum_matches_file": checksum_matches,
                    "applied_non_negative": applied_valid,
                    "skipped_non_negative": skipped_valid,
                    "ops_accounted": ops_accounted,
                }
            )

        records_present = len(self._records) > 0
        touched_set_stable = (touched_from_targets == touched_from_results and len(touched_from_results) > 0) if records_present else True
        ok = path_resolution_ok and metadata_consistent and touched_set_stable
        verification = {
            "ok": ok,
            "mutations": len(self._records),
            "invariants": {
                "records_present_when_requested": records_present,
                "paths_resolve_under_agent_root": path_resolution_ok,
                "touched_file_set_stable": touched_set_stable,
                "metadata_consistent": metadata_consistent,
            },
            "touched": {
                "requested": sorted(touched_from_targets),
                "recorded": sorted(touched_from_results),
            },
            "metadata_checks": metadata_checks,
        }
        if not ok:
            raise MutationVerificationError("transaction_verify_failed")
        return verification

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


__all__ = ["MutationTransaction", "MutationRecord", "MutationTargetError", "MutationVerificationError"]
