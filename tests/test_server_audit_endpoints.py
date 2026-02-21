from __future__ import annotations

import json

from fastapi.testclient import TestClient

import server


def _auth_header(token: str = "audit-token") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_audit_requires_authentication() -> None:
    with TestClient(server.app) as client:
        response = client.get("/api/audit/epochs/epoch-1/replay-proof")

    assert response.status_code == 401
    assert response.json() == {"detail": "missing_authentication"}


def test_audit_rejects_invalid_token(monkeypatch) -> None:
    monkeypatch.setenv("ADAAD_AUDIT_TOKENS", json.dumps({"known-token": ["audit:read"]}))
    with TestClient(server.app) as client:
        response = client.get("/api/audit/epochs/epoch-1/replay-proof", headers=_auth_header("wrong-token"))

    assert response.status_code == 401
    assert response.json() == {"detail": "invalid_token"}


def test_audit_rejects_insufficient_scope(monkeypatch, tmp_path) -> None:
    proof_dir = tmp_path / "proofs"
    proof_dir.mkdir()
    (proof_dir / "epoch-1.replay_attestation.v1.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "epoch_id": "epoch-1",
                "checkpoint_chain": [],
                "checkpoint_chain_digest": "sha256:" + "0" * 64,
                "replay_digest": "sha256:0",
                "canonical_digest": "0" * 64,
                "policy_hashes": {
                    "promotion_policy_hash": "sha256:0",
                    "entropy_policy_hash": "sha256:0",
                    "sandbox_policy_hash": "sha256:0",
                },
                "proof_digest": "sha256:" + "0" * 64,
                "signatures": [
                    {
                        "key_id": "k",
                        "algorithm": "hmac-sha256",
                        "signed_digest": "sha256:" + "0" * 64,
                        "signature": "sha256:bad",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "REPLAY_PROOFS_DIR", proof_dir)
    monkeypatch.setenv("ADAAD_AUDIT_TOKENS", json.dumps({"audit-token": ["metrics:read"]}))

    with TestClient(server.app) as client:
        response = client.get("/api/audit/epochs/epoch-1/replay-proof", headers=_auth_header())

    assert response.status_code == 403
    assert response.json() == {"detail": "insufficient_scope"}


def test_replay_proof_response_schema_and_redaction(monkeypatch, tmp_path) -> None:
    proof_dir = tmp_path / "proofs"
    proof_dir.mkdir()
    proof = {
        "schema_version": "1.0",
        "epoch_id": "epoch-1",
        "checkpoint_chain": [],
        "checkpoint_chain_digest": "sha256:" + "0" * 64,
        "replay_digest": "sha256:0",
        "canonical_digest": "0" * 64,
        "policy_hashes": {
            "promotion_policy_hash": "sha256:0",
            "entropy_policy_hash": "sha256:0",
            "sandbox_policy_hash": "sha256:0",
        },
        "proof_digest": "sha256:" + "0" * 64,
        "signatures": [
            {
                "key_id": "k",
                "algorithm": "hmac-sha256",
                "signed_digest": "sha256:" + "0" * 64,
                "signature": "sha256:secret",
            }
        ],
    }
    (proof_dir / "epoch-1.replay_attestation.v1.json").write_text(json.dumps(proof), encoding="utf-8")

    monkeypatch.setattr(server, "REPLAY_PROOFS_DIR", proof_dir)
    monkeypatch.setenv("ADAAD_AUDIT_TOKENS", json.dumps({"audit-token": ["audit:read"]}))

    with TestClient(server.app) as client:
        response = client.get(
            "/api/audit/epochs/epoch-1/replay-proof?redaction=sensitive",
            headers=_auth_header(),
        )

    assert response.status_code == 200
    payload = response.json()
    assert list(payload.keys()) == ["schema_version", "authn", "data"]
    assert payload["schema_version"] == "1.0"
    assert payload["authn"] == {"scheme": "bearer", "scope": "audit:read", "redaction": "sensitive"}
    assert list(payload["data"].keys()) == ["epoch_id", "bundle_path", "bundle", "verification"]
    assert "signatures" not in payload["data"]["bundle"]


def test_lineage_response_schema(monkeypatch) -> None:
    class _FakeLedger:
        def read_epoch(self, epoch_id: str):
            return [{"type": "MutationBundleEvent", "payload": {"epoch_id": epoch_id, "bundle_id": "b-1"}}]

        def compute_incremental_epoch_digest(self, epoch_id: str) -> str:
            return "sha256:" + "1" * 64

        def get_expected_epoch_digest(self, epoch_id: str) -> str:
            return "sha256:" + "2" * 64

    monkeypatch.setattr(server, "LineageLedgerV2", _FakeLedger)
    monkeypatch.setattr(server.journal, "read_entries", lambda limit=200: [{"epoch_id": "epoch-1", "entry": "j1"}])
    monkeypatch.setenv("ADAAD_AUDIT_TOKENS", json.dumps({"audit-token": ["audit:read"]}))

    with TestClient(server.app) as client:
        response = client.get("/api/audit/epochs/epoch-1/lineage", headers=_auth_header())

    assert response.status_code == 200
    payload = response.json()
    assert list(payload["data"].keys()) == [
        "epoch_id",
        "lineage",
        "lineage_digest",
        "expected_epoch_digest",
        "journal_entries",
    ]


def test_bundle_response_schema(monkeypatch, tmp_path) -> None:
    forensics = tmp_path / "forensics"
    forensics.mkdir()
    bundle = {
        "bundle_id": "bundle-123",
        "export_metadata": {"signer": {"key_id": "k", "signature": "sig"}},
    }
    (forensics / "bundle-123.json").write_text(json.dumps(bundle), encoding="utf-8")

    class _FakeBuilder:
        def __init__(self, export_dir):
            self.export_dir = export_dir

        def validate_bundle(self, loaded_bundle):
            assert loaded_bundle["bundle_id"] == "bundle-123"
            return []

    monkeypatch.setattr(server, "FORENSIC_EXPORT_DIR", forensics)
    monkeypatch.setattr(server, "EvidenceBundleBuilder", _FakeBuilder)
    monkeypatch.setenv("ADAAD_AUDIT_TOKENS", json.dumps({"audit-token": ["audit:read"]}))

    with TestClient(server.app) as client:
        response = client.get("/api/audit/bundles/bundle-123", headers=_auth_header())

    assert response.status_code == 200
    payload = response.json()
    assert payload["authn"]["scope"] == "audit:read"
    assert list(payload["data"].keys()) == ["bundle_id", "bundle_path", "bundle", "validation"]
    assert "signature" not in payload["data"]["bundle"]["export_metadata"]["signer"]



def test_review_quality_metrics_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(
        server.metrics,
        "tail",
        lambda limit=500: [
            {"event": "governance_review_quality", "payload": {"review_id": "r1", "reviewer": "alice", "latency_seconds": 10}},
            {"event": "governance_review_quality", "payload": {"review_id": "r2", "reviewer": "bob", "latency_seconds": 20}},
        ],
    )

    with TestClient(server.app) as client:
        response = client.get("/metrics/review-quality?limit=50&sla_seconds=86400")

    assert response.status_code == 200
    payload = response.json()
    assert payload["window_limit"] == 50
    assert payload["sla_seconds"] == 86400
    assert payload["window_count"] == 2
    assert payload["review_latency_distribution_seconds"]["count"] == 2
