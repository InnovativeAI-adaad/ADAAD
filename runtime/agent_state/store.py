# SPDX-License-Identifier: Apache-2.0
"""Lightweight JSONL persistence for agent snapshots and execution history."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


class AgentStateStore:
    """Append-only JSONL persistence for agent state."""

    def __init__(self, root: Path | str = Path("runtime/agent_state")) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.snapshots_path = self.root / "snapshots.jsonl"
        self.history_path = self.root / "execution_history.jsonl"

    def _append(self, path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")

    def _read_all(self, path: Path) -> List[Dict[str, Any]]:
        if not path.exists():
            return []
        rows: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return rows

    def write_snapshot(self, agent_id: str, snapshot: Dict[str, Any], now_ts: Optional[float] = None) -> Dict[str, Any]:
        record = {
            "agent_id": str(agent_id),
            "ts": float(now_ts if now_ts is not None else time.time()),
            "snapshot": dict(snapshot),
        }
        self._append(self.snapshots_path, record)
        return record

    def read_snapshot(self, agent_id: str) -> Optional[Dict[str, Any]]:
        rows = self._read_all(self.snapshots_path)
        for row in reversed(rows):
            if row.get("agent_id") == str(agent_id):
                return row
        return None

    def write_execution_event(
        self,
        agent_id: str,
        event_type: str,
        payload: Dict[str, Any],
        *,
        score: Optional[float] = None,
        now_ts: Optional[float] = None,
    ) -> Dict[str, Any]:
        record: Dict[str, Any] = {
            "agent_id": str(agent_id),
            "event_type": str(event_type),
            "payload": dict(payload),
            "ts": float(now_ts if now_ts is not None else time.time()),
        }
        if score is not None:
            record["score"] = float(score)
        self._append(self.history_path, record)
        return record

    def read_recent_execution_history(self, agent_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        rows = [row for row in self._read_all(self.history_path) if row.get("agent_id") == str(agent_id)]
        return rows[-max(0, int(limit)) :]


__all__ = ["AgentStateStore"]
