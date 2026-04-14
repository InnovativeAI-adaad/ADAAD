# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable


@dataclass(frozen=True)
class DatasetSnapshot:
    dataset: str
    rows: tuple[dict[str, Any], ...]
    source_version: str
    snapshot_id: str
    indexes: dict[str, Any]


class ComplianceExportService:
    """Assembles compliance datasets with source-keyed memoization."""

    def __init__(
        self,
        *,
        root: Path,
        replay_proofs_dir: Path,
        journal_read_entries: Callable[..., list[dict[str, Any]]],
    ) -> None:
        self._root = root
        self._replay_proofs_dir = replay_proofs_dir
        self._journal_read_entries = journal_read_entries
        self._cache: dict[str, DatasetSnapshot] = {}

    def get_dataset_snapshot(self, dataset: str) -> DatasetSnapshot:
        source_version = self._dataset_source_version(dataset)
        cached = self._cache.get(dataset)
        if cached is not None and cached.source_version == source_version:
            return cached

        rows, indexes = self._assemble_dataset(dataset)
        snapshot_id = "sha256:" + hashlib.sha256(
            json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        snapshot = DatasetSnapshot(
            dataset=dataset,
            rows=tuple(rows),
            source_version=source_version,
            snapshot_id=snapshot_id,
            indexes=indexes,
        )
        self._cache[dataset] = snapshot
        return snapshot

    def paginate(
        self,
        snapshot: DatasetSnapshot,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        total = len(snapshot.rows)
        page_rows = list(snapshot.rows[offset : offset + limit])
        next_offset = offset + len(page_rows)
        has_more = next_offset < total
        next_cursor = f"o:{next_offset}" if has_more else None
        page = {
            "limit": limit,
            "offset": offset,
            "next_cursor": next_cursor,
            "has_more": has_more,
            "returned_records": len(page_rows),
            "total_records": total,
        }
        return page_rows, page

    @staticmethod
    def decode_cursor(cursor: str | None) -> int | None:
        if cursor is None:
            return None
        value = cursor.strip()
        if not value:
            return None
        if not value.startswith("o:"):
            raise ValueError("invalid_cursor")
        try:
            offset = int(value.split(":", 1)[1])
        except ValueError as exc:
            raise ValueError("invalid_cursor") from exc
        if offset < 0:
            raise ValueError("invalid_cursor")
        return offset

    def _dataset_source_version(self, dataset: str) -> str:
        if dataset == "immutable-replay-attestations":
            return self._replay_dir_signature()
        if dataset == "control-evidence-snapshots":
            evidence_matrix = self._root / "docs" / "comms" / "claims_evidence_matrix.md"
            runtime_profile = self._root / "governance_runtime_profile.lock.json"
            return "|".join(
                [
                    f"replay:{self._replay_dir_signature()}",
                    f"evidence:{self._file_signature(evidence_matrix)}",
                    f"runtime:{self._file_signature(runtime_profile)}",
                ]
            )
        if dataset == "policy-change-history":
            policy_baseline = self._root / "governance" / "governance_policy_v1.json"
            return "|".join(
                [
                    f"journal:{self._journal_head_signature(limit=1000)}",
                    f"policy:{self._file_signature(policy_baseline)}",
                ]
            )
        if dataset == "incident-remediation-logs":
            return f"journal:{self._journal_head_signature(limit=2000)}"
        raise KeyError(dataset)

    def _assemble_dataset(self, dataset: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if dataset == "immutable-replay-attestations":
            rows = self._load_replay_attestations()
            return rows, {}
        if dataset == "control-evidence-snapshots":
            rows = self._load_control_evidence_snapshots()
            return rows, {}
        if dataset == "policy-change-history":
            rows = self._load_policy_change_history()
            return rows, self._policy_history_indexes(rows)
        if dataset == "incident-remediation-logs":
            rows = self._load_incident_remediation_logs()
            return rows, self._incident_indexes(rows)
        raise KeyError(dataset)

    def _load_replay_attestations(self) -> list[dict[str, Any]]:
        attestations: list[dict[str, Any]] = []
        if not self._replay_proofs_dir.exists():
            return attestations
        for proof_file in sorted(self._replay_proofs_dir.glob("*.replay_attestation.v1.json")):
            try:
                bundle = json.loads(proof_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            attestations.append(
                {
                    "epoch_id": str(bundle.get("epoch_id") or proof_file.name.split(".", 1)[0]),
                    "proof_digest": str(bundle.get("proof_digest", "")),
                    "canonical_digest": str(bundle.get("canonical_digest", "")),
                    "checkpoint_chain_digest": str(bundle.get("checkpoint_chain_digest", "")),
                    "replay_digest": str(bundle.get("replay_digest", "")),
                    "signature_count": len(bundle.get("signatures", [])) if isinstance(bundle.get("signatures"), list) else 0,
                    "source_path": str(proof_file),
                }
            )
        return attestations

    def _load_control_evidence_snapshots(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        evidence_matrix = self._root / "docs" / "comms" / "claims_evidence_matrix.md"
        if evidence_matrix.exists():
            rows.append(
                {
                    "control_id": "claims-evidence-matrix",
                    "snapshot_type": "evidence_matrix",
                    "source_path": str(evidence_matrix),
                    "sha256": hashlib.sha256(evidence_matrix.read_bytes()).hexdigest(),
                }
            )
        runtime_profile = self._root / "governance_runtime_profile.lock.json"
        if runtime_profile.exists():
            rows.append(
                {
                    "control_id": "governance-runtime-profile",
                    "snapshot_type": "runtime_profile",
                    "source_path": str(runtime_profile),
                    "sha256": hashlib.sha256(runtime_profile.read_bytes()).hexdigest(),
                }
            )
        rows.extend(
            {
                "control_id": f"replay-attestation:{row['epoch_id']}",
                "snapshot_type": "immutable_replay_attestation",
                "source_path": row["source_path"],
                "sha256": row["proof_digest"] or row["canonical_digest"],
            }
            for row in self._load_replay_attestations()
        )
        return rows

    def _load_policy_change_history(self) -> list[dict[str, Any]]:
        entries = self._journal_read_entries(limit=1000)
        filtered: list[dict[str, Any]] = []
        for item in entries:
            tx_type = str(item.get("tx_type", ""))
            payload = item.get("payload", {})
            reason = ""
            if isinstance(payload, dict):
                reason = str(payload.get("reason_code") or payload.get("reason") or "")
            text = f"{tx_type} {reason}".lower()
            if "policy" not in text and "governance" not in text:
                continue
            filtered.append(
                {
                    "entry_id": str(item.get("entry_id", "")),
                    "timestamp": str(item.get("timestamp", "")),
                    "tx_type": tx_type,
                    "reason_code": reason,
                    "payload": payload if isinstance(payload, dict) else {},
                }
            )
        policy_baseline = self._root / "governance" / "governance_policy_v1.json"
        if policy_baseline.exists():
            try:
                baseline = json.loads(policy_baseline.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                baseline = {}
            filtered.insert(
                0,
                {
                    "entry_id": "baseline-governance-policy-v1",
                    "timestamp": "",
                    "tx_type": "policy_baseline",
                    "reason_code": "",
                    "payload": baseline if isinstance(baseline, dict) else {},
                },
            )
        return filtered

    def _load_incident_remediation_logs(self) -> list[dict[str, Any]]:
        entries = self._journal_read_entries(limit=2000)
        rows: list[dict[str, Any]] = []
        for item in entries:
            tx_type = str(item.get("tx_type", ""))
            payload = item.get("payload", {})
            payload_text = json.dumps(payload, sort_keys=True) if isinstance(payload, dict) else str(payload)
            combined = f"{tx_type} {payload_text}".lower()
            if "incident" not in combined and "remediation" not in combined and "recover" not in combined:
                continue
            rows.append(
                {
                    "entry_id": str(item.get("entry_id", "")),
                    "timestamp": str(item.get("timestamp", "")),
                    "tx_type": tx_type,
                    "severity": str(payload.get("severity", "")) if isinstance(payload, dict) else "",
                    "status": str(payload.get("status", "")) if isinstance(payload, dict) else "",
                    "payload": payload if isinstance(payload, dict) else {},
                }
            )
        return rows

    @staticmethod
    def _policy_history_indexes(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
        by_tx_type: dict[str, int] = {}
        for row in rows:
            key = str(row.get("tx_type", "")).strip() or "unknown"
            by_tx_type[key] = by_tx_type.get(key, 0) + 1
        return {"tx_type_counts": by_tx_type}

    @staticmethod
    def _incident_indexes(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
        by_status: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        for row in rows:
            status = str(row.get("status", "")).strip() or "unknown"
            severity = str(row.get("severity", "")).strip() or "unknown"
            by_status[status] = by_status.get(status, 0) + 1
            by_severity[severity] = by_severity.get(severity, 0) + 1
        return {"status_counts": by_status, "severity_counts": by_severity}

    def _replay_dir_signature(self) -> str:
        if not self._replay_proofs_dir.exists():
            return "missing"
        stat = self._replay_proofs_dir.stat()
        parts = [f"dir_mtime_ns:{stat.st_mtime_ns}"]
        for proof_file in sorted(self._replay_proofs_dir.glob("*.replay_attestation.v1.json")):
            file_stat = proof_file.stat()
            parts.append(f"{proof_file.name}:{file_stat.st_mtime_ns}:{file_stat.st_size}")
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()

    def _journal_head_signature(self, *, limit: int) -> str:
        entries = self._journal_read_entries(limit=limit)
        if not entries:
            return "empty"
        head = entries[0]
        tail = entries[-1]
        return "|".join(
            [
                str(head.get("entry_id", "")),
                str(head.get("timestamp", "")),
                str(tail.get("entry_id", "")),
                str(len(entries)),
            ]
        )

    @staticmethod
    def _file_signature(path: Path) -> str:
        if not path.exists():
            return "missing"
        stat = path.stat()
        return f"{path.name}:{stat.st_mtime_ns}:{stat.st_size}"
