# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
from unittest import mock

from app.agents.mutation_request import MutationRequest
from app.dream_mode import DreamMode
from app.mutation_executor import MutationExecutor
from runtime.evolution.epoch import EpochManager
from runtime.governance.foundation import SeededDeterminismProvider


class _Governor:
    def __init__(self, tier: str = "audit") -> None:
        self.recovery_tier = type("Tier", (), {"value": tier})()

    def mark_epoch_start(self, epoch_id, metadata):
        return None


class _Ledger:
    def compute_cumulative_epoch_digest(self, _epoch_id: str) -> str:
        return "sha256:0"

    def append_event(self, _event: str, _payload: dict) -> None:
        return None


def _request() -> MutationRequest:
    return MutationRequest(
        agent_id="sample_agent",
        generation_ts="2026-01-01T00:00:00Z",
        intent="mutate",
        ops=[],
        signature="dev-signature",
        nonce="nonce-1",
        bundle_id="bundle-7",
    )


def test_mutation_executor_deterministic_id_in_strict_mode() -> None:
    executor = MutationExecutor(agents_root=Path("/tmp"), provider=SeededDeterminismProvider(seed="strict"))
    executor.evolution_runtime.set_replay_mode("strict")

    request = _request()
    first = executor._build_mutation_id(request, "epoch-1")
    second = executor._build_mutation_id(request, "epoch-1")

    assert first == second


def test_epoch_manager_deterministic_epoch_id_in_audit_mode() -> None:
    governor = _Governor("audit")
    manager = EpochManager(governor, _Ledger(), replay_mode="off", provider=SeededDeterminismProvider(seed="audit"))

    state_a = manager.start_new_epoch({"reason": "boot"})
    manager._state = None
    state_b = manager.start_new_epoch({"reason": "boot"})

    assert state_a.epoch_id == state_b.epoch_id


@mock.patch("app.dream_mode.cryovant.validate_ancestry", return_value=True)
@mock.patch("app.dream_mode.stage_offspring")
@mock.patch("app.dream_mode.agent_path_from_id", return_value=Path("/tmp/agent"))
def test_dream_mode_deterministic_content_in_strict_replay(_path, stage_offspring, _ancestry) -> None:
    dream = DreamMode(Path("/tmp"), Path("/tmp"), replay_mode="strict")
    dream.discover_tasks = mock.Mock(return_value=["sample_agent"])
    dream._read_json = mock.Mock(return_value={"dream_scope": {"enabled": True, "allow": ["mutation"]}})

    dream.run_cycle(agent_id="sample_agent", epoch_id="epoch-1", bundle_id="bundle-7")
    content_a = stage_offspring.call_args.kwargs["content"]

    dream.run_cycle(agent_id="sample_agent", epoch_id="epoch-1", bundle_id="bundle-7")
    content_b = stage_offspring.call_args.kwargs["content"]

    assert content_a == content_b
