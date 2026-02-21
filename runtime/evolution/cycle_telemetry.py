# SPDX-License-Identifier: Apache-2.0
"""Structured per-cycle telemetry artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from runtime import ROOT_DIR


class CycleTelemetryStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or (ROOT_DIR / "reports" / "cycle_metrics")
        self.history_path = self.root / "history.json"

    def write_metrics(self, cycle_id: str, payload: Dict[str, Any]) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        out_path = self.root / f"{cycle_id}.metrics.json"
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        self._append_history(payload)
        return out_path

    def _append_history(self, payload: Dict[str, Any]) -> None:
        records: List[Dict[str, Any]] = []
        if self.history_path.exists():
            try:
                records = list(json.loads(self.history_path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                records = []
        records.append(payload)
        records = records[-200:]
        self.history_path.write_text(json.dumps(records, indent=2, sort_keys=True), encoding="utf-8")


__all__ = ["CycleTelemetryStore"]
