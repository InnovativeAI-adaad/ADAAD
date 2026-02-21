# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from app.agents.mutation_request import MutationRequest, MutationTarget
from runtime.evolution.governor import EvolutionGovernor, GovernanceDecision
from runtime.evolution.lineage_v2 import LineageLedgerV2
from runtime.governance.foundation import SeededDeterminismProvider


def _request(index: int) -> MutationRequest:
    target = MutationTarget(
        agent_id="alpha",
        path=f"agents/alpha/memory/{index}.json",
        target_type="memory",
        ops=[{"op": "replace", "path": "/value", "value": index}],
        hash_preimage=f"preimage-{index}",
    )
    return MutationRequest(
        agent_id="alpha",
        generation_ts="2026-01-01T00:00:00Z",
        intent="refactor",
        ops=[{"op": "set", "path": "/strategy", "value": "safe"}],
        signature="cryovant-dev-alpha",
        nonce=f"nonce-{index:03d}",
        targets=[target],
        authority_level="governor-review",
    )


def _decision_hash(decision: GovernanceDecision) -> str:
    certificate = dict(decision.certificate or {})
    certificate.pop("checkpoint_digest", None)
    payload = {
        "accepted": decision.accepted,
        "reason": decision.reason,
        "certificate": certificate,
        "replay_status": decision.replay_status,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _run_parallel_validation(
    tmp_path: Path, *, seed: str, count: int, run_label: str
) -> tuple[list[str], list[str], list[int]]:
    def _worker(index: int) -> tuple[str, str, int]:
        epoch_id = f"epoch-concurrent-{index:03d}"
        ledger = LineageLedgerV2(tmp_path / f"lineage-{seed}-{run_label}-{index:03d}.jsonl")
        governor = EvolutionGovernor(
            ledger=ledger,
            provider=SeededDeterminismProvider(seed=f"{seed}:{index:03d}"),
            replay_mode="strict",
        )
        governor.mark_epoch_start(epoch_id)

        decision = governor.validate_bundle(_request(index), epoch_id=epoch_id)

        epoch_entries = ledger.read_epoch(epoch_id)
        bundle_digests = [
            entry["payload"]["bundle_digest"]
            for entry in epoch_entries
            if entry.get("type") == "MutationBundleEvent"
        ]
        return _decision_hash(decision), bundle_digests[0], len(ledger.read_all())

    with mock.patch.dict("os.environ", {"ADAAD_ENV": "dev", "CRYOVANT_DEV_MODE": "1"}, clear=False):
        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = list(pool.map(_worker, range(count)))

    decision_hashes = sorted(item[0] for item in outcomes)
    bundle_hashes = sorted(item[1] for item in outcomes)
    ledger_sizes = sorted(item[2] for item in outcomes)
    return decision_hashes, bundle_hashes, ledger_sizes


def _run_shared_epoch_parallel_validation(
    tmp_path: Path, *, seed: str, count: int, run_label: str
) -> tuple[list[str], str, list[str]]:
    epoch_id = "epoch-shared-concurrent"
    ledger = LineageLedgerV2(tmp_path / f"shared-epoch-{seed}-{run_label}.jsonl")
    governor = EvolutionGovernor(
        ledger=ledger,
        provider=SeededDeterminismProvider(seed=seed),
        replay_mode="strict",
    )
    governor.mark_epoch_start(epoch_id)

    def _worker(index: int) -> GovernanceDecision:
        # Deterministic submission staggering to avoid scheduler randomness artifacts.
        time.sleep(index * 0.001)
        return governor.validate_bundle(_request(index), epoch_id=epoch_id)

    with mock.patch.dict("os.environ", {"ADAAD_ENV": "dev", "CRYOVANT_DEV_MODE": "1"}, clear=False):
        with ThreadPoolExecutor(max_workers=4) as pool:
            decisions = list(pool.map(_worker, range(count)))

    decision_hashes = [_decision_hash(decision) for decision in decisions]
    mutation_bundles = [
        entry
        for entry in ledger.read_epoch(epoch_id)
        if entry.get("type") == "MutationBundleEvent"
    ]
    bundle_ids_in_order = [entry["payload"]["bundle_id"] for entry in mutation_bundles]
    return decision_hashes, ledger.compute_cumulative_epoch_digest(epoch_id), bundle_ids_in_order


def test_parallel_bundle_validation_is_deterministic_in_strict_mode(tmp_path: Path) -> None:
    first_hashes, first_bundle_hashes, first_ledger_sizes = _run_parallel_validation(
        tmp_path,
        seed="parallel-seed",
        count=8,
        run_label="a",
    )
    second_hashes, second_bundle_hashes, second_ledger_sizes = _run_parallel_validation(
        tmp_path,
        seed="parallel-seed",
        count=8,
        run_label="b",
    )

    assert first_hashes == second_hashes
    assert first_bundle_hashes == second_bundle_hashes
    assert first_ledger_sizes == second_ledger_sizes
    assert len(first_ledger_sizes) == 8
    assert min(first_ledger_sizes) >= 2


def test_shared_epoch_parallel_validation_is_deterministic_in_strict_mode(tmp_path: Path) -> None:
    first_hashes, first_epoch_digest, first_bundle_order = _run_shared_epoch_parallel_validation(
        tmp_path,
        seed="shared-seed",
        count=8,
        run_label="a",
    )
    second_hashes, second_epoch_digest, second_bundle_order = _run_shared_epoch_parallel_validation(
        tmp_path,
        seed="shared-seed",
        count=8,
        run_label="b",
    )

    assert first_hashes == second_hashes
    assert first_epoch_digest == second_epoch_digest
    assert first_bundle_order == second_bundle_order
