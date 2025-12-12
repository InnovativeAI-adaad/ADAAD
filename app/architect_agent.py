# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved
"""Architect agent governance utilities."""
from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from runtime.metrics import METRICS_PATH, MutationStage, StageResult


PROPOSAL_DIR = Path("reports/architect")
PROPOSAL_DIR.mkdir(parents=True, exist_ok=True)
CANON_TAG = "# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved"
SYSTEM_PROPOSAL_DIR = PROPOSAL_DIR
KERNEL_STATE = Path("reports/evolution_kernel.json")
META_STATE = Path("reports/meta_mutator.json")


@dataclass
class BlueprintProposal:
    path: str
    rationale: str
    metrics_signal: Dict[str, object] | None = None

    def to_json(self) -> str:
        return json.dumps({"path": self.path, "rationale": self.rationale, "metrics_signal": self.metrics_signal})


class ArchitectAgent:
    """Generates stage-aligned diagnostic blueprint proposals."""

    def __init__(self, root: Path | str = Path("app"), metrics_path: Path = METRICS_PATH) -> None:
        self.root = Path(root)
        self.metrics_path = metrics_path

    def _tail_lines(self, path: Path, max_lines: int = 2000, max_bytes: int = 512 * 1024) -> List[str]:
        if not path.exists():
            return []
        try:
            size = path.stat().st_size
        except OSError:
            return []
        if size <= 0:
            return []
        read_size = min(size, max_bytes)
        try:
            with path.open("rb") as f:
                f.seek(size - read_size)
                chunk = f.read(read_size)
        except OSError:
            return []
        lines = chunk.splitlines()[-max_lines:]
        out: List[str] = []
        for b in lines:
            try:
                out.append(b.decode("utf-8", errors="ignore"))
            except Exception:
                continue
        return out

    def _load_metrics(self) -> List[Dict[str, object]]:
        payloads: List[Dict[str, object]] = []
        for line in self._tail_lines(self.metrics_path):
            try:
                payloads.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return [p for p in payloads if p.get("event_type") == "MUTATION_STAGE"]

    def _dominant_error(self, rows: List[Dict[str, object]]) -> str | None:
        codes = Counter(row.get("error_code") for row in rows if row.get("error_code"))
        if not codes:
            return None
        return codes.most_common(1)[0][0]

    def _stage_blueprint(self, stage: MutationStage, rows: List[Dict[str, object]]) -> BlueprintProposal:
        stage_rows = [row for row in rows if row.get("stage") == stage.value]
        total = len(stage_rows)
        failure_rows = [row for row in stage_rows if row.get("result") == StageResult.FAIL.value]
        dominant = self._dominant_error(stage_rows)
        if total == 0:
            rationale = f"Diagnostic for stage {stage.value}: no stage data in recent metrics tail"
        else:
            rationale = (
                f"Diagnostic for stage {stage.value}: "
                f"{len(failure_rows)}/{total} failures; dominant error={dominant or 'none'}"
            )
        metrics_signal = {
            "stage": stage.value,
            "failures": len(failure_rows),
            "total": total,
            "dominant_error_code": dominant,
        }
        return BlueprintProposal(
            path=f"diagnostics/{stage.value.lower()}.json",
            rationale=rationale,
            metrics_signal=metrics_signal,
        )

    def diagnostic_blueprints(self) -> List[BlueprintProposal]:
        rows = self._load_metrics()
        return [self._stage_blueprint(stage, rows) for stage in MutationStage]

    def audit_system_layers(self) -> List[BlueprintProposal]:
        """Placeholder system audits retained for compatibility."""
        return []

    def governance_sweep(self) -> List[BlueprintProposal]:
        return self.diagnostic_blueprints()

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

