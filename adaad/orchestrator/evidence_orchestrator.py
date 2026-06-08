# SPDX-License-Identifier: Apache-2.0
"""Deterministic evidence collection orchestration for evidence bundles."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from runtime.evolution.lineage_v2 import LineageLedgerV2
from runtime.evolution.replay import ReplayEngine
from runtime.governance.deterministic_filesystem import read_file_deterministic
from runtime.governance.foundation import ZERO_HASH

NormalizedEvidenceItem = dict[str, Any]


def _read_jsonl_deterministic(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line_no, line in enumerate(read_file_deterministic(path).splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid_jsonl:{path}:{line_no}:{exc.msg}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"invalid_jsonl_entry:{path}:{line_no}:expected_object")
        entries.append(payload)
    return entries


@dataclass
class EvidenceCollectorContext:
    """Shared immutable inputs and deterministic intermediate outputs."""

    epoch_ids: list[str]
    ledger: LineageLedgerV2
    replay_engine: ReplayEngine
    sandbox_evidence_path: Path
    collected_sections: dict[str, list[NormalizedEvidenceItem]] = field(default_factory=dict)


class EvidenceCollector(Protocol):
    """Collector protocol for deterministic evidence sections."""

    section: str

    def collect(self, context: EvidenceCollectorContext) -> list[NormalizedEvidenceItem]:
        """Collect normalized evidence items for the configured section."""


class MutationBundleCollector:
    section = "bundle_index"

    def collect(self, context: EvidenceCollectorContext) -> list[NormalizedEvidenceItem]:
        bundles: list[NormalizedEvidenceItem] = []
        for epoch_id in context.epoch_ids:
            for entry in context.ledger.read_epoch(epoch_id):
                if entry.get("type") != "MutationBundleEvent":
                    continue
                payload = dict(entry.get("payload") or {})
                bundles.append(
                    {
                        "epoch_id": epoch_id,
                        "bundle_id": str(payload.get("bundle_id") or payload.get("certificate", {}).get("bundle_id") or ""),
                        "bundle_digest": str(payload.get("bundle_digest") or ""),
                        "epoch_digest": str(payload.get("epoch_digest") or ""),
                        "risk_tier": str(payload.get("risk_tier") or ""),
                        "certificate": dict(payload.get("certificate") or {}),
                    }
                )
        bundles.sort(key=lambda item: (item["epoch_id"], item["bundle_id"], item["bundle_digest"]))
        return bundles


class SandboxEvidenceCollector:
    section = "sandbox_evidence"

    def collect(self, context: EvidenceCollectorContext) -> list[NormalizedEvidenceItem]:
        allowed = set(context.epoch_ids)
        evidence: list[NormalizedEvidenceItem] = []
        for entry in _read_jsonl_deterministic(context.sandbox_evidence_path):
            payload = dict(entry.get("payload") or {})
            manifest = dict(payload.get("manifest") or {})
            epoch_id = str(manifest.get("epoch_id") or payload.get("epoch_id") or "")
            if epoch_id not in allowed:
                continue
            evidence.append(
                {
                    "epoch_id": epoch_id,
                    "bundle_id": str(manifest.get("bundle_id") or payload.get("bundle_id") or ""),
                    "evidence_hash": str(payload.get("evidence_hash") or ""),
                    "manifest_hash": str(payload.get("manifest_hash") or ""),
                    "policy_hash": str(payload.get("policy_hash") or ""),
                    "entry_hash": str(entry.get("hash") or ""),
                    "prev_hash": str(entry.get("prev_hash") or ZERO_HASH),
                }
            )
        evidence.sort(key=lambda item: (item["epoch_id"], item["bundle_id"], item["entry_hash"]))
        return evidence


class ReplayProofCollector:
    section = "replay_proofs"

    def collect(self, context: EvidenceCollectorContext) -> list[NormalizedEvidenceItem]:
        proofs: list[NormalizedEvidenceItem] = []
        for epoch_id in context.epoch_ids:
            replay = context.replay_engine.replay_epoch(epoch_id)
            proofs.append(
                {
                    "epoch_id": epoch_id,
                    "digest": str(replay.get("digest") or ""),
                    "canonical_digest": str(replay.get("canonical_digest") or ""),
                    "event_count": int(replay.get("events") or 0),
                    "sandbox_replay": list(replay.get("sandbox_replay") or []),
                }
            )
        proofs.sort(key=lambda item: item["epoch_id"])
        return proofs


class LineageAnchorCollector:
    section = "lineage_anchors"

    def collect(self, context: EvidenceCollectorContext) -> list[NormalizedEvidenceItem]:
        bundle_index = context.collected_sections.get("bundle_index", [])
        anchors: list[NormalizedEvidenceItem] = []
        for epoch_id in context.epoch_ids:
            epoch_bundle_ids = sorted(
                {
                    entry["bundle_id"]
                    for entry in bundle_index
                    if entry["epoch_id"] == epoch_id and entry["bundle_id"]
                }
            )
            anchors.append(
                {
                    "epoch_id": epoch_id,
                    "expected_epoch_digest": str(context.ledger.get_expected_epoch_digest(epoch_id) or ""),
                    "incremental_epoch_digest": str(context.ledger.compute_incremental_epoch_digest(epoch_id)),
                    "bundle_ids": epoch_bundle_ids,
                }
            )
        anchors.sort(key=lambda item: item["epoch_id"])
        return anchors


class SelfAbilitiesCollector:
    """Enhancement for all of ADAAD: collect current high-level self-capable abilities,
    snapshot, and drift report as first-class evidence section.
    Integrates the Phase 199+ self-capable surface (list, discover, drift, provenance, hook)
    into deterministic evidence bundles for governance, replay, and self-audit."""
    section = "self_abilities"

    def collect(self, context: EvidenceCollectorContext) -> list[NormalizedEvidenceItem]:
        try:
            from adaad.abilities import list_abilities, abilities_snapshot  # adaad: import-boundary-ok:evidence-self-capabilities
            from adaad.abilities.drift import detect_abilities_drift
            abilities = [a.to_dict() for a in list_abilities()]
            snapshot = {k: v.to_dict() for k, v in abilities_snapshot().items()}
            drift = detect_abilities_drift().to_dict()
            return [{
                "abilities": abilities,
                "snapshot": snapshot,
                "drift_report": drift,
                "count": len(abilities),
            }]
        except Exception as exc:
            return [{"error": str(exc), "available": False}]


class EvidenceOrchestrator:
    """Runs explicitly-registered collectors in deterministic order."""

    def __init__(self, collectors: list[EvidenceCollector]) -> None:
        self._collectors = list(collectors)

    @property
    def collectors(self) -> tuple[EvidenceCollector, ...]:
        return tuple(self._collectors)

    def collect(self, context: EvidenceCollectorContext) -> dict[str, list[NormalizedEvidenceItem]]:
        outputs: dict[str, list[NormalizedEvidenceItem]] = {}
        for collector in self._collectors:
            items = collector.collect(context)
            outputs[collector.section] = list(items)
            context.collected_sections[collector.section] = outputs[collector.section]
        return outputs


DEFAULT_COLLECTOR_ORDER: tuple[type[EvidenceCollector], ...] = (
    MutationBundleCollector,
    SandboxEvidenceCollector,
    ReplayProofCollector,
    LineageAnchorCollector,
    SelfAbilitiesCollector,  # self-capable enhancement: include abilities/drift in all evidence bundles
)


def create_default_evidence_orchestrator() -> EvidenceOrchestrator:
    """Create the deterministic default orchestrator instance."""

    return EvidenceOrchestrator([collector_type() for collector_type in DEFAULT_COLLECTOR_ORDER])


__all__ = [
    "DEFAULT_COLLECTOR_ORDER",
    "EvidenceCollector",
    "EvidenceCollectorContext",
    "EvidenceOrchestrator",
    "LineageAnchorCollector",
    "MutationBundleCollector",
    "NormalizedEvidenceItem",
    "ReplayProofCollector",
    "SandboxEvidenceCollector",
    "SelfAbilitiesCollector",
    "create_default_evidence_orchestrator",
]
