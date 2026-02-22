# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json

from runtime.evolution.lineage_v2 import LineageLedgerV2
from runtime.evolution.replay_attestation import ReplayProofBuilder, validate_replay_proof_schema, verify_replay_proof_bundle
from runtime.governance.foundation import canonical_json, sha256_digest, sha256_prefixed_digest


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


def _attach_trust_metadata(bundle: dict, *, key_epoch_id: str = "epoch-1") -> dict:
    trusted = json.loads(json.dumps(bundle))
    trusted["trust_root_metadata"] = {
        "issuer_chain": ["sovereign-root-A", "federation-anchor-1"],
        "key_epoch": {
            "id": key_epoch_id,
            "valid_from": "2026-01-01T00:00:00Z",
            "valid_until": "2026-12-31T23:59:59Z",
        },
        "revocation_reference": {
            "source": "offline-revocation-ledger",
            "reference": "rl-2026-01",
        },
        "trust_policy_version": "trust-policy-v1",
    }
    unsigned_bundle = {
        "schema_version": trusted.get("schema_version"),
        "epoch_id": trusted.get("epoch_id"),
        "baseline_digest": trusted.get("baseline_digest"),
        "ledger_state_hash": trusted.get("ledger_state_hash"),
        "mutation_graph_fingerprint": trusted.get("mutation_graph_fingerprint"),
        "constitution_version": trusted.get("constitution_version"),
        "sandbox_policy_hash": trusted.get("sandbox_policy_hash"),
        "checkpoint_chain": trusted.get("checkpoint_chain", []),
        "checkpoint_chain_digest": trusted.get("checkpoint_chain_digest"),
        "replay_digest": trusted.get("replay_digest"),
        "canonical_digest": trusted.get("canonical_digest"),
        "policy_hashes": trusted.get("policy_hashes", {}),
        "trust_root_metadata": trusted.get("trust_root_metadata"),
    }
    proof_digest = sha256_prefixed_digest(unsigned_bundle)
    trusted["proof_digest"] = proof_digest
    key_id = trusted["signature_bundle"]["key_id"]
    secret = f"adaad-replay-proof-dev-secret:{key_id}"
    signature = "sha256:" + sha256_digest(f"{secret}:{proof_digest}")
    trusted["signature_bundle"]["signed_digest"] = proof_digest
    trusted["signature_bundle"]["signature"] = signature
    trusted["signatures"][0]["signed_digest"] = proof_digest
    trusted["signatures"][0]["signature"] = signature
    return trusted


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
    assert bundle_a["signature_bundle"] == bundle_b["signature_bundle"]
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

    assert validate_replay_proof_schema(bundle) == []
    assert verify_replay_proof_bundle(bundle)["ok"]

    digest_tampered = json.loads(json.dumps(bundle))
    digest_tampered["replay_digest"] = "sha256:" + ("f" * 64)
    digest_result = verify_replay_proof_bundle(digest_tampered)
    assert not digest_result["ok"]
    assert digest_result["error"] == "proof_digest_mismatch"

    signature_bundle_tampered = json.loads(json.dumps(bundle))
    signature_bundle_tampered["signature_bundle"]["signed_digest"] = "sha256:" + ("9" * 64)
    signature_bundle_result = verify_replay_proof_bundle(signature_bundle_tampered)
    assert not signature_bundle_result["ok"]
    assert signature_bundle_result["error"] == "signature_bundle_mismatch"

    schema_pattern_tampered = json.loads(json.dumps(bundle))
    schema_pattern_tampered["ledger_state_hash"] = "not-a-sha256"
    schema_pattern_result = verify_replay_proof_bundle(schema_pattern_tampered)
    assert not schema_pattern_result["ok"]
    assert schema_pattern_result["error"] == "schema_validation_failed"

    signature_tampered = json.loads(json.dumps(bundle))
    signature_tampered["signatures"][0]["signature"] = "bad-signature"
    signature_tampered["signature_bundle"]["signature"] = "bad-signature"
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


def test_replay_attestation_cross_instance_rejects_unaccepted_issuer(tmp_path) -> None:
    epoch_id = "epoch-cross-instance-issuer"
    ledger = LineageLedgerV2(tmp_path / "lineage_cross_instance.jsonl")
    _seed_epoch(ledger, epoch_id=epoch_id)

    builder = ReplayProofBuilder(ledger=ledger, proofs_dir=tmp_path / "proofs", key_id="proof-key")
    bundle = _attach_trust_metadata(builder.build_bundle(epoch_id))

    result = verify_replay_proof_bundle(
        bundle,
        keyring={"proof-key": "adaad-replay-proof-dev-secret:proof-key"},
        accepted_issuers=["unknown-root"],
    )
    assert not result["ok"]
    assert result["error"] == "issuer_not_accepted"


def test_replay_attestation_cross_instance_key_rotation_window_enforced(tmp_path) -> None:
    epoch_id = "epoch-cross-instance-window"
    ledger = LineageLedgerV2(tmp_path / "lineage_cross_window.jsonl")
    _seed_epoch(ledger, epoch_id=epoch_id)

    builder = ReplayProofBuilder(ledger=ledger, proofs_dir=tmp_path / "proofs", key_id="proof-key")
    bundle = _attach_trust_metadata(builder.build_bundle(epoch_id), key_epoch_id="epoch-rotation-1")

    allowed_windows = {
        "epoch-rotation-1": {
            "valid_from": "2026-02-01T00:00:00Z",
            "valid_until": "2026-03-01T00:00:00Z",
        }
    }
    result = verify_replay_proof_bundle(
        bundle,
        keyring={"proof-key": "adaad-replay-proof-dev-secret:proof-key"},
        accepted_issuers=["sovereign-root-A"],
        key_validity_windows=allowed_windows,
        trust_policy_version="trust-policy-v1",
    )
    assert not result["ok"]
    assert result["signature_results"][0]["error"] == "key_validity_window_violation"


def test_replay_attestation_cross_instance_revocation_check(tmp_path) -> None:
    epoch_id = "epoch-cross-instance-revocation"
    ledger = LineageLedgerV2(tmp_path / "lineage_cross_revocation.jsonl")
    _seed_epoch(ledger, epoch_id=epoch_id)

    builder = ReplayProofBuilder(ledger=ledger, proofs_dir=tmp_path / "proofs", key_id="proof-key")
    bundle = _attach_trust_metadata(builder.build_bundle(epoch_id), key_epoch_id="epoch-rotation-2")

    def _revocation_source(*, key_id: str, trust_metadata: dict, revocation_reference: dict) -> bool:
        _ = trust_metadata
        return key_id == "proof-key" and revocation_reference.get("reference") == "rl-2026-01"

    result = verify_replay_proof_bundle(
        bundle,
        keyring={"proof-key": "adaad-replay-proof-dev-secret:proof-key"},
        accepted_issuers=["sovereign-root-A"],
        key_validity_windows={
            "epoch-rotation-2": {
                "valid_from": "2026-01-01T00:00:00Z",
                "valid_until": "2026-12-31T23:59:59Z",
            }
        },
        revocation_source=_revocation_source,
        trust_policy_version="trust-policy-v1",
    )
    assert not result["ok"]
    assert result["signature_results"][0]["error"] == "key_revoked"
