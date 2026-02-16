# SPDX-License-Identifier: Apache-2.0
"""Deterministic envelope integration and concurrency tests."""

from __future__ import annotations

import concurrent.futures
from pathlib import Path
from unittest import mock

from app.agents.mutation_request import MutationRequest, MutationTarget
from runtime.evolution.governor import EvolutionGovernor
from runtime.evolution.lineage_v2 import LineageLedgerV2
from runtime.governance.deterministic_envelope import EntropySource, charge_entropy, deterministic_envelope
from runtime.governance.foundation import SeededDeterminismProvider


def _request(idx: int) -> MutationRequest:
    return MutationRequest(
        agent_id="alpha",
        generation_ts=f"2026-02-15T00:00:{idx:02d}Z",
        intent="refactor",
        ops=[{"op": "noop", "index": idx}],
        signature=f"cryovant-dev-alpha-{idx}",
        nonce=f"nonce-{idx:02d}",
        authority_level="governor-review",
        targets=[
            MutationTarget(
                agent_id="alpha",
                path="dna.json",
                target_type="dna",
                ops=[{"op": "set", "path": "/version", "value": idx}],
                hash_preimage="abc",
            )
        ],
    )


def test_serial_submissions_deterministic(tmp_path: Path) -> None:
    ledger_a = LineageLedgerV2(tmp_path / "lineage_a.jsonl")
    ledger_b = LineageLedgerV2(tmp_path / "lineage_b.jsonl")

    governor_a = EvolutionGovernor(
        ledger=ledger_a,
        provider=SeededDeterminismProvider(seed="seed-serial"),
        replay_mode="strict",
    )
    governor_b = EvolutionGovernor(
        ledger=ledger_b,
        provider=SeededDeterminismProvider(seed="seed-serial"),
        replay_mode="strict",
    )

    governor_a.mark_epoch_start("epoch-1")
    governor_b.mark_epoch_start("epoch-1")

    with mock.patch("security.cryovant.signature_valid", return_value=True):
        results_a = [governor_a.validate_bundle(_request(i), "epoch-1") for i in range(5)]
        results_b = [governor_b.validate_bundle(_request(i), "epoch-1") for i in range(5)]

    normalized_a = [(d.accepted, d.reason, d.certificate.get("bundle_id") if d.certificate else None) for d in results_a]
    normalized_b = [(d.accepted, d.reason, d.certificate.get("bundle_id") if d.certificate else None) for d in results_b]
    assert normalized_a == normalized_b


def test_envelope_budget_enforced() -> None:
    with deterministic_envelope(epoch_id="epoch-budget", budget=10):
        charge_entropy(EntropySource.RANDOM, "first")
        decision = None
        try:
            charge_entropy(EntropySource.RANDOM, "second")
        except RuntimeError as exc:
            decision = str(exc)
        assert decision and "entropy_budget_exceeded" in decision


def test_concurrent_envelopes_independent() -> None:
    def run_task(idx: int) -> int:
        with deterministic_envelope(epoch_id=f"epoch-{idx}", budget=100) as ledger:
            charge_entropy(EntropySource.FILESYSTEM, "walk")
            charge_entropy(EntropySource.TIME, "clock")
            return ledger.consumed

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run_task, range(8)))

    assert all(value == 8 for value in results)
