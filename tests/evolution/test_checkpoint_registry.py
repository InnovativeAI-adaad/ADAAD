# SPDX-License-Identifier: Apache-2.0

from runtime.evolution.checkpoint_registry import CheckpointRegistry
from runtime.evolution.checkpoint_verifier import verify_checkpoint_chain
from runtime.evolution.lineage_v2 import LineageLedgerV2
from runtime.governance.foundation.determinism import SeededDeterminismProvider


def test_checkpoint_registry_emits_chain(tmp_path):
    ledger = LineageLedgerV2(tmp_path / "lineage.jsonl")
    epoch_id = "epoch-1"
    ledger.append_event("EpochStartEvent", {"epoch_id": epoch_id, "ts": "2026-01-01T00:00:00Z"})
    ledger.append_bundle_with_digest(epoch_id, {"epoch_id": epoch_id, "bundle_id": "b1", "impact": 0.1, "certificate": {}, "strategy_set": []})
    ledger.append_event("SandboxEvidenceEvent", {"epoch_id": epoch_id, "mutation_id": "m1", "evidence_hash": "sha256:" + ("1" * 64)})

    registry = CheckpointRegistry(ledger, provider=SeededDeterminismProvider("seed"), replay_mode="strict")
    cp1 = registry.create_checkpoint(epoch_id)
    cp2 = registry.create_checkpoint(epoch_id)

    assert cp1["prev_checkpoint_hash"].startswith("sha256:")
    assert cp2["prev_checkpoint_hash"] == cp1["checkpoint_hash"]
    assert cp1["evidence_hash"].startswith("sha256:")
    assert cp1["sandbox_policy_hash"].startswith("sha256:")

    verification = verify_checkpoint_chain(ledger, epoch_id)
    assert verification["passed"]
    assert verification["count"] == 2
