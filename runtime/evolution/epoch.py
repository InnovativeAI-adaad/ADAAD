# SPDX-License-Identifier: Apache-2.0
"""Epoch lifecycle management and active epoch state."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

from runtime import ROOT_DIR
from runtime.evolution.entropy_discipline import deterministic_context, deterministic_token
from runtime.timeutils import now_iso

STATE_DIR = ROOT_DIR / "runtime" / "evolution" / "state"
CURRENT_EPOCH_PATH = STATE_DIR / "current_epoch.json"


@dataclass
class EpochState:
    epoch_id: str
    start_ts: str
    metadata: Dict[str, Any]
    governor_version: str
    mutation_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "epoch_id": self.epoch_id,
            "start_ts": self.start_ts,
            "metadata": self.metadata,
            "governor_version": self.governor_version,
            "mutation_count": self.mutation_count,
        }


class EpochManager:
    def __init__(
        self,
        governor,
        ledger,
        *,
        max_mutations: int = 50,
        max_duration_minutes: int = 30,
        state_path: Path | None = None,
        replay_mode: str = "off",
    ) -> None:
        self.governor = governor
        self.ledger = ledger
        self.max_mutations = max_mutations
        self.max_duration_minutes = max_duration_minutes
        self.state_path = state_path or CURRENT_EPOCH_PATH
        self.replay_mode = replay_mode
        self._state: EpochState | None = None
        self._force_end = False

    def load_or_create(self) -> EpochState:
        loaded = self._load_state()
        if loaded:
            self._state = loaded
            if not self.governor._epoch_started(loaded.epoch_id):
                self.governor.mark_epoch_start(loaded.epoch_id, {**loaded.metadata, "restored": True})
        else:
            self._state = self.start_new_epoch({"reason": "boot"})
        return self._state

    def get_active(self) -> EpochState:
        if self._state is None:
            return self.load_or_create()
        return self._state

    def trigger_force_end(self) -> None:
        self._force_end = True

    def should_rotate(self) -> bool:
        state = self.get_active()
        if self._force_end:
            return True
        if state.mutation_count >= self.max_mutations:
            return True
        if self._epoch_duration_exceeded(state.start_ts):
            return True
        return False

    def rotation_reason(self) -> str:
        state = self.get_active()
        if self._force_end:
            return "replay_divergence"
        if state.mutation_count >= self.max_mutations:
            return "mutation_threshold"
        if self._epoch_duration_exceeded(state.start_ts):
            return "duration_threshold"
        return "manual"

    def maybe_rotate(self, reason: str = "threshold") -> EpochState:
        if self.should_rotate():
            return self.rotate_epoch(reason)
        return self.get_active()

    def rotate_epoch(self, reason: str) -> EpochState:
        current = self.get_active()
        epoch_digest = self.ledger.compute_cumulative_epoch_digest(current.epoch_id)
        self.governor.mark_epoch_end(
            current.epoch_id,
            {
                "reason": reason,
                "mutation_count": current.mutation_count,
                "epoch_digest": epoch_digest,
            },
        )
        self.ledger.append_event(
            "EpochCheckpointEvent",
            {
                "epoch_id": current.epoch_id,
                "epoch_digest": epoch_digest,
                "mutation_count": current.mutation_count,
                "phase": "end",
            },
        )
        self._force_end = False
        self._state = self.start_new_epoch({"reason": reason})
        return self._state

    def start_new_epoch(self, metadata: Dict[str, Any] | None = None) -> EpochState:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        if deterministic_context(replay_mode=self.replay_mode, recovery_tier=self.governor.recovery_tier.value):
            previous_epoch_id = self._state.epoch_id if self._state else "genesis"
            suffix = deterministic_token(epoch_id=previous_epoch_id, bundle_id=(metadata or {}).get("reason", "boot"), label="epoch", length=6)
        else:
            suffix = uuid.uuid4().hex[:6]
        epoch_id = f"epoch-{timestamp}-{suffix}"
        state = EpochState(
            epoch_id=epoch_id,
            start_ts=now_iso(),
            metadata=metadata or {},
            governor_version="3.0.0",
            mutation_count=0,
        )
        self.governor.mark_epoch_start(epoch_id, {**state.metadata})
        self.ledger.append_event(
            "EpochCheckpointEvent",
            {"epoch_id": epoch_id, "epoch_digest": "sha256:0", "mutation_count": 0, "phase": "start"},
        )
        self._persist(state)
        return state

    def increment_mutation_count(self) -> EpochState:
        state = self.get_active()
        state.mutation_count += 1
        self._persist(state)
        return state

    def _persist(self, state: EpochState) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_state(self) -> EpochState | None:
        if not self.state_path.exists():
            return None
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            return EpochState(
                epoch_id=str(raw.get("epoch_id") or ""),
                start_ts=str(raw.get("start_ts") or now_iso()),
                metadata=dict(raw.get("metadata") or {}),
                governor_version=str(raw.get("governor_version") or "3.0.0"),
                mutation_count=int(raw.get("mutation_count", 0) or 0),
            )
        except Exception:
            return None

    def _epoch_duration_exceeded(self, start_ts: str) -> bool:
        try:
            started = datetime.fromisoformat(start_ts.replace("Z", "+00:00"))
        except ValueError:
            return False
        now = datetime.now(timezone.utc)
        return now - started >= timedelta(minutes=self.max_duration_minutes)


__all__ = ["EpochManager", "EpochState", "CURRENT_EPOCH_PATH"]
