from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from app.agents.mutation_request import MutationRequest, MutationTarget
from app.mutation_executor import MutationExecutor
from runtime.evolution.epoch import EpochManager
from runtime.evolution.governor import EvolutionGovernor
from runtime.evolution.lineage_v2 import LineageLedgerV2
from runtime.evolution.promotion_manifest import PromotionManifestWriter
from runtime.evolution.runtime import EvolutionRuntime
from runtime.governance.foundation import SeededDeterminismProvider, SystemDeterminismProvider
from runtime.recovery.ledger_guardian import SnapshotManager


class _Governor:
    def __init__(self) -> None:
        self.recovery_tier = type("Tier", (), {"value": "soft"})()

    def mark_epoch_start(self, _epoch_id: str, _metadata: dict) -> None:
        return None

    def mark_epoch_end(self, _epoch_id: str, _metadata: dict) -> None:
        return None

    def _epoch_started(self, _epoch_id: str) -> bool:
        return True


class _Ledger:
    def compute_cumulative_epoch_digest(self, _epoch_id: str) -> str:
        return "sha256:0"

    def append_event(self, _event: str, _payload: dict) -> None:
        return None


def _request() -> MutationRequest:
    return MutationRequest(
        agent_id="alpha",
        generation_ts="2026-01-01T00:00:00Z",
        intent="refactor",
        ops=[],
        signature="cryovant-dev-alpha",
        nonce="nonce-1",
        authority_level="governor-review",
        targets=[
            MutationTarget(
                agent_id="alpha",
                path="dna.json",
                target_type="dna",
                ops=[{"op": "set", "path": "/v", "value": 1}],
                hash_preimage="abc",
            )
        ],
    )


def test_promotion_manifest_is_identical_with_seeded_provider(tmp_path: Path) -> None:
    provider = SeededDeterminismProvider(seed="seed-1")
    writer_a = PromotionManifestWriter(tmp_path / "a", provider=provider, replay_mode="strict")
    writer_b = PromotionManifestWriter(tmp_path / "b", provider=SeededDeterminismProvider(seed="seed-1"), replay_mode="strict")

    payload = {"parent_id": "p", "child_id": "c", "status": "ok"}
    first = writer_a.write(payload)
    second = writer_b.write(payload)

    assert first["manifest_hash"] == second["manifest_hash"]
    assert Path(first["manifest_path"]).name == Path(second["manifest_path"]).name
    assert Path(first["manifest_path"]).read_text(encoding="utf-8") == Path(second["manifest_path"]).read_text(encoding="utf-8")


def test_epoch_manager_epoch_id_is_identical_with_seeded_provider(tmp_path: Path) -> None:
    provider = SeededDeterminismProvider(seed="seed-2")
    manager_a = EpochManager(_Governor(), _Ledger(), replay_mode="strict", state_path=tmp_path / "a.json", provider=provider)
    manager_b = EpochManager(
        _Governor(),
        _Ledger(),
        replay_mode="strict",
        state_path=tmp_path / "b.json",
        provider=SeededDeterminismProvider(seed="seed-2"),
    )

    state_a = manager_a.start_new_epoch({"reason": "boot"})
    state_b = manager_b.start_new_epoch({"reason": "boot"})

    assert state_a.epoch_id == state_b.epoch_id
    assert state_a.start_ts == state_b.start_ts


def test_governor_bundle_id_is_identical_with_seeded_provider(tmp_path: Path) -> None:
    ledger_a = LineageLedgerV2(tmp_path / "a.jsonl")
    ledger_b = LineageLedgerV2(tmp_path / "b.jsonl")
    governor_a = EvolutionGovernor(ledger=ledger_a, provider=SeededDeterminismProvider(seed="seed-3"), replay_mode="strict")
    governor_b = EvolutionGovernor(ledger=ledger_b, provider=SeededDeterminismProvider(seed="seed-3"), replay_mode="strict")

    governor_a.mark_epoch_start("epoch-1")
    governor_b.mark_epoch_start("epoch-1")

    with mock.patch("security.cryovant.signature_valid", return_value=True):
        decision_a = governor_a.validate_bundle(_request(), epoch_id="epoch-1")
        decision_b = governor_b.validate_bundle(_request(), epoch_id="epoch-1")

    assert decision_a.certificate is not None
    assert decision_b.certificate is not None
    assert decision_a.certificate["bundle_id"] == decision_b.certificate["bundle_id"]


def test_snapshot_manager_snapshot_id_is_identical_with_seeded_provider(tmp_path: Path) -> None:
    source = tmp_path / "lineage_v2.jsonl"
    source.write_text('{"type":"EpochStartEvent"}\n', encoding="utf-8")

    snaps_a = SnapshotManager(tmp_path / "a", provider=SeededDeterminismProvider(seed="seed-4"), replay_mode="strict")
    snaps_b = SnapshotManager(tmp_path / "b", provider=SeededDeterminismProvider(seed="seed-4"), replay_mode="strict")

    meta_a = snaps_a.create_snapshot_set([source])
    meta_b = snaps_b.create_snapshot_set([source])

    assert meta_a.snapshot_id == meta_b.snapshot_id
    assert meta_a.timestamp == meta_b.timestamp


def test_mutation_executor_mutation_id_is_identical_with_seeded_provider() -> None:
    executor_a = MutationExecutor(Path("/tmp"), provider=SeededDeterminismProvider(seed="seed-5"))
    executor_b = MutationExecutor(Path("/tmp"), provider=SeededDeterminismProvider(seed="seed-5"))
    executor_a.evolution_runtime.set_replay_mode("strict")
    executor_b.evolution_runtime.set_replay_mode("strict")

    mutation_id_a = executor_a._build_mutation_id(_request(), "epoch-1")
    mutation_id_b = executor_b._build_mutation_id(_request(), "epoch-1")

    assert mutation_id_a == mutation_id_b


@pytest.mark.parametrize(
    "builder",
    [
        lambda tmp: PromotionManifestWriter(tmp / "m", provider=SystemDeterminismProvider(), replay_mode="strict").write({"parent_id": "a", "child_id": "b"}),
        lambda tmp: EpochManager(_Governor(), _Ledger(), replay_mode="strict", state_path=tmp / "e.json", provider=SystemDeterminismProvider()).start_new_epoch({"reason": "boot"}),
        lambda tmp: SnapshotManager(tmp / "s", provider=SystemDeterminismProvider(), replay_mode="strict").create_snapshot_set([tmp / "in.jsonl"]),
    ],
)
def test_strict_mode_rejects_live_provider(tmp_path: Path, builder) -> None:
    source = tmp_path / "in.jsonl"
    source.write_text("{}\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="strict_replay_requires_deterministic_provider"):
        builder(tmp_path)


def test_strict_mode_rejects_live_provider_for_governor(tmp_path: Path) -> None:
    governor = EvolutionGovernor(ledger=LineageLedgerV2(tmp_path / "g.jsonl"), provider=SystemDeterminismProvider(), replay_mode="strict")
    governor.mark_epoch_start("epoch-1")
    with mock.patch("security.cryovant.signature_valid", return_value=True):
        with pytest.raises(RuntimeError, match="strict_replay_requires_deterministic_provider"):
            governor.validate_bundle(_request(), epoch_id="epoch-1")


def test_strict_mode_rejects_live_provider_for_executor() -> None:
    executor = MutationExecutor(Path("/tmp"), provider=SystemDeterminismProvider())
    with pytest.raises(RuntimeError, match="strict_replay_requires_deterministic_provider"):
        executor.evolution_runtime.set_replay_mode("strict")


def test_seeded_provider_protocol_methods_are_deterministic() -> None:
    provider_a = SeededDeterminismProvider(seed="proto-seed")
    provider_b = SeededDeterminismProvider(seed="proto-seed")

    assert provider_a.next_id(label="mutation", length=12) == provider_b.next_id(
        label="mutation", length=12
    )
    assert provider_a.next_token(label="checkpoint", length=10) == provider_b.next_token(
        label="checkpoint", length=10
    )
    assert provider_a.next_int(low=10, high=20, label="snapshot") == provider_b.next_int(
        low=10, high=20, label="snapshot"
    )


def test_seeded_provider_protocol_methods_vary_by_label_and_bounds() -> None:
    provider = SeededDeterminismProvider(seed="proto-seed")

    id_alpha = provider.next_id(label="alpha", length=8)
    id_beta = provider.next_id(label="beta", length=8)
    assert id_alpha != id_beta

    token_alpha = provider.next_token(label="alpha", length=8)
    token_beta = provider.next_token(label="beta", length=8)
    assert token_alpha != token_beta

    value = provider.next_int(low=3, high=7, label="bounded")
    assert 3 <= value <= 7


def test_evolution_runtime_reuses_injected_seeded_provider() -> None:
    provider = SeededDeterminismProvider(seed="runtime-seed")
    runtime = EvolutionRuntime(provider=provider)

    assert runtime.governor.provider is provider
    assert runtime.epoch_manager.provider is provider
    assert runtime.checkpoint_registry.provider is provider


def test_evolution_runtime_strict_mode_rejects_system_provider() -> None:
    runtime = EvolutionRuntime(provider=SystemDeterminismProvider())

    with pytest.raises(RuntimeError, match="strict_replay_requires_deterministic_provider"):
        runtime.set_replay_mode("strict")


def test_mutation_executor_rejects_provider_mismatch_with_injected_runtime() -> None:
    runtime = EvolutionRuntime(provider=SeededDeterminismProvider(seed="runtime-seed"))

    with pytest.raises(ValueError, match="provider_mismatch_with_evolution_runtime"):
        MutationExecutor(
            Path("/tmp"),
            evolution_runtime=runtime,
            provider=SeededDeterminismProvider(seed="other-seed"),
        )


def test_seeded_provider_output_is_call_order_independent() -> None:
    provider_a = SeededDeterminismProvider(seed="order-seed")
    provider_b = SeededDeterminismProvider(seed="order-seed")

    first_a = provider_a.next_id(label="first", length=10)
    second_a = provider_a.next_token(label="second", length=10)

    second_b = provider_b.next_token(label="second", length=10)
    first_b = provider_b.next_id(label="first", length=10)

    assert first_a == first_b
    assert second_a == second_b
