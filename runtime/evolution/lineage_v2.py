# SPDX-License-Identifier: Apache-2.0
"""Lineage ledger v2 events and append-only storage helpers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from runtime import ROOT_DIR

LEDGER_V2_PATH = ROOT_DIR / "security" / "ledger" / "lineage_v2.jsonl"


@dataclass(frozen=True)
class LineageEvent:
    event_type: str
    payload: Dict[str, Any]


@dataclass(frozen=True)
class EpochStartEvent:
    epoch_id: str
    ts: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EpochEndEvent:
    epoch_id: str
    ts: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MutationBundleEvent:
    epoch_id: str
    bundle_id: str
    impact: float
    certificate: Dict[str, Any]
    strategy_set: List[str] = field(default_factory=list)
    bundle_digest: str = ""
    epoch_digest: str = ""


class LineageLedgerV2:
    def __init__(self, ledger_path: Path | None = None) -> None:
        self.ledger_path = ledger_path or LEDGER_V2_PATH
        self._epoch_digest_index: Dict[str, str] = {}

    def _ensure(self) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.ledger_path.exists():
            self.ledger_path.touch()

    def _last_hash(self) -> str:
        self._ensure()
        lines = self.ledger_path.read_text(encoding="utf-8").splitlines()
        if not lines:
            return "0" * 64
        try:
            return json.loads(lines[-1]).get("hash", "0" * 64)
        except Exception:
            return "0" * 64

    @staticmethod
    def _compute_hash(prev_hash: str, entry: Dict[str, Any]) -> str:
        material = (prev_hash + json.dumps(entry, ensure_ascii=False, sort_keys=True)).encode("utf-8")
        return hashlib.sha256(material).hexdigest()

    @staticmethod
    def _hash_event(payload: Dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

    def append(self, event: LineageEvent) -> Dict[str, Any]:
        return self.append_event(event.event_type, event.payload)

    def append_event(self, event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        prev_hash = self._last_hash()
        entry: Dict[str, Any] = {
            "type": event_type,
            "payload": payload,
            "prev_hash": prev_hash,
        }
        entry["hash"] = self._compute_hash(prev_hash, entry)
        with self.ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        if event_type == "MutationBundleEvent":
            epoch_id = str(payload.get("epoch_id") or "")
            digest = str(payload.get("epoch_digest") or "")
            if epoch_id and digest:
                self._update_epoch_digest(epoch_id, digest)
        return entry

    def append_typed_event(self, event: EpochStartEvent | EpochEndEvent | MutationBundleEvent) -> Dict[str, Any]:
        event_type = event.__class__.__name__
        return self.append_event(event_type, asdict(event))

    def read_all(self) -> List[Dict[str, Any]]:
        self._ensure()
        entries: List[Dict[str, Any]] = []
        for line in self.ledger_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries

    def read_epoch(self, epoch_id: str) -> List[Dict[str, Any]]:
        return [entry for entry in self.read_all() if entry.get("payload", {}).get("epoch_id") == epoch_id]

    def list_epoch_ids(self) -> List[str]:
        seen: List[str] = []
        for entry in self.read_all():
            epoch_id = entry.get("payload", {}).get("epoch_id")
            if isinstance(epoch_id, str) and epoch_id and epoch_id not in seen:
                seen.append(epoch_id)
        return seen

    def get_expected_epoch_digest(self, epoch_id: str) -> str | None:
        return self.get_epoch_digest(epoch_id)

    def compute_bundle_digest(self, bundle_event: Dict[str, Any]) -> str:
        canonical = {
            "epoch_id": bundle_event.get("epoch_id"),
            "bundle_id": bundle_event.get("bundle_id") or bundle_event.get("certificate", {}).get("bundle_id"),
            "impact": bundle_event.get("impact") or bundle_event.get("impact_score"),
            "strategy_set": bundle_event.get("strategy_set") or bundle_event.get("certificate", {}).get("strategy_set") or [],
            "strategy_snapshot_hash": bundle_event.get("certificate", {}).get("strategy_snapshot_hash", ""),
            "strategy_version_set": bundle_event.get("certificate", {}).get("strategy_version_set", []),
            "certificate": bundle_event.get("certificate") or {},
        }
        material = json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return "sha256:" + hashlib.sha256(material).hexdigest()

    def append_bundle_with_digest(self, epoch_id: str, bundle_event: Dict[str, Any]) -> str:
        previous = self.get_epoch_digest(epoch_id) or "sha256:0"
        bundle_digest = self.compute_bundle_digest(bundle_event)
        chained = hashlib.sha256((previous + bundle_digest).encode("utf-8")).hexdigest()
        epoch_digest = "sha256:" + chained

        payload = dict(bundle_event)
        payload["epoch_id"] = epoch_id
        payload["bundle_digest"] = bundle_digest
        payload["epoch_digest"] = epoch_digest

        self.append_event("MutationBundleEvent", payload)
        self._update_epoch_digest(epoch_id, epoch_digest)
        return epoch_digest

    def get_epoch_digest(self, epoch_id: str) -> Optional[str]:
        if epoch_id in self._epoch_digest_index:
            return self._epoch_digest_index[epoch_id]
        digest: Optional[str] = None
        for entry in self.read_epoch(epoch_id):
            payload = entry.get("payload", {})
            if entry.get("type") == "MutationBundleEvent" and payload.get("epoch_digest"):
                digest = str(payload["epoch_digest"])
            if entry.get("type") == "EpochCheckpointEvent" and payload.get("epoch_digest"):
                digest = str(payload["epoch_digest"])
        if digest:
            self._epoch_digest_index[epoch_id] = digest
        return digest

    def _update_epoch_digest(self, epoch_id: str, digest: str) -> None:
        self._epoch_digest_index[epoch_id] = digest

    def compute_incremental_epoch_digest(self, epoch_id: str) -> str:
        digest = "sha256:0"
        for entry in self.read_epoch(epoch_id):
            if entry.get("type") != "MutationBundleEvent":
                continue
            payload = dict(entry.get("payload") or {})
            bundle_digest = self.compute_bundle_digest(payload)
            digest = "sha256:" + hashlib.sha256((digest + bundle_digest).encode("utf-8")).hexdigest()
        return digest

    def compute_cumulative_epoch_digest(self, epoch_id: str) -> str:
        return self.compute_incremental_epoch_digest(epoch_id)

    def compute_epoch_digest(self, epoch_id: str) -> str:
        events = self.read_epoch(epoch_id)
        digest_input: List[Dict[str, Any]] = []
        for event in events:
            payload = dict(event.get("payload") or {})
            digest_input.append(
                {
                    "type": event.get("type"),
                    "payload": payload,
                }
            )
        material = json.dumps(digest_input, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(material).hexdigest()

    def compute_digest(self, epoch_id: str) -> str:
        return self.compute_epoch_digest(epoch_id)


__all__ = [
    "LineageLedgerV2",
    "LineageEvent",
    "EpochStartEvent",
    "EpochEndEvent",
    "MutationBundleEvent",
    "LEDGER_V2_PATH",
]
