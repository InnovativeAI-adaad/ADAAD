# SPDX-License-Identifier: Apache-2.0
import base64
import hashlib
import hmac
import json
import time

import pytest
pytestmark = pytest.mark.regression_standard
from fastapi.testclient import TestClient

from runtime.governance.foundation import SeededDeterminismProvider
from runtime.mcp.server import create_app
from security import cryovant


def _jwt(secret: str, exp: int) -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).decode().rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    msg = f"{header}.{payload}".encode()
    sig = base64.urlsafe_b64encode(hmac.new(secret.encode(), msg, hashlib.sha256).digest()).decode().rstrip("=")
    return f"{header}.{payload}.{sig}"


def test_health_and_auth_and_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("ADAAD_MCP_JWT_SECRET", "secret")
    monkeypatch.setattr(cryovant, "KEYS_DIR", tmp_path)
    (tmp_path / "signing-key.pem").write_text("k", encoding="utf-8")
    app = create_app()
    client = TestClient(app)
    assert client.get("/health").status_code == 200
    assert client.post("/mutation/rank", json={"mutation_ids": ["x"]}).status_code == 401
    expired = _jwt("secret", int(time.time()) - 10)
    assert client.post("/mutation/rank", json={"mutation_ids": ["x"]}, headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    ok = _jwt("secret", int(time.time()) + 500)
    assert client.get("/missing", headers={"Authorization": f"Bearer {ok}"}).status_code == 404


def test_propose_contracts(tmp_path, monkeypatch):
    monkeypatch.setenv("ADAAD_MCP_JWT_SECRET", "secret")
    monkeypatch.setattr(cryovant, "KEYS_DIR", tmp_path)
    (tmp_path / "signing-key.pem").write_text("k", encoding="utf-8")
    client = TestClient(create_app())
    tok = _jwt("secret", int(time.time()) + 500)
    hdr = {"Authorization": f"Bearer {tok}"}
    monkeypatch.setattr("runtime.mcp.proposal_validator.evaluate_mutation", lambda *_args, **_kwargs: {"passed": True, "verdicts": []})
    payload = {
        "agent_id": "claude-proposal-agent",
        "generation_ts": "2026-01-01T00:00:00Z",
        "intent": "x",
        "ops": [{"op": "replace", "value": "safe"}],
        "targets": [{"agent_id": "a", "path": "app/foo.py", "target_type": "file", "ops": []}],
        "signature": "s",
        "nonce": "n",
        "authority_level": "auto-execute",
    }
    resp = client.post("/mutation/propose", json=payload, headers=hdr)
    assert resp.status_code == 200
    assert resp.json()["authority_level"] == "governor-review"

    payload["targets"] = [{"agent_id": "a", "path": "security/cryovant.py", "target_type": "file", "ops": []}]
    assert client.post("/mutation/propose", json=payload, headers=hdr).status_code == 403

    payload["targets"] = [{"agent_id": "a", "path": "app/foo.py", "target_type": "file", "ops": []}]
    monkeypatch.setattr(
        "runtime.mcp.proposal_validator.evaluate_mutation",
        lambda *_args, **_kwargs: {"passed": False, "verdicts": [{"severity": "blocking", "ok": False, "rule": "x"}]},
    )
    assert client.post("/mutation/propose", json=payload, headers=hdr).status_code == 422


def test_propose_contracts_deterministic_ids_in_strict_and_audit_modes(tmp_path, monkeypatch):
    monkeypatch.setenv("ADAAD_MCP_JWT_SECRET", "secret")
    monkeypatch.setattr(cryovant, "KEYS_DIR", tmp_path)
    (tmp_path / "signing-key.pem").write_text("k", encoding="utf-8")
    monkeypatch.setattr("runtime.mcp.proposal_validator.evaluate_mutation", lambda *_args, **_kwargs: {"passed": True, "verdicts": []})

    payload = {
        "agent_id": "claude-proposal-agent",
        "generation_ts": "2026-01-01T00:00:00Z",
        "intent": "x",
        "ops": [{"op": "replace", "value": "safe"}],
        "targets": [{"agent_id": "a", "path": "app/foo.py", "target_type": "file", "ops": []}],
        "signature": "s",
        "nonce": "n",
        "authority_level": "governor-review",
    }

    strict_provider = SeededDeterminismProvider("strict-seed")
    # Compute expected id BEFORE posting: the POST consumes the first next_id call.
    # Clone the provider at call-0 position to compute the expected value.
    strict_expected = SeededDeterminismProvider("strict-seed").next_id(label="mcp-proposal", length=32)
    strict_client = TestClient(create_app(provider=strict_provider, replay_mode="strict"))
    tok = _jwt("secret", int(time.time()) + 500)
    hdr = {"Authorization": f"Bearer {tok}"}
    strict_resp = strict_client.post("/mutation/propose", json=payload, headers=hdr)
    assert strict_resp.status_code == 200
    assert strict_resp.json()["proposal_id"] == strict_expected

    audit_provider = SeededDeterminismProvider("audit-seed")
    audit_expected = SeededDeterminismProvider("audit-seed").next_id(label="mcp-proposal", length=32)
    audit_client = TestClient(create_app(provider=audit_provider, recovery_tier="audit"))
    audit_resp = audit_client.post("/mutation/propose", json=payload, headers=hdr)
    assert audit_resp.status_code == 200
    assert audit_resp.json()["proposal_id"] == audit_expected


def test_propose_contracts_live_mode_ids_are_unique_and_hex(tmp_path, monkeypatch):
    monkeypatch.setenv("ADAAD_MCP_JWT_SECRET", "secret")
    monkeypatch.setattr(cryovant, "KEYS_DIR", tmp_path)
    (tmp_path / "signing-key.pem").write_text("k", encoding="utf-8")
    monkeypatch.setattr("runtime.mcp.proposal_validator.evaluate_mutation", lambda *_args, **_kwargs: {"passed": True, "verdicts": []})

    payload = {
        "agent_id": "claude-proposal-agent",
        "generation_ts": "2026-01-01T00:00:00Z",
        "intent": "x",
        "ops": [{"op": "replace", "value": "safe"}],
        "targets": [{"agent_id": "a", "path": "app/foo.py", "target_type": "file", "ops": []}],
        "signature": "s",
        "nonce": "n",
        "authority_level": "governor-review",
    }

    client = TestClient(create_app(replay_mode="off"))
    tok = _jwt("secret", int(time.time()) + 500)
    hdr = {"Authorization": f"Bearer {tok}"}

    first = client.post("/mutation/propose", json=payload, headers=hdr)
    second = client.post("/mutation/propose", json=payload, headers=hdr)
    assert first.status_code == 200
    assert second.status_code == 200
    first_id = first.json()["proposal_id"]
    second_id = second.json()["proposal_id"]
    assert first_id != second_id
    assert len(first_id) == 32
    assert len(second_id) == 32
    assert all(ch in "0123456789abcdef" for ch in first_id)
    assert all(ch in "0123456789abcdef" for ch in second_id)


def test_startup_refuses_when_signing_key_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("ADAAD_MCP_JWT_SECRET", "secret")
    monkeypatch.setattr(cryovant, "KEYS_DIR", tmp_path)
    app = create_app()
    with pytest.raises(RuntimeError):
        with TestClient(app):
            pass


def test_auth_failure_codes_for_malformed_tokens(tmp_path, monkeypatch):
    monkeypatch.setenv("ADAAD_MCP_JWT_SECRET", "super-secret")
    monkeypatch.setattr(cryovant, "KEYS_DIR", tmp_path)
    (tmp_path / "signing-key.pem").write_text("k", encoding="utf-8")
    client = TestClient(create_app())

    malformed = "abc.def"
    resp = client.post("/mutation/rank", json={"mutation_ids": ["x"]}, headers={"Authorization": f"Bearer {malformed}"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "invalid_jwt"
    assert "super-secret" not in resp.text

    bad_payload = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.invalid-json.signature"
    resp2 = client.post("/mutation/rank", json={"mutation_ids": ["x"]}, headers={"Authorization": f"Bearer {bad_payload}"})
    assert resp2.status_code == 401
    assert resp2.json()["detail"] == "invalid_jwt"


def test_cel_feed_health_uses_requested_phase(tmp_path, monkeypatch):
    monkeypatch.setenv("ADAAD_MCP_JWT_SECRET", "secret")
    monkeypatch.setattr(cryovant, "KEYS_DIR", tmp_path)
    (tmp_path / "signing-key.pem").write_text("k", encoding="utf-8")
    client = TestClient(create_app())
    called: dict[str, int] = {}

    def _fake_probe(phase: int = 148):
        called["phase"] = phase
        return {"ok": True, "phase": phase}

    monkeypatch.setattr("runtime.mcp.server.lef_probe", _fake_probe)

    resp = client.get("/events/cel-feed/health?phase=222")
    assert resp.status_code == 200
    assert called["phase"] == 222
    assert resp.json()["phase"] == 222


def test_pre_check_failed_fallback_on_unparseable_verdicts(tmp_path, monkeypatch):
    monkeypatch.setenv("ADAAD_MCP_JWT_SECRET", "secret")
    monkeypatch.setattr(cryovant, "KEYS_DIR", tmp_path)
    (tmp_path / "signing-key.pem").write_text("k", encoding="utf-8")
    client = TestClient(create_app())
    tok = _jwt("secret", int(time.time()) + 500)

    from runtime.mcp.proposal_validator import ProposalValidationError

    def _raise(*_args, **_kwargs):
        raise ProposalValidationError(code="pre_check_failed", detail="not-json", status_code=422)

    monkeypatch.setattr("runtime.mcp.server.validate_proposal", _raise)
    payload = {"agent_id": "a"}
    resp = client.post("/mutation/propose", json=payload, headers={"Authorization": f"Bearer {tok}"})
    assert resp.status_code == 422
    body = resp.json()["detail"]
    assert body["error"] == "pre_check_failed"
    assert "verdicts" not in body
