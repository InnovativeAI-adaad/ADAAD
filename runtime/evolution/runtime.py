# SPDX-License-Identifier: Apache-2.0
"""Evolution runtime wrapper integrating governor, epochs, and replay checks."""

from __future__ import annotations

from typing import Any, Dict

from runtime.evolution.epoch import EpochManager
from runtime.evolution.governor import EvolutionGovernor
from runtime.evolution.lineage_v2 import LineageLedgerV2
from runtime.evolution.replay import ReplayEngine
from runtime.evolution.replay_verifier import ReplayVerifier


class EvolutionRuntime:
    def __init__(self) -> None:
        self.ledger = LineageLedgerV2()
        self.governor = EvolutionGovernor(ledger=self.ledger)
        self.epoch_manager = EpochManager(self.governor, self.ledger)
        self.replay_engine = ReplayEngine(self.ledger)
        self.replay_verifier = ReplayVerifier(self.ledger, self.replay_engine)

        self.current_epoch_id = ""
        self.epoch_metadata: Dict[str, Any] = {}
        self.epoch_mutation_count = 0
        self.epoch_start_ts = ""
        self.epoch_digest: str | None = None

    @property
    def fail_closed(self) -> bool:
        return self.governor.fail_closed

    def boot(self) -> Dict[str, Any]:
        epoch = self.epoch_manager.load_or_create()
        self._sync_from_epoch(epoch.to_dict())
        self.epoch_digest = self.ledger.get_epoch_digest(epoch.epoch_id)
        return epoch.to_dict()

    def before_mutation_cycle(self) -> Dict[str, Any]:
        if self.epoch_manager.should_rotate():
            reason = self.epoch_manager.rotation_reason()
            self.before_epoch_rotation(reason)
            rotated = self.after_epoch_rotation(reason)
            self._sync_from_epoch(rotated)
            return {"epoch_id": rotated["epoch_id"]}

        state = self.epoch_manager.increment_mutation_count()
        payload = state.to_dict()
        self._sync_from_epoch(payload)
        return {"epoch_id": payload["epoch_id"]}

    def after_mutation_cycle(self, result: Dict[str, Any]) -> Dict[str, Any]:
        state = self.epoch_manager.get_active()
        epoch_id = state.epoch_id

        expected = self.ledger.get_epoch_digest(epoch_id) or "sha256:0"
        actual = self.replay_engine.compute_incremental_digest(epoch_id)
        passed = expected == actual

        replay_result = {
            "epoch_id": epoch_id,
            "replay_passed": passed,
            "epoch_digest": expected,
            "replay_digest": actual,
            "expected": expected,
        }
        self.epoch_digest = expected

        self.ledger.append_event(
            "ReplayVerificationEvent",
            {
                "epoch_id": epoch_id,
                "epoch_digest": expected,
                "replay_digest": actual,
                "replay_passed": passed,
            },
        )

        if not passed:
            self.epoch_manager.trigger_force_end()
            self.governor.enter_fail_closed("replay_divergence", epoch_id)

        current = self.epoch_manager.get_active().to_dict()
        self._sync_from_epoch(current)
        return {"epoch": current, "replay": replay_result}

    def before_epoch_rotation(self, reason: str) -> Dict[str, Any]:
        current = self.epoch_manager.get_active()
        return {"epoch_id": current.epoch_id, "reason": reason}

    def after_epoch_rotation(self, reason: str) -> Dict[str, Any]:
        state = self.epoch_manager.rotate_epoch(reason)
        payload = state.to_dict()
        self.epoch_digest = self.ledger.get_epoch_digest(payload["epoch_id"])
        self._sync_from_epoch(payload)
        return payload

    def verify_epoch(self, epoch_id: str, expected: str | None = None) -> Dict[str, Any]:
        replay = self.replay_engine.replay_epoch(epoch_id)
        replay_digest = replay["digest"]
        expected_digest = expected or self.ledger.get_epoch_digest(epoch_id) or "sha256:0"
        passed = replay_digest == expected_digest
        self.ledger.append_event(
            "ReplayVerificationEvent",
            {
                "epoch_id": epoch_id,
                "epoch_digest": expected_digest,
                "replay_digest": replay_digest,
                "replay_passed": passed,
                "expected": expected_digest,
            },
        )
        return {
            "epoch_id": epoch_id,
            "digest": replay_digest,
            "expected": expected_digest,
            "passed": passed,
        }

    def verify_all_epochs(self) -> bool:
        ok = True
        for epoch_id in self.ledger.list_epoch_ids():
            result = self.verify_epoch(epoch_id)
            ok = ok and result["passed"]
        if not ok:
            self.governor.enter_fail_closed("replay_divergence", self.current_epoch_id or "unknown")
        return ok

    def _sync_from_epoch(self, payload: Dict[str, Any]) -> None:
        self.current_epoch_id = str(payload.get("epoch_id") or "")
        self.epoch_metadata = dict(payload.get("metadata") or {})
        self.epoch_mutation_count = int(payload.get("mutation_count") or 0)
        self.epoch_start_ts = str(payload.get("start_ts") or "")


__all__ = ["EvolutionRuntime"]
