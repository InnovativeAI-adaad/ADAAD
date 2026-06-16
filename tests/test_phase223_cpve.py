# SPDX-License-Identifier: Apache-2.0
"""
tests/test_phase223_cpve.py
Phase 223 · INNOV-128 · CPVE — Constitutional Provenance Verification Engine
30-test acceptance suite · Must achieve 30/30 · Governor: DUSTIN L REID

Test categories:
  TRACE  — ProvenanceTracer chain and origin invariants  (T223-CPVE-01..07)
  VERIFY — ProvenanceVerifier digest and chain integrity  (T223-CPVE-08..13)
  GATE   — CPVE-GATE-0 promotion gating                  (T223-CPVE-14..16)
  CERT   — ProvenanceCertifier HUMAN-0 gating            (T223-CPVE-17..21)
  AUDIT  — ProvenanceAuditor chain and AUDIT-0            (T223-CPVE-22..26)
  API    — CPVERouter endpoint coverage                   (T223-CPVE-27..30)
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch, MagicMock

import pytest

from dorkllm.constitutional_provenance_verification_engine import (
    ARTIFACT_CLASSES,
    ArtifactClass,
    AuditEventKind,
    CPVEEngine,
    CPVEViolation,
    CertificationDenied,
    ChainIntegrityError,
    OrphanArtifactError,
    ProvenanceAuditor,
    ProvenanceCertifier,
    ProvenanceGateError,
    ProvenanceStatus,
    ProvenanceTracer,
    ProvenanceVerifier,
    ScopeViolation,
    VerificationResult,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_engine(tmp_path: Path) -> CPVEEngine:
    return CPVEEngine(
        ledger_path = tmp_path / "provenance.jsonl",
        audit_path  = tmp_path / "audit.jsonl",
        cert_path   = tmp_path / "certs.jsonl",
    )


def _trace_one(engine: CPVEEngine, suffix: str = "001") -> str:
    artifact_id = f"ART-{suffix}"
    engine.trace(
        artifact_id    = artifact_id,
        artifact_class = ArtifactClass.INVARIANT.value,
        origin_id      = f"ORIGIN-{suffix}",
        phase          = 223,
        innov_id       = "INNOV-128",
        payload        = {"text": f"test artifact {suffix}"},
    )
    return artifact_id


# ════════════════════════════════════════════════════════════════════════════
# TRACE — ProvenanceTracer (T223-CPVE-01..07)
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase223
def test_T223_CPVE_01_trace_emits_record(tmp_path):
    """T223-CPVE-01: trace() emits a ProvenanceRecord with expected fields."""
    engine = make_engine(tmp_path)
    record = engine.trace(
        artifact_id    = "ART-001",
        artifact_class = ArtifactClass.INVARIANT.value,
        origin_id      = "ORIGIN-001",
        phase          = 223,
        innov_id       = "INNOV-128",
        payload        = {"key": "value"},
    )
    assert record.artifact_id       == "ART-001"
    assert record.artifact_class    == ArtifactClass.INVARIANT.value
    assert record.origin_id         == "ORIGIN-001"
    assert record.phase             == 223
    assert record.innov_id          == "INNOV-128"
    assert record.status            == ProvenanceStatus.TRACED.value
    assert len(record.provenance_digest) == 64


@pytest.mark.phase223
def test_T223_CPVE_02_trace_chains_multiple_records(tmp_path):
    """T223-CPVE-02: consecutive traces produce linked HMAC chain."""
    engine = make_engine(tmp_path)
    r1 = engine.trace("ART-002a", ArtifactClass.MUTATION.value, "ORIGIN-002a", 223, "INNOV-128", {})
    r2 = engine.trace("ART-002b", ArtifactClass.MUTATION.value, "ORIGIN-002b", 223, "INNOV-128", {})
    assert r2.prev_digest == r1.provenance_digest
    assert r1.prev_digest == "GENESIS"


@pytest.mark.phase223
def test_T223_CPVE_03_trace_scope_violation_rejected(tmp_path):
    """T223-CPVE-03: CPVE-SCOPE-0 rejects unknown artifact class."""
    engine = make_engine(tmp_path)
    with pytest.raises(CPVEViolation, match="CPVE-SCOPE-0"):
        engine.trace("ART-003", "UNKNOWN_CLASS", "ORIGIN-003", 223, "INNOV-128", {})


@pytest.mark.phase223
def test_T223_CPVE_04_trace_orphan_rejected(tmp_path):
    """T223-CPVE-04: CPVE-ORIGIN-0 rejects empty origin_id."""
    engine = make_engine(tmp_path)
    with pytest.raises(CPVEViolation, match="CPVE-ORIGIN-0"):
        engine.trace("ART-004", ArtifactClass.INVARIANT.value, "", 223, "INNOV-128", {})


@pytest.mark.phase223
def test_T223_CPVE_05_trace_all_artifact_classes(tmp_path):
    """T223-CPVE-05: all five artifact classes trace successfully."""
    engine = make_engine(tmp_path)
    for cls in ARTIFACT_CLASSES:
        record = engine.trace(f"ART-{cls}", cls, f"ORIGIN-{cls}", 223, "INNOV-128", {})
        assert record.artifact_class == cls


@pytest.mark.phase223
def test_T223_CPVE_06_trace_persists_to_ledger(tmp_path):
    """T223-CPVE-06: traced records persist atomically to ledger file."""
    engine = make_engine(tmp_path)
    _trace_one(engine, "006")
    ledger = tmp_path / "provenance.jsonl"
    assert ledger.exists()
    records = [json.loads(l) for l in ledger.read_text().splitlines() if l.strip()]
    assert any(r["artifact_id"] == "ART-006" for r in records)


@pytest.mark.phase223
def test_T223_CPVE_07_trace_deterministic_payload_digest(tmp_path):
    """T223-CPVE-07: CPVE-DETERM-0 identical payload produces identical payload_digest."""
    payload = {"a": 1, "b": "hello"}
    e1 = make_engine(tmp_path / "e1")
    e2 = make_engine(tmp_path / "e2")
    r1 = e1.trace("ART-007", ArtifactClass.INVARIANT.value, "ORIG-007", 223, "INNOV-128", payload)
    r2 = e2.trace("ART-007", ArtifactClass.INVARIANT.value, "ORIG-007", 223, "INNOV-128", payload)
    assert r1.payload_digest == r2.payload_digest


# ════════════════════════════════════════════════════════════════════════════
# VERIFY — ProvenanceVerifier (T223-CPVE-08..13)
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase223
def test_T223_CPVE_08_verify_passes_for_valid_artifact(tmp_path):
    """T223-CPVE-08: verify() PASS for correctly traced artifact."""
    engine      = make_engine(tmp_path)
    artifact_id = _trace_one(engine, "008")
    report      = engine.verify(artifact_id)
    assert report.result      == VerificationResult.PASS.value
    assert report.chain_valid is True
    assert report.failures    == []


@pytest.mark.phase223
def test_T223_CPVE_09_verify_fails_for_unknown_artifact(tmp_path):
    """T223-CPVE-09: verify() FAIL for artifact not in ledger."""
    engine = make_engine(tmp_path)
    report = engine.verify("ART-NONEXISTENT")
    assert report.result      == VerificationResult.FAIL.value
    assert report.chain_valid is False
    assert "RECORD_NOT_FOUND" in report.failures


@pytest.mark.phase223
def test_T223_CPVE_10_verify_detects_digest_tamper(tmp_path):
    """T223-CPVE-10: tampered provenance_digest causes FAIL on verify."""
    engine      = make_engine(tmp_path)
    artifact_id = _trace_one(engine, "010")
    ledger      = tmp_path / "provenance.jsonl"
    lines       = ledger.read_text().splitlines()
    first       = json.loads(lines[0])
    first["provenance_digest"] = "0" * 64
    ledger.write_text(json.dumps(first) + "\n")
    # Reload engine
    engine2 = make_engine(tmp_path)
    report  = engine2.verify(artifact_id)
    assert report.result      == VerificationResult.FAIL.value
    assert report.chain_valid is False


@pytest.mark.phase223
def test_T223_CPVE_11_verify_full_chain_empty_passes(tmp_path):
    """T223-CPVE-11: verify_chain() PASS on empty ledger."""
    engine = make_engine(tmp_path)
    report = engine.verify_chain()
    assert report.result      == VerificationResult.PASS.value
    assert report.chain_valid is True
    assert report.link_count  == 0


@pytest.mark.phase223
def test_T223_CPVE_12_verify_full_chain_multi_records(tmp_path):
    """T223-CPVE-12: verify_chain() PASS after multiple traces."""
    engine = make_engine(tmp_path)
    for i in range(5):
        _trace_one(engine, f"012-{i}")
    report = engine.verify_chain()
    assert report.result      == VerificationResult.PASS.value
    assert report.link_count  == 5


@pytest.mark.phase223
def test_T223_CPVE_13_verify_full_chain_detects_break(tmp_path):
    """T223-CPVE-13: verify_chain() FAIL when chain link is broken."""
    engine = make_engine(tmp_path)
    _trace_one(engine, "013a")
    _trace_one(engine, "013b")
    ledger = tmp_path / "provenance.jsonl"
    lines  = ledger.read_text().splitlines()
    second = json.loads(lines[1])
    second["prev_digest"] = "0" * 64
    ledger.write_text("\n".join([lines[0], json.dumps(second)]) + "\n")
    engine2 = make_engine(tmp_path)
    report  = engine2.verify_chain()
    assert report.chain_valid is False
    assert any("CHAIN_BREAK" in f or "DIGEST_MISMATCH" in f for f in report.failures)


# ════════════════════════════════════════════════════════════════════════════
# GATE — CPVE-GATE-0 (T223-CPVE-14..16)
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase223
def test_T223_CPVE_14_gate_check_passes_for_valid(tmp_path):
    """T223-CPVE-14: gate_check() True for verified artifact."""
    engine      = make_engine(tmp_path)
    artifact_id = _trace_one(engine, "014")
    result      = engine.verifier.gate_check(artifact_id)
    assert result is True


@pytest.mark.phase223
def test_T223_CPVE_15_gate_check_raises_for_missing(tmp_path):
    """T223-CPVE-15: CPVE-GATE-0 raises ProvenanceGateError for unknown artifact."""
    engine = make_engine(tmp_path)
    with pytest.raises(ProvenanceGateError):
        engine.verifier.gate_check("ART-MISSING")


@pytest.mark.phase223
def test_T223_CPVE_16_gate_check_raises_for_tampered(tmp_path):
    """T223-CPVE-16: CPVE-GATE-0 raises ProvenanceGateError on tampered digest."""
    engine      = make_engine(tmp_path)
    artifact_id = _trace_one(engine, "016")
    ledger      = tmp_path / "provenance.jsonl"
    lines       = ledger.read_text().splitlines()
    rec         = json.loads(lines[0])
    rec["provenance_digest"] = "f" * 64
    ledger.write_text(json.dumps(rec) + "\n")
    engine2 = make_engine(tmp_path)
    with pytest.raises(ProvenanceGateError):
        engine2.verifier.gate_check(artifact_id)


# ════════════════════════════════════════════════════════════════════════════
# CERT — ProvenanceCertifier (T223-CPVE-17..21)
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase223
def test_T223_CPVE_17_certify_issues_certificate(tmp_path):
    """T223-CPVE-17: certify() issues a ProvenanceCertificate with all fields."""
    engine      = make_engine(tmp_path)
    artifact_id = _trace_one(engine, "017")
    cert        = engine.certify(artifact_id, human0_id="DUSTIN L REID")
    assert cert.artifact_id   == artifact_id
    assert cert.human0_id     == "DUSTIN L REID"
    assert cert.status        == "ISSUED"
    assert len(cert.cert_digest) == 64


@pytest.mark.phase223
def test_T223_CPVE_18_certify_rejected_without_human0(tmp_path):
    """T223-CPVE-18: CPVE-CERT-0 rejects certification with empty human0_id."""
    engine      = make_engine(tmp_path)
    artifact_id = _trace_one(engine, "018")
    with pytest.raises(CPVEViolation, match="CPVE-CERT-0"):
        engine.certify(artifact_id, human0_id="")


@pytest.mark.phase223
def test_T223_CPVE_19_certify_rejected_for_unknown_artifact(tmp_path):
    """T223-CPVE-19: CPVE-GATE-0 blocks certification for unknown artifact."""
    engine = make_engine(tmp_path)
    with pytest.raises(ProvenanceGateError):
        engine.certify("ART-UNKNOWN", human0_id="DUSTIN L REID")


@pytest.mark.phase223
def test_T223_CPVE_20_cert_chain_links(tmp_path):
    """T223-CPVE-20: consecutive certificates form an HMAC chain."""
    engine = make_engine(tmp_path)
    id1    = _trace_one(engine, "020a")
    id2    = _trace_one(engine, "020b")
    c1     = engine.certify(id1, "DUSTIN L REID")
    c2     = engine.certify(id2, "DUSTIN L REID")
    assert c2.cert_digest != c1.cert_digest
    # Verify certs persist
    certs = engine.certifier.load_certificates()
    assert len(certs) >= 2


@pytest.mark.phase223
def test_T223_CPVE_21_cert_retrievable_by_artifact(tmp_path):
    """T223-CPVE-21: issued certificate is retrievable by artifact_id."""
    engine      = make_engine(tmp_path)
    artifact_id = _trace_one(engine, "021")
    engine.certify(artifact_id, "DUSTIN L REID")
    cert = engine.certifier.get_certificate(artifact_id)
    assert cert is not None
    assert cert["artifact_id"] == artifact_id
    assert cert["status"]      == "ISSUED"


# ════════════════════════════════════════════════════════════════════════════
# AUDIT — ProvenanceAuditor (T223-CPVE-22..26)
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase223
def test_T223_CPVE_22_trace_emits_audit_entry(tmp_path):
    """T223-CPVE-22: CPVE-AUDIT-0 — trace() emits audit ledger entry."""
    engine = make_engine(tmp_path)
    _trace_one(engine, "022")
    entries = engine.auditor.load_entries()
    assert any(e["event_kind"] == AuditEventKind.TRACE.value for e in entries)


@pytest.mark.phase223
def test_T223_CPVE_23_verify_emits_audit_entry(tmp_path):
    """T223-CPVE-23: CPVE-AUDIT-0 — verify() emits audit ledger entry."""
    engine      = make_engine(tmp_path)
    artifact_id = _trace_one(engine, "023")
    engine.verify(artifact_id)
    entries = engine.auditor.load_entries()
    assert any(e["event_kind"] == AuditEventKind.VERIFY.value for e in entries)


@pytest.mark.phase223
def test_T223_CPVE_24_certify_emits_audit_entry(tmp_path):
    """T223-CPVE-24: CPVE-AUDIT-0 — certify() emits audit ledger entry."""
    engine      = make_engine(tmp_path)
    artifact_id = _trace_one(engine, "024")
    engine.certify(artifact_id, "DUSTIN L REID")
    entries = engine.auditor.load_entries()
    assert any(e["event_kind"] == AuditEventKind.CERTIFY.value for e in entries)


@pytest.mark.phase223
def test_T223_CPVE_25_audit_chain_valid_after_ops(tmp_path):
    """T223-CPVE-25: audit ledger chain remains valid after multiple operations."""
    engine      = make_engine(tmp_path)
    artifact_id = _trace_one(engine, "025")
    engine.verify(artifact_id)
    engine.certify(artifact_id, "DUSTIN L REID")
    result = engine.auditor.verify_audit_chain()
    assert result["valid"]       is True
    assert result["entry_count"] >= 3


@pytest.mark.phase223
def test_T223_CPVE_26_audit_chain_detects_tamper(tmp_path):
    """T223-CPVE-26: tampered audit entry causes chain verification to FAIL."""
    engine = make_engine(tmp_path)
    _trace_one(engine, "026")
    audit = tmp_path / "audit.jsonl"
    lines = audit.read_text().splitlines()
    first = json.loads(lines[0])
    first["audit_digest"] = "0" * 64
    audit.write_text(json.dumps(first) + "\n")
    engine2 = make_engine(tmp_path)
    result  = engine2.auditor.verify_audit_chain()
    assert result["valid"] is False


# ════════════════════════════════════════════════════════════════════════════
# API — CPVERouter endpoint coverage (T223-CPVE-27..30)
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase223
def test_T223_CPVE_27_router_trace_endpoint(tmp_path):
    """T223-CPVE-27: POST /cpve/trace returns TRACED status."""
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    import dorkllm.cpve_router as cpve_router_mod

    app    = FastAPI()
    engine = make_engine(tmp_path)
    cpve_router_mod._DEFAULT_ENGINE = engine
    app.include_router(cpve_router_mod.router)
    client = TestClient(app)

    resp = client.post("/cpve/trace", json={
        "artifact_id":    "ART-API-027",
        "artifact_class": "INVARIANT",
        "origin_id":      "ORIGIN-API-027",
        "phase":          223,
        "innov_id":       "INNOV-128",
        "payload":        {"test": True},
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"]      == "TRACED"
    assert data["artifact_id"] == "ART-API-027"
    cpve_router_mod._DEFAULT_ENGINE = None


@pytest.mark.phase223
def test_T223_CPVE_28_router_verify_endpoint(tmp_path):
    """T223-CPVE-28: GET /cpve/verify/{id} returns result field."""
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    import dorkllm.cpve_router as cpve_router_mod

    app    = FastAPI()
    engine = make_engine(tmp_path)
    engine.trace("ART-API-028", "MUTATION", "ORIG-028", 223, "INNOV-128", {})
    cpve_router_mod._DEFAULT_ENGINE = engine
    app.include_router(cpve_router_mod.router)
    client = TestClient(app)

    resp = client.get("/cpve/verify/ART-API-028")
    assert resp.status_code == 200
    assert resp.json()["result"] == VerificationResult.PASS.value
    cpve_router_mod._DEFAULT_ENGINE = None


@pytest.mark.phase223
def test_T223_CPVE_29_router_certify_requires_human0(tmp_path):
    """T223-CPVE-29: POST /cpve/certify returns 403 without human0_id."""
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    import dorkllm.cpve_router as cpve_router_mod

    app    = FastAPI()
    engine = make_engine(tmp_path)
    engine.trace("ART-API-029", "ATTESTATION", "ORIG-029", 223, "INNOV-128", {})
    cpve_router_mod._DEFAULT_ENGINE = engine
    app.include_router(cpve_router_mod.router)
    client = TestClient(app)

    resp = client.post("/cpve/certify", json={
        "artifact_id": "ART-API-029",
        "human0_id":   "",
    })
    assert resp.status_code == 403
    cpve_router_mod._DEFAULT_ENGINE = None


@pytest.mark.phase223
def test_T223_CPVE_30_router_status_endpoint(tmp_path):
    """T223-CPVE-30: GET /cpve/status returns cpve_version and governor."""
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    import dorkllm.cpve_router as cpve_router_mod

    app    = FastAPI()
    engine = make_engine(tmp_path)
    cpve_router_mod._DEFAULT_ENGINE = engine
    app.include_router(cpve_router_mod.router)
    client = TestClient(app)

    resp = client.get("/cpve/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["governor"]     == "DUSTIN L REID"
    assert data["cpve_version"] == "1.0.0"
    assert "artifact_classes"   in data
    cpve_router_mod._DEFAULT_ENGINE = None
