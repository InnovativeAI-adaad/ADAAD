# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved
"""Architect agent governance utilities."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


PROPOSAL_DIR = Path("reports/architect")
PROPOSAL_DIR.mkdir(parents=True, exist_ok=True)
CANON_TAG = "# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved"
BAD_IMPORTS = ("from ..", "import app.")
EVENT_LOG = Path("runtime/logs/events.jsonl")
SYSTEM_PROPOSAL_DIR = PROPOSAL_DIR
KERNEL_STATE = Path("reports/evolution_kernel.json")
META_STATE = Path("reports/meta_mutator.json")


@dataclass
class BlueprintProposal:
    path: str
    rationale: str

    def to_json(self) -> str:
        return json.dumps({"path": self.path, "rationale": self.rationale})


class ArchitectAgent:
    """Generates lightweight blueprint proposals based on missing modules."""

    def __init__(self, root: Path | str = Path("app")) -> None:
        self.root = Path(root)

    def scan_for_placeholders(self) -> List[BlueprintProposal]:
        proposals: List[BlueprintProposal] = []
        for dirpath, _dirnames, filenames in os.walk(self.root):
            for filename in filenames:
                if filename.endswith(".py"):
                    file_path = Path(dirpath) / filename
                    content = file_path.read_text(encoding="utf-8")
                    if not content.strip() or content.strip() == "pass":
                        proposals.append(
                            BlueprintProposal(
                                path=str(file_path),
                                rationale="Stub detected; propose fleshing out implementation",
                            )
                        )
        return proposals

    def scan_for_policy_violations(self) -> List[BlueprintProposal]:
        proposals: List[BlueprintProposal] = []
        for dirpath, _dirnames, filenames in os.walk(self.root):
            for filename in filenames:
                if not filename.endswith(".py"):
                    continue
                file_path = Path(dirpath) / filename
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                lines = content.splitlines()
                if CANON_TAG not in lines[:5]:
                    proposals.append(BlueprintProposal(str(file_path), "Missing ADAAD tag"))
                if "from /" in content or "import /" in content:
                    proposals.append(BlueprintProposal(str(file_path), "Absolute path import"))
        return proposals

    def analyze_runtime_events(self) -> List[BlueprintProposal]:
        proposals: List[BlueprintProposal] = []
        if not EVENT_LOG.exists():
            return proposals
        for line in EVENT_LOG.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("event", "").lower().startswith("error") or payload.get("ok") is False:
                proposals.append(
                    BlueprintProposal(
                        path=str(self.root),
                        rationale=f"Runtime anomaly detected: {payload.get('event')}",
                    )
                )
        return proposals

    def audit_system_layers(self) -> List[BlueprintProposal]:
        proposals: List[BlueprintProposal] = []
        if not KERNEL_STATE.exists():
            proposals.append(BlueprintProposal(str(KERNEL_STATE), "Missing evolution kernel state"))
        else:
            payload = json.loads(KERNEL_STATE.read_text(encoding="utf-8"))
            if "fingerprint" not in payload:
                proposals.append(BlueprintProposal(str(KERNEL_STATE), "Kernel fingerprint absent"))
        if not META_STATE.exists():
            proposals.append(BlueprintProposal(str(META_STATE), "Missing meta-mutator state"))
        return proposals

    def governance_sweep(self) -> List[BlueprintProposal]:
        return (
            self.scan_for_placeholders()
            + self.scan_for_policy_violations()
            + self.analyze_runtime_events()
            + self.audit_system_layers()
        )

    def export_proposals(self, proposals: List[BlueprintProposal]) -> Path:
        timestamped_path = PROPOSAL_DIR / f"architect_proposals_{int(time.time())}.json"
        with timestamped_path.open("w", encoding="utf-8") as handle:
            json.dump([proposal.__dict__ for proposal in proposals], handle, indent=2)
        return timestamped_path

    def export_system_proposals(self, proposals: List[BlueprintProposal]) -> Path:
        timestamped_path = SYSTEM_PROPOSAL_DIR / f"system_proposals_{int(time.time())}.json"
        with timestamped_path.open("w", encoding="utf-8") as handle:
            json.dump([proposal.__dict__ for proposal in proposals], handle, indent=2)
        return timestamped_path

