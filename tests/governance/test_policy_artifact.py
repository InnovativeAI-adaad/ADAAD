# SPDX-License-Identifier: Apache-2.0

import json

import pytest

from runtime.governance.policy_artifact import (
    GovernancePolicyArtifactEnvelope,
    GovernancePolicyError,
    GovernanceSignerMetadata,
    load_governance_policy,
    policy_artifact_digest,
    verify_policy_artifact_chain,
)


def _artifact(*, signature: str = "sig", previous_hash: str = "sha256:" + "0" * 64) -> dict:
    return {
        "schema_version": "governance_policy_artifact.v1",
        "payload": {
            "schema_version": "governance_policy_v1",
            "model": {"name": "governance_health", "version": "v1.2.3"},
            "determinism_window": 180,
            "mutation_rate_window_sec": 3600,
            "thresholds": {"determinism_pass": 0.97, "determinism_warn": 0.9},
        },
        "signer": {"key_id": "policy-signer-dev", "algorithm": "ed25519"},
        "signature": signature,
        "previous_artifact_hash": previous_hash,
        "effective_epoch": 2,
    }


def test_load_governance_policy_valid(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("runtime.governance.policy_artifact.cryovant.verify_signature", lambda sig: sig == "sig")
    policy_path = tmp_path / "governance_policy_v1.json"
    policy_path.write_text(json.dumps(_artifact()), encoding="utf-8")

    policy = load_governance_policy(policy_path)

    assert policy.schema_version == "governance_policy_v1"
    assert policy.model.version == "v1.2.3"
    assert policy.determinism_window == 180
    assert policy.thresholds.determinism_pass == 0.97
    assert policy.fingerprint.startswith("sha256:")


def test_load_governance_policy_rejects_invalid_signature(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("runtime.governance.policy_artifact.cryovant.verify_signature", lambda _sig: False)
    policy_path = tmp_path / "invalid_signature.json"
    policy_path.write_text(json.dumps(_artifact(signature="bad-signature")), encoding="utf-8")

    with pytest.raises(GovernancePolicyError, match="signature verification failed"):
        load_governance_policy(policy_path)


def test_load_governance_policy_rejects_broken_hash_chain(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("runtime.governance.policy_artifact.cryovant.verify_signature", lambda _sig: True)
    policy_path = tmp_path / "broken_chain.json"
    policy_path.write_text(json.dumps(_artifact(previous_hash="not-a-hash")), encoding="utf-8")

    with pytest.raises(GovernancePolicyError, match="previous_artifact_hash"):
        load_governance_policy(policy_path)


def test_load_governance_policy_accepts_hmac_signature(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("runtime.governance.policy_artifact.cryovant.verify_signature", lambda _sig: False)
    monkeypatch.setattr("runtime.governance.policy_artifact.cryovant.dev_signature_allowed", lambda _sig: False)
    monkeypatch.setenv("ADAAD_POLICY_ARTIFACT_SIGNING_KEY", "policy-secret")

    artifact = _artifact(signature="placeholder")
    artifact["signer"] = {"key_id": "policy-signer-kms", "algorithm": "hmac-sha256"}

    from runtime.governance.policy_artifact import GovernancePolicyArtifactEnvelope, GovernanceSignerMetadata, policy_artifact_digest
    from security import cryovant

    envelope = GovernancePolicyArtifactEnvelope(
        schema_version=artifact["schema_version"],
        payload=artifact["payload"],
        signer=GovernanceSignerMetadata(key_id="policy-signer-kms", algorithm="hmac-sha256"),
        signature="",
        previous_artifact_hash=artifact["previous_artifact_hash"],
        effective_epoch=artifact["effective_epoch"],
    )
    artifact["signature"] = cryovant.sign_hmac_digest(
        key_id="policy-signer-kms",
        signed_digest=policy_artifact_digest(envelope),
        specific_env_prefix="ADAAD_POLICY_ARTIFACT_KEY_",
        generic_env_var="ADAAD_POLICY_ARTIFACT_SIGNING_KEY",
        fallback_namespace="adaad-policy-artifact-dev-secret",
    )
    policy_path = tmp_path / "hmac_signature.json"
    policy_path.write_text(json.dumps(artifact), encoding="utf-8")

    policy = load_governance_policy(policy_path)
    assert policy.signer.algorithm == "hmac-sha256"


def test_load_governance_policy_accepts_dev_signature_via_public_helper(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("runtime.governance.policy_artifact.cryovant.verify_signature", lambda _sig: False)
    monkeypatch.setattr("runtime.governance.policy_artifact.cryovant.dev_signature_allowed", lambda sig: sig.startswith("cryovant-dev-"))
    policy_path = tmp_path / "dev_signature.json"
    policy_path.write_text(json.dumps(_artifact(signature="cryovant-dev-local")), encoding="utf-8")

    policy = load_governance_policy(policy_path)
    assert policy.signature.startswith("cryovant-dev-")


def test_policy_artifact_digest_is_replay_safe_and_deterministic() -> None:
    envelope_a = GovernancePolicyArtifactEnvelope(
        schema_version="governance_policy_artifact.v1",
        payload={"a": 1, "b": 2},
        signer=GovernanceSignerMetadata(key_id="k", algorithm="ed25519"),
        signature="sig-a",
        previous_artifact_hash="sha256:" + "0" * 64,
        effective_epoch=3,
    )
    envelope_b = GovernancePolicyArtifactEnvelope(
        schema_version="governance_policy_artifact.v1",
        payload={"b": 2, "a": 1},
        signer=GovernanceSignerMetadata(key_id="k", algorithm="ed25519"),
        signature="sig-b",
        previous_artifact_hash="sha256:" + "0" * 64,
        effective_epoch=3,
    )

    assert policy_artifact_digest(envelope_a) == policy_artifact_digest(envelope_b)


def test_verify_policy_artifact_chain_detects_broken_link() -> None:
    genesis = GovernancePolicyArtifactEnvelope(
        schema_version="governance_policy_artifact.v1",
        payload={"x": 1},
        signer=GovernanceSignerMetadata(key_id="k", algorithm="ed25519"),
        signature="sig",
        previous_artifact_hash="sha256:" + "0" * 64,
        effective_epoch=0,
    )
    broken = GovernancePolicyArtifactEnvelope(
        schema_version="governance_policy_artifact.v1",
        payload={"x": 2},
        signer=GovernanceSignerMetadata(key_id="k", algorithm="ed25519"),
        signature="sig",
        previous_artifact_hash="sha256:" + "9" * 64,
        effective_epoch=1,
    )

    with pytest.raises(GovernancePolicyError, match="hash chain mismatch"):
        verify_policy_artifact_chain([genesis, broken])
