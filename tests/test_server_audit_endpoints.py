# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations
import pytest
pytestmark = pytest.mark.regression_standard

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


def test_evidence_endpoint_is_auth_gated_and_schema_aligned(monkeypatch, tmp_path) -> None:
    forensics = tmp_path / "forensics"
    forensics.mkdir()
    bundle = {
        "bundle_id": "bundle-789",
        "export_metadata": {"signer": {"key_id": "k", "signature": "sig"}},
    }
    (forensics / "bundle-789.json").write_text(json.dumps(bundle), encoding="utf-8")

    class _FakeBuilder:
        def __init__(self, export_dir):
            self.export_dir = export_dir

        def validate_bundle(self, loaded_bundle):
            assert loaded_bundle["bundle_id"] == "bundle-789"
            return []

    monkeypatch.setattr(server, "FORENSIC_EXPORT_DIR", forensics)
    monkeypatch.setattr(server, "EvidenceBundleBuilder", _FakeBuilder)
    monkeypatch.setenv("ADAAD_AUDIT_TOKENS", json.dumps({"audit-token": ["audit:read"]}))

    with TestClient(server.app) as client:
        unauthorized = client.get("/evidence/bundle-789")
        assert unauthorized.status_code == 401
        authorized = client.get("/evidence/bundle-789", headers=_auth_header())

    assert authorized.status_code == 200
    payload = authorized.json()
    assert payload["authn"]["scope"] == "audit:read"
    assert payload["data"]["bundle_id"] == "bundle-789"



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


def test_reviewer_calibration_endpoint_auth_gate(monkeypatch) -> None:
    """GET /governance/reviewer-calibration requires bearer token with audit:read scope."""
    monkeypatch.setenv("ADAAD_AUDIT_TOKENS", json.dumps({"audit-token": ["audit:read"]}))

    with TestClient(server.app) as client:
        unauthorized = client.get("/governance/reviewer-calibration?epoch_id=epoch-7")
        assert unauthorized.status_code == 401

        authorized = client.get(
            "/governance/reviewer-calibration?epoch_id=epoch-7",
            headers=_auth_header(),
        )

    assert authorized.status_code == 200


def test_reviewer_calibration_endpoint_schema(monkeypatch, tmp_path) -> None:
    """GET /governance/reviewer-calibration returns expected schema keys."""
    monkeypatch.setenv("ADAAD_AUDIT_TOKENS", json.dumps({"audit-token": ["audit:read"]}))

    # Point journal to an empty temp file (no events)
    import server as _server_module
    from security.ledger import journal as _journal_module
    empty_journal = tmp_path / "journal.jsonl"
    empty_journal.touch()
    monkeypatch.setattr(_journal_module, "JOURNAL_PATH", empty_journal)
    monkeypatch.setattr(_journal_module, "TAIL_STATE_PATH", tmp_path / "tail.json")

    with TestClient(server.app) as client:
        resp = client.get(
            "/governance/reviewer-calibration?epoch_id=epoch-99&reviewer_ids=alice,bob",
            headers=_auth_header(),
        )

    assert resp.status_code == 200
    data = resp.json()
    assert list(data.keys()) == ["schema_version", "authn", "data"]
    assert data["data"]["epoch_id"] == "epoch-99"
    assert set(data["data"]["cohort_summary"].keys()) == {"high", "standard", "low"}
    assert "avg_reputation" in data["data"]
    assert "tier_pressure" in data["data"]
    assert data["data"]["constitutional_floor"] == "enforced"
    assert "constitution_version" in data["data"]
    assert "scoring_algorithm_version" in data["data"]
    assert data["authn"]["scope"] == "audit:read"


def test_reviewer_calibration_explicit_reviewer_ids(monkeypatch, tmp_path) -> None:
    """Explicit reviewer_ids param is accepted and returns the contract fields."""
    monkeypatch.setenv("ADAAD_AUDIT_TOKENS", json.dumps({"audit-token": ["audit:read"]}))

    from security.ledger import journal as _journal_module
    empty_journal = tmp_path / "journal.jsonl"
    empty_journal.touch()
    monkeypatch.setattr(_journal_module, "JOURNAL_PATH", empty_journal)
    monkeypatch.setattr(_journal_module, "TAIL_STATE_PATH", tmp_path / "tail.json")

    with TestClient(server.app) as client:
        resp = client.get(
            "/governance/reviewer-calibration?epoch_id=epoch-7&reviewer_ids=alice,bob,carol",
            headers=_auth_header(),
        )

    assert resp.status_code == 200
    payload = resp.json()["data"]
    assert set(payload.keys()) == {
        "cohort_summary",
        "avg_reputation",
        "tier_pressure",
        "constitutional_floor",
        "epoch_id",
        "constitution_version",
        "scoring_algorithm_version",
    }


def test_reviewer_calibration_requires_epoch_id(monkeypatch) -> None:
    monkeypatch.setenv("ADAAD_AUDIT_TOKENS", json.dumps({"audit-token": ["audit:read"]}))

    with TestClient(server.app) as client:
        resp = client.get("/governance/reviewer-calibration", headers=_auth_header())

    assert resp.status_code == 422
    assert resp.json() == {"detail": "missing_epoch_id"}


def test_compliance_export_json_replay_attestations(monkeypatch, tmp_path) -> None:
    proof_dir = tmp_path / "proofs"
    proof_dir.mkdir()
    (proof_dir / "epoch-1.replay_attestation.v1.json").write_text(
        json.dumps(
            {
                "epoch_id": "epoch-1",
                "proof_digest": "sha256:abc",
                "canonical_digest": "sha256:def",
                "checkpoint_chain_digest": "sha256:ghi",
                "replay_digest": "sha256:jkl",
                "signatures": [{"key_id": "k1"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "REPLAY_PROOFS_DIR", proof_dir)
    monkeypatch.setenv("ADAAD_AUDIT_TOKENS", json.dumps({"audit-token": ["audit:read"]}))

    with TestClient(server.app) as client:
        response = client.get(
            "/api/compliance/exports/immutable-replay-attestations?fmt=json",
            headers=_auth_header(),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["dataset"] == "immutable-replay-attestations"
    assert payload["data"]["record_count"] == 1
    assert payload["data"]["records"][0]["epoch_id"] == "epoch-1"
    assert payload["data"]["pagination"]["returned_records"] == 1
    assert payload["data"]["snapshot"]["snapshot_id"].startswith("sha256:")


def test_compliance_export_csv_policy_history(monkeypatch) -> None:
    monkeypatch.setenv("ADAAD_AUDIT_TOKENS", json.dumps({"audit-token": ["audit:read"]}))
    monkeypatch.setattr(
        server.journal,
        "read_entries",
        lambda limit=1000: [
            {
                "entry_id": "e-1",
                "timestamp": "2026-03-26T00:00:00Z",
                "tx_type": "governance_policy_updated",
                "payload": {"reason_code": "policy_rotation"},
            }
        ],
    )

    with TestClient(server.app) as client:
        response = client.get(
            "/api/compliance/exports/policy-change-history?fmt=csv",
            headers=_auth_header(),
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "tx_type" in response.text
    assert "governance_policy_updated" in response.text


def test_compliance_export_supports_limit_offset_pagination(monkeypatch) -> None:
    monkeypatch.setenv("ADAAD_AUDIT_TOKENS", json.dumps({"audit-token": ["audit:read"]}))
    monkeypatch.setattr(
        server.journal,
        "read_entries",
        lambda limit=2000: [
            {
                "entry_id": "inc-1",
                "timestamp": "2026-03-26T00:00:00Z",
                "tx_type": "incident_opened",
                "payload": {"status": "open", "severity": "high"},
            },
            {
                "entry_id": "inc-2",
                "timestamp": "2026-03-26T00:01:00Z",
                "tx_type": "incident_remediation_started",
                "payload": {"status": "in_progress", "severity": "medium"},
            },
            {
                "entry_id": "inc-3",
                "timestamp": "2026-03-26T00:02:00Z",
                "tx_type": "incident_recovered",
                "payload": {"status": "closed", "severity": "low"},
            },
        ],
    )

    with TestClient(server.app) as client:
        response = client.get(
            "/api/compliance/exports/incident-remediation-logs?fmt=json&limit=1&offset=1",
            headers=_auth_header(),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["record_count"] == 1
    assert payload["data"]["records"][0]["entry_id"] == "inc-2"
    assert payload["data"]["pagination"]["next_cursor"] == "o:2"
    assert payload["data"]["indexes"]["status_counts"]["open"] == 1


def test_compliance_export_supports_cursor_pagination(monkeypatch) -> None:
    monkeypatch.setenv("ADAAD_AUDIT_TOKENS", json.dumps({"audit-token": ["audit:read"]}))
    monkeypatch.setattr(
        server.journal,
        "read_entries",
        lambda limit=1000: [
            {
                "entry_id": "p-1",
                "timestamp": "2026-03-26T00:00:00Z",
                "tx_type": "governance_policy_updated",
                "payload": {"reason_code": "rotation"},
            },
            {
                "entry_id": "p-2",
                "timestamp": "2026-03-27T00:00:00Z",
                "tx_type": "governance_policy_updated",
                "payload": {"reason_code": "hotfix"},
            },
        ],
    )

    with TestClient(server.app) as client:
        response = client.get(
            "/api/compliance/exports/policy-change-history?fmt=json&limit=1&cursor=o:1",
            headers=_auth_header(),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["pagination"]["offset"] == 1
    assert payload["data"]["records"][0]["entry_id"] == "p-2"


def test_compliance_export_rejects_invalid_cursor(monkeypatch) -> None:
    monkeypatch.setenv("ADAAD_AUDIT_TOKENS", json.dumps({"audit-token": ["audit:read"]}))

    with TestClient(server.app) as client:
        response = client.get(
            "/api/compliance/exports/policy-change-history?fmt=json&cursor=bad",
            headers=_auth_header(),
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "invalid_cursor"


def test_compliance_export_job_writes_file(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ADAAD_AUDIT_TOKENS", json.dumps({"audit-token": ["audit:read"]}))
    monkeypatch.setattr(server, "COMPLIANCE_EXPORT_DIR", tmp_path / "compliance")
    monkeypatch.setattr(server.journal, "read_entries", lambda limit=2000: [])

    with TestClient(server.app) as client:
        response = client.post(
            "/api/compliance/exports/incident-remediation-logs/jobs?fmt=json",
            headers=_auth_header(),
        )

    assert response.status_code == 200
    payload = response.json()
    output_path = payload["data"]["path"]
    assert payload["data"]["dataset"] == "incident-remediation-logs"
    assert output_path.endswith(".json")
    assert server.Path(output_path).exists()
    assert payload["data"]["snapshot"]["snapshot_id"].startswith("sha256:")
