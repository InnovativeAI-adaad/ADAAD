# SPDX-License-Identifier: Apache-2.0
"""Epoch lifecycle management and active epoch state."""

from __future__ import annotations
import hashlib

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict

from runtime import ROOT_DIR
from runtime.evolution.baseline import BaselineStore, create_baseline
from runtime.evolution.checkpoint_verifier import CheckpointVerifier
from runtime.evolution.entropy_discipline import deterministic_context
from runtime.founders_law import epoch_law_metadata
from runtime.governance.deterministic_filesystem import read_file_deterministic
from runtime.governance.foundation import (
    ZERO_HASH,
    RuntimeDeterminismProvider,
    default_provider,
    require_replay_safe_provider,
    sha256_prefixed_digest,
)
from runtime.governance.founders_law_v2 import LawManifest
from runtime.governance.law_evolution_certificate import (
    LawEvolutionCertificate,
    epoch_law_transition_metadata,
    validate_law_transition,
)

STATE_DIR = ROOT_DIR / "runtime" / "evolution" / "state"
CURRENT_EPOCH_PATH = STATE_DIR / "current_epoch.json"


@dataclass
class EpochState:
    epoch_id: str
    start_ts: str
    metadata: Dict[str, Any]
    governor_version: str
    baseline_id: str = ""
    baseline_hash: str = ""
    mutation_count: int = 0
    cumulative_entropy_bits: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "epoch_id": self.epoch_id,
            "start_ts": self.start_ts,
            "metadata": self.metadata,
            "governor_version": self.governor_version,
            "baseline_id": self.baseline_id,
            "baseline_hash": self.baseline_hash,
            "mutation_count": self.mutation_count,
            "cumulative_entropy_bits": self.cumulative_entropy_bits,
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
        baseline_store: BaselineStore | None = None,
        provider: RuntimeDeterminismProvider | None = None,
    ) -> None:
        self.governor = governor
        self.ledger = ledger
        self.max_mutations = max_mutations
        self.max_duration_minutes = max_duration_minutes
        self.state_path = state_path or CURRENT_EPOCH_PATH
        self.replay_mode = replay_mode
        self.baseline_store = baseline_store or BaselineStore()
        self.provider = provider or default_provider()
        require_replay_safe_provider(
            self.provider,
            replay_mode=self.replay_mode,
            recovery_tier=self.governor.recovery_tier.value,
        )
        self._state: EpochState | None = None
        self._force_end = False
        self._force_end_reason = "replay_divergence"

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

    def trigger_force_end(self, reason: str = "replay_divergence") -> None:
        self._force_end = True
        self._force_end_reason = str(reason or "replay_divergence")

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
            return self._force_end_reason
        if state.mutation_count >= self.max_mutations:
            return "mutation_threshold"
        if self._epoch_duration_exceeded(state.start_ts):
            return "duration_threshold"
        return "manual"

    def maybe_rotate(self, reason: str = "threshold") -> EpochState:
        if self.should_rotate():
            return self.rotate_epoch(reason)
        return self.get_active()

    def rotate_epoch(
        self,
        reason: str,
        *,
        old_law_manifest: LawManifest | None = None,
        new_law_manifest: LawManifest | None = None,
        law_certificate: LawEvolutionCertificate | None = None,
        require_replay_safe_law_cert: bool = False,
    ) -> EpochState:
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
        transition_errors = validate_law_transition(
            old_manifest=old_law_manifest,
            new_manifest=new_law_manifest,
            certificate=law_certificate,
            require_replay_safe=require_replay_safe_law_cert,
        )
        if transition_errors:
            raise ValueError("invalid law transition: " + "; ".join(transition_errors))

        continuity = self._verify_terminal_checkpoint_continuity(current.epoch_id)
        if not continuity["ok"]:
            if continuity["reason"] == "prior_checkpoint_missing":
                # Initial epoch or test setup without checkpoints - allow rotation
                terminal_hash = ZERO_HASH
            else:
                self.ledger.append_event(
                    "epoch_checkpoint_continuity_failed",
                    {
                        "epoch_id": current.epoch_id,
                        "reason": continuity["reason"],
                        "details": continuity,
                    },
                )
                raise RuntimeError(f"epoch_checkpoint_continuity_failed:{continuity['reason']}")
        else:
            terminal_hash = continuity["terminal_checkpoint_hash"]

        if continuity["ok"] or continuity["reason"] == "prior_checkpoint_missing":
            self.ledger.append_event(
                "epoch_checkpoint_continuity_verified",
                {
                    "epoch_id": current.epoch_id,
                    "terminal_checkpoint_hash": terminal_hash,
                },
            )

        self._force_end = False
        self._state = self.start_new_epoch(
            {
                "reason": reason,
                "prior_epoch_id": current.epoch_id,
                "prior_terminal_checkpoint_hash": terminal_hash,
            },
            law_manifest=new_law_manifest,
            law_certificate=law_certificate,
        )
        return self._state

    def _verify_terminal_checkpoint_continuity(self, epoch_id: str) -> Dict[str, Any]:
        checkpoints = [
            dict(entry.get("payload") or {})
            for entry in self.ledger.read_epoch(epoch_id)
            if entry.get("type") == "EpochCheckpointEvent"
        ]
        hashed = [checkpoint for checkpoint in checkpoints if str(checkpoint.get("checkpoint_hash") or "")]
        if not hashed:
            return {"ok": False, "reason": "prior_checkpoint_missing", "epoch_id": epoch_id}

        previous_hash = ZERO_HASH
        for index, checkpoint in enumerate(hashed):
            prev_checkpoint_hash = str(checkpoint.get("prev_checkpoint_hash") or "")
            if prev_checkpoint_hash != previous_hash:
                return {
                    "ok": False,
                    "reason": f"prev_checkpoint_hash_mismatch:{index}",
                    "epoch_id": epoch_id,
                    "checkpoint_hash": str(checkpoint.get("checkpoint_hash") or ""),
                    "prev_checkpoint_hash": prev_checkpoint_hash,
                    "expected_prev_checkpoint_hash": previous_hash,
                }

            expected_hash = sha256_prefixed_digest(CheckpointVerifier._checkpoint_material(checkpoint))
            checkpoint_hash = str(checkpoint.get("checkpoint_hash") or "")
            if checkpoint_hash != expected_hash:
                return {
                    "ok": False,
                    "reason": f"checkpoint_hash_mismatch:{index}",
                    "epoch_id": epoch_id,
                    "checkpoint_hash": checkpoint_hash,
                    "expected_checkpoint_hash": expected_hash,
                }
            previous_hash = checkpoint_hash

        return {
            "ok": True,
            "epoch_id": epoch_id,
            "terminal_checkpoint_hash": previous_hash,
            "checkpoint_count": len(hashed),
        }

    def start_new_epoch(
        self,
        metadata: Dict[str, Any] | None = None,
        *,
        law_manifest: LawManifest | None = None,
        law_certificate: LawEvolutionCertificate | None = None,
    ) -> EpochState:
        require_replay_safe_provider(
            self.provider,
            replay_mode=self.replay_mode,
            recovery_tier=self.governor.recovery_tier.value,
        )
        timestamp = self.provider.format_utc("%Y%m%dT%H%M%SZ")
        if deterministic_context(replay_mode=self.replay_mode, recovery_tier=self.governor.recovery_tier.value):
            previous_epoch_id = self._state.epoch_id if self._state else "genesis"
            suffix = self.provider.next_token(
                label=f"epoch:{previous_epoch_id}:{(metadata or {}).get('reason', 'boot')}",
                length=6,
            )
        else:
            suffix = self.provider.next_id(label="epoch", length=6)
        epoch_id = f"epoch-{timestamp}-{suffix}"
        baseline = create_baseline(
            epoch_id=epoch_id,
            replay_mode=self.replay_mode,
            recovery_tier=self.governor.recovery_tier.value,
        )
        self.baseline_store.append(baseline)
        combined_metadata = {
            **epoch_law_metadata(),
            **epoch_law_transition_metadata(law_manifest, law_certificate),
            **(metadata or {}),
        }
        state = EpochState(
            epoch_id=epoch_id,
            start_ts=self.provider.iso_now(),
            metadata=combined_metadata,
            governor_version="3.0.0",
            baseline_id=baseline.baseline_id,
            baseline_hash=baseline.baseline_hash,
            mutation_count=0,
            cumulative_entropy_bits=0,
        )
        self.governor.mark_epoch_start(epoch_id, {**state.metadata})
        self.ledger.append_event(
            "EpochCheckpointEvent",
            {"epoch_id": epoch_id, "epoch_digest": "sha256:0", "checkpoint_hash": "", "prev_checkpoint_hash": ZERO_HASH, "mutation_count": 0, "phase": "start"},
        )
        self._persist(state)
        return state

    def increment_mutation_count(self) -> EpochState:
        state = self.get_active()
        state.mutation_count += 1
        self._persist(state)
        return state

    def add_entropy_bits(self, bits: int) -> EpochState:
        state = self.get_active()
        state.cumulative_entropy_bits += max(0, int(bits))
        self._persist(state)
        return state

    def _persist(self, state: EpochState) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_state(self) -> EpochState | None:
        if not self.state_path.exists():
            return None
        try:
            raw = json.loads(read_file_deterministic(self.state_path))
            return EpochState(
                epoch_id=str(raw.get("epoch_id") or ""),
                start_ts=str(raw.get("start_ts") or self.provider.iso_now()),
                metadata=dict(raw.get("metadata") or {}),
                governor_version=str(raw.get("governor_version") or "3.0.0"),
                baseline_id=str(raw.get("baseline_id") or ""),
                baseline_hash=str(raw.get("baseline_hash") or ""),
                mutation_count=int(raw.get("mutation_count", 0) or 0),
                cumulative_entropy_bits=int(raw.get("cumulative_entropy_bits", 0) or 0),
            )
        except Exception:
            return None

    def _epoch_duration_exceeded(self, start_ts: str) -> bool:
        try:
            started = datetime.fromisoformat(start_ts.replace("Z", "+00:00"))
        except ValueError:
            return False
        now = self.provider.now_utc()
        return now - started >= timedelta(minutes=self.max_duration_minutes)


__all__ = ["EpochManager", "EpochState", "CURRENT_EPOCH_PATH"]
