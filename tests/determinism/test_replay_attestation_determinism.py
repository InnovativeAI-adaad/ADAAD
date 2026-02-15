# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json

from runtime.evolution.lineage_v2 import LineageLedgerV2
from runtime.evolution.replay_attestation import ReplayProofBuilder, verify_replay_proof_bundle
from runtime.governance.foundation import canonical_json


def _seed_epoch(ledger: LineageLedgerV2, *, epoch_id: str) -> None:
    ledger.append_event(
        "EpochStartEvent",
        {
            "epoch_id": epoch_id,
            "ts": "2026-01-01T00:00:00Z",
            "metadata": {"seed": "alpha"},
        },
    )
    ledger.append_bundle_with_digest(
        epoch_id,
        {
            "bundle_id": "bundle-1",
            "impact": 0.42,
            "strategy_set": ["safe_mutation", "entropy_guard"],
            "certificate": {
                "bundle_id": "bundle-1",
                "strategy_set": ["safe_mutation", "entropy_guard"],
                "strategy_snapshot_hash": "sha256:" + ("1" * 64),
                "strategy_version_set": ["v1", "v2"],
            },
        },
    )
    ledger.append_event(
        "EpochCheckpointEvent",
        {
            "epoch_id": epoch_id,
            "checkpoint_id": "chk_0000000000000001",
            "checkpoint_hash": "sha256:" + ("a" * 64),
            "prev_checkpoint_hash": "sha256:0",
            "epoch_digest": ledger.get_epoch_digest(epoch_id) or "sha256:0",
            "baseline_digest": ledger.compute_incremental_epoch_digest(epoch_id),
            "mutation_count": 1,
            "promotion_event_count": 0,
            "scoring_event_count": 0,
            "entropy_policy_hash": "sha256:" + ("b" * 64),
            "promotion_policy_hash": "sha256:" + ("c" * 64),
            "evidence_hash": "sha256:" + ("d" * 64),
            "sandbox_policy_hash": "sha256:" + ("e" * 64),
            "created_at": "2026-01-01T00:01:00Z",
        },
    )


def test_replay_attestation_digest_is_identical_for_identical_input(tmp_path) -> None:
    epoch_id = "epoch-deterministic"
    ledger_a = LineageLedgerV2(tmp_path / "lineage_a.jsonl")
    ledger_b = LineageLedgerV2(tmp_path / "lineage_b.jsonl")
    _seed_epoch(ledger_a, epoch_id=epoch_id)
    _seed_epoch(ledger_b, epoch_id=epoch_id)

    builder_a = ReplayProofBuilder(ledger=ledger_a, proofs_dir=tmp_path / "proofs_a", key_id="proof-key")
    builder_b = ReplayProofBuilder(ledger=ledger_b, proofs_dir=tmp_path / "proofs_b", key_id="proof-key")

    bundle_a = builder_a.build_bundle(epoch_id)
    bundle_b = builder_b.build_bundle(epoch_id)

    assert bundle_a["proof_digest"] == bundle_b["proof_digest"]
    assert canonical_json(bundle_a) == canonical_json(bundle_b)

    path_a = builder_a.write_bundle(epoch_id)
    path_b = builder_b.write_bundle(epoch_id)
    assert path_a.read_text(encoding="utf-8") == path_b.read_text(encoding="utf-8")


def test_replay_attestation_rejects_tampered_bundle(tmp_path) -> None:
    epoch_id = "epoch-tamper"
    ledger = LineageLedgerV2(tmp_path / "lineage.jsonl")
    _seed_epoch(ledger, epoch_id=epoch_id)

    builder = ReplayProofBuilder(ledger=ledger, proofs_dir=tmp_path / "proofs", key_id="proof-key")
    bundle = builder.build_bundle(epoch_id)

    assert verify_replay_proof_bundle(bundle)["ok"]

    digest_tampered = json.loads(json.dumps(bundle))
    digest_tampered["replay_digest"] = "sha256:" + ("f" * 64)
    digest_result = verify_replay_proof_bundle(digest_tampered)
    assert not digest_result["ok"]
    assert digest_result["error"] == "proof_digest_mismatch"

    signature_tampered = json.loads(json.dumps(bundle))
    signature_tampered["signatures"][0]["signature"] = "bad-signature"
    signature_result = verify_replay_proof_bundle(signature_tampered)
    assert not signature_result["ok"]
    assert signature_result["signature_results"][0]["error"] == "signature_mismatch"


def test_replay_attestation_verify_uses_explicit_keyring(tmp_path) -> None:
    epoch_id = "epoch-keyring"
    ledger = LineageLedgerV2(tmp_path / "lineage_keyring.jsonl")
    _seed_epoch(ledger, epoch_id=epoch_id)

    builder = ReplayProofBuilder(ledger=ledger, proofs_dir=tmp_path / "proofs", key_id="proof-key")
    bundle = builder.build_bundle(epoch_id)

    assert not verify_replay_proof_bundle(bundle, keyring={"other-key": "secret"})["ok"]
    assert verify_replay_proof_bundle(bundle, keyring={"proof-key": "adaad-replay-proof-dev-secret:proof-key"})["ok"]
