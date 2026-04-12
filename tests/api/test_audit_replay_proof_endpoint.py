# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json

from fastapi.testclient import TestClient

import server


def _auth_and_tenant_headers(token: str = "audit-token") -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Id": "tenant-test",
        "X-Workspace-Id": "workspace-test",
    }


def _write_proof(tmp_path) -> None:
    proof_dir = tmp_path / "proofs"
    proof_dir.mkdir()
    proof = {
        "schema_version": "1.0",
        "epoch_id": "epoch-1",
        "tenant_id": "tenant-test",
        "workspace_id": "workspace-test",
        "proof_digest": "sha256:" + "0" * 64,
        "signatures": [
            {
                "key_id": "k1",
                "algorithm": "hmac-sha256",
                "signed_digest": "sha256:" + "0" * 64,
                "signature": "sha256:secret-1",
            },
            {
                "key_id": "k2",
                "algorithm": "ed25519",
                "signed_digest": "sha256:" + "1" * 64,
                "signature": "ed25519:secret-2",
            },
        ],
    }
    (proof_dir / "epoch-1.replay_attestation.v1.json").write_text(json.dumps(proof), encoding="utf-8")


def test_replay_proof_default_mode_preserves_signatures(monkeypatch, tmp_path) -> None:
    _write_proof(tmp_path)
    monkeypatch.setattr(server, "REPLAY_PROOFS_DIR", tmp_path / "proofs")
    monkeypatch.setenv("ADAAD_AUDIT_TOKENS", json.dumps({"audit-token": ["audit:read"]}))

    with TestClient(server.app) as client:
        response = client.get(
            "/api/audit/epochs/epoch-1/replay-proof",
            headers=_auth_and_tenant_headers(),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["bundle"]["signatures"][0]["signature"] == "sha256:secret-1"
    assert payload["data"]["bundle"]["signatures"][1]["signature"] == "ed25519:secret-2"
    assert payload["data"]["verification"]["signatures_present"] is True


def test_replay_proof_sensitive_redaction_preserves_contract(monkeypatch, tmp_path) -> None:
    _write_proof(tmp_path)
    monkeypatch.setattr(server, "REPLAY_PROOFS_DIR", tmp_path / "proofs")
    monkeypatch.setenv("ADAAD_AUDIT_TOKENS", json.dumps({"audit-token": ["audit:read"]}))

    with TestClient(server.app) as client:
        response = client.get(
            "/api/audit/epochs/epoch-1/replay-proof?redaction=sensitive",
            headers=_auth_and_tenant_headers(),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["bundle"]["signatures"] == [
        {
            "key_id": "k1",
            "algorithm": "hmac-sha256",
            "signed_digest": "sha256:" + "0" * 64,
        },
        {
            "key_id": "k2",
            "algorithm": "ed25519",
            "signed_digest": "sha256:" + "1" * 64,
        },
    ]
    assert payload["data"]["verification"]["signatures_present"] is True
