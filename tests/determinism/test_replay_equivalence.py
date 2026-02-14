# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from app.agents.mutation_request import MutationRequest
from app.dream_mode import DreamMode
from app.mutation_executor import MutationExecutor
from runtime.evolution.epoch import EpochManager
from runtime.evolution.entropy_discipline import deterministic_context
from runtime.governance.foundation import SeededDeterminismProvider


def test_epoch_id_determinism_in_strict_mode() -> None:
    governor = mock.Mock()
    governor.recovery_tier.value = "audit"
    ledger = mock.Mock()
    ledger.append_event = mock.Mock()

    manager_a = EpochManager(governor, ledger, replay_mode="strict", provider=SeededDeterminismProvider(seed="eq"))
    manager_b = EpochManager(governor, ledger, replay_mode="strict", provider=SeededDeterminismProvider(seed="eq"))

    epoch_a = manager_a.start_new_epoch({"reason": "boot"})
    epoch_b = manager_b.start_new_epoch({"reason": "boot"})
    assert epoch_a.epoch_id == epoch_b.epoch_id


def test_mutation_id_determinism() -> None:
    executor = MutationExecutor(Path("/tmp"), provider=SeededDeterminismProvider(seed="eq-exec"))
    executor.evolution_runtime.set_replay_mode("strict")
    request = MutationRequest(
        agent_id="test_agent",
        generation_ts="2026-01-01T00:00:00Z",
        intent="test",
        ops=[],
        signature="sig",
        nonce="n1",
        bundle_id="bundle-1",
    )
    id_a = executor._build_mutation_id(request, "epoch-1")
    id_b = executor._build_mutation_id(request, "epoch-1")
    assert id_a == id_b
    assert id_a != executor._build_mutation_id(request, "epoch-2")


def test_dream_mutation_token_determinism() -> None:
    dream_a = DreamMode(Path("/tmp"), Path("/tmp"), replay_mode="strict")
    dream_b = DreamMode(Path("/tmp"), Path("/tmp"), replay_mode="strict")
    dream_a.discover_tasks = mock.Mock(return_value=["agent1"])
    dream_b.discover_tasks = mock.Mock(return_value=["agent1"])
    scope = {"dream_scope": {"enabled": True, "allow": ["mutation"]}}
    dream_a._read_json = mock.Mock(return_value=scope)
    dream_b._read_json = mock.Mock(return_value=scope)

    with mock.patch("app.dream_mode.stage_offspring") as stage_a, mock.patch(
        "app.dream_mode.agent_path_from_id", return_value=Path("/tmp")
    ), mock.patch("app.dream_mode.cryovant.validate_ancestry", return_value=True):
        dream_a.run_cycle("agent1", epoch_id="ep1", bundle_id="b1")
        content_a = stage_a.call_args.kwargs["content"]

    with mock.patch("app.dream_mode.stage_offspring") as stage_b, mock.patch(
        "app.dream_mode.agent_path_from_id", return_value=Path("/tmp")
    ), mock.patch("app.dream_mode.cryovant.validate_ancestry", return_value=True):
        dream_b.run_cycle("agent1", epoch_id="ep1", bundle_id="b1")
        content_b = stage_b.call_args.kwargs["content"]

    assert content_a == content_b


@pytest.mark.parametrize(
    "replay_mode,recovery_tier,expected",
    [("strict", "normal", True), ("audit", "normal", True), ("off", "audit", True)],
)
def test_determinism_contract_across_modes(replay_mode: str, recovery_tier: str, expected: bool) -> None:
    assert deterministic_context(replay_mode=replay_mode, recovery_tier=recovery_tier) is expected
