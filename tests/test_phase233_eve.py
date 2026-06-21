# SPDX-License-Identifier: Apache-2.0
"""
tests/test_phase233_eve.py
Phase 233 · INNOV-138 · EVE — External Verifiability Engine
30-test acceptance suite · T233-EVE-01 through T233-EVE-30
Author: DEVADAAD · InnovativeAI LLC · Governor: DUSTIN L REID
"""
from __future__ import annotations

import json
import time
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from dorkllm.external_verifiability_engine import (
    EVEEngine,
    EVEViolation,
    BundleDigestError,
    ChainBreakError,
    ImmutabilityViolation,
    ScopeViolation,
    PublicationGateError,
    VerificationFailure,
    ExportError,
    BundleStatus,
    CHIProof,
    ACICycleProof,
    InvariantRegisterProof,
    SPIEProof,
    AttestationLedger,
    AuditLog,
    VALID_PROOF_SOURCES,
)
from app.api.eve import router

# ── Test app ──────────────────────────────────────────────────────────────────
app = FastAPI()
app.include_router(router)
client = TestClient(app)

# ── Fixtures ──────────────────────────────────────────────────────────────────

def _chi() -> CHIProof:
    return CHIProof(
        epoch_id="test-epoch-001",
        chi_score=0.92,
        invariant_count=944,
        measurement_ts=1_700_000_000.0,
        source_module="CASL",
        chain_ref="hmac-sha256:abc123",
    )

def _aci() -> ACICycleProof:
    return ACICycleProof(
        cycle_id="cycle-001",
        outcome="PROMOTED",
        stages_completed=["CASL", "CADE", "CAPE"],
        cycle_started_at=1_700_000_000.0,
        cycle_closed_at=1_700_000_100.0,
        cacg_proof_digest="sha256:deadbeef",
    )

def _inv() -> InvariantRegisterProof:
    return InvariantRegisterProof(
        epoch_id="test-epoch-001",
        total_invariants=944,
        register_digest="sha256:cafebabe",
        snapshot_ts=1_700_000_000.0,
        version="10.43.0",
    )

def _spie() -> SPIEProof:
    return SPIEProof(
        proposal_id="spie:4f75db25a631a8fe",
        epoch_id="arc4-open-20260621",
        ratified_by="DUSTIN L. REID / HUMAN-0",
        proposal_digest="sha256:55712d7a08bc38172f0e214a9b3ad381c9cb3668df62f3c261bb6b7be6bbc261",
        chain_link="hmac-sha256:ab57e1621155366088e1937e0e08cafebabe",
    )

def _engine() -> EVEEngine:
    return EVEEngine(instance_id="test-eve-engine")


# ═══════════════════════════════════════════════════════════════════════════════
# T233-EVE-01 — EVE-BUNDLE-0: bundle_digest non-empty after seal
# ═══════════════════════════════════════════════════════════════════════════════
def test_T233_EVE_01_bundle_digest_non_empty():
    eng = _engine()
    b = eng.create_bundle("ep1", chi_proofs=[_chi()])
    eng.seal_bundle(b.bundle_id, "DUSTIN L REID", time.time())
    assert b.bundle_digest.startswith("sha256:")
    assert len(b.bundle_digest) > 10

# ═══════════════════════════════════════════════════════════════════════════════
# T233-EVE-02 — EVE-DETERM-0: identical inputs → identical digest
# ═══════════════════════════════════════════════════════════════════════════════
def test_T233_EVE_02_determ_digest():
    eng1 = EVEEngine(instance_id="determ-test")
    eng2 = EVEEngine(instance_id="determ-test")
    b1 = eng1.create_bundle("ep-determ", chi_proofs=[_chi()])
    b2 = eng2.create_bundle("ep-determ", chi_proofs=[_chi()])
    eng1.seal_bundle(b1.bundle_id, "DUSTIN L REID", 999.0)
    eng2.seal_bundle(b2.bundle_id, "DUSTIN L REID", 999.0)
    assert b1.bundle_digest == b2.bundle_digest

# ═══════════════════════════════════════════════════════════════════════════════
# T233-EVE-03 — EVE-CHAIN-0: ledger chain integrity after multiple appends
# ═══════════════════════════════════════════════════════════════════════════════
def test_T233_EVE_03_chain_integrity():
    eng = _engine()
    for i in range(3):
        b = eng.create_bundle(f"ep{i}", chi_proofs=[_chi()])
        eng.seal_bundle(b.bundle_id, "DUSTIN L REID", float(i))
    assert eng.verify_ledger_chain() is True

# ═══════════════════════════════════════════════════════════════════════════════
# T233-EVE-04 — EVE-APPEND-0: no deletion from ledger
# ═══════════════════════════════════════════════════════════════════════════════
def test_T233_EVE_04_ledger_append_only():
    eng = _engine()
    b = eng.create_bundle("ep-append", chi_proofs=[_chi()])
    eng.seal_bundle(b.bundle_id, "DUSTIN L REID", time.time())
    entries_before = len(eng.ledger_entries())
    assert entries_before >= 1
    # Ledger object has no delete method
    assert not hasattr(eng._engine if hasattr(eng, '_engine') else eng._ledger, 'delete')

# ═══════════════════════════════════════════════════════════════════════════════
# T233-EVE-05 — EVE-SCOPE-0: no proof_source raises ScopeViolation
# ═══════════════════════════════════════════════════════════════════════════════
def test_T233_EVE_05_scope_violation_no_proofs():
    eng = _engine()
    with pytest.raises(EVEViolation, match="EVE-SCOPE-0"):
        eng.create_bundle("ep-scope")

# ═══════════════════════════════════════════════════════════════════════════════
# T233-EVE-06 — EVE-SCOPE-0: valid proof sources set is correct
# ═══════════════════════════════════════════════════════════════════════════════
def test_T233_EVE_06_valid_proof_sources():
    assert "CHI" in VALID_PROOF_SOURCES
    assert "ACI_CYCLE" in VALID_PROOF_SOURCES
    assert "INVARIANT_REGISTER" in VALID_PROOF_SOURCES
    assert "SPIE" in VALID_PROOF_SOURCES
    assert len(VALID_PROOF_SOURCES) == 4

# ═══════════════════════════════════════════════════════════════════════════════
# T233-EVE-07 — EVE-HUMAN0-0: seal without identity raises violation
# ═══════════════════════════════════════════════════════════════════════════════
def test_T233_EVE_07_human0_seal_required():
    eng = _engine()
    b = eng.create_bundle("ep-h0", chi_proofs=[_chi()])
    with pytest.raises(EVEViolation, match="EVE-HUMAN0-0"):
        eng.seal_bundle(b.bundle_id, "", time.time())

# ═══════════════════════════════════════════════════════════════════════════════
# T233-EVE-08 — EVE-HUMAN0-0: publish without identity raises violation
# ═══════════════════════════════════════════════════════════════════════════════
def test_T233_EVE_08_human0_publish_required():
    eng = _engine()
    b = eng.create_bundle("ep-h0b", chi_proofs=[_chi()])
    eng.seal_bundle(b.bundle_id, "DUSTIN L REID", time.time())
    with pytest.raises(EVEViolation, match="EVE-HUMAN0-0"):
        eng.publish_bundle(b.bundle_id, "", time.time())

# ═══════════════════════════════════════════════════════════════════════════════
# T233-EVE-09 — EVE-VERIFY-0: verify_bundle PASS on valid sealed bundle
# ═══════════════════════════════════════════════════════════════════════════════
def test_T233_EVE_09_verify_pass():
    eng = _engine()
    b = eng.create_bundle("ep-verify", chi_proofs=[_chi()])
    eng.seal_bundle(b.bundle_id, "DUSTIN L REID", time.time())
    result = eng.verify_bundle(b.bundle_id)
    assert result["verification"] == "PASS"
    assert result["declared_digest"] == result["recomputed_digest"]

# ═══════════════════════════════════════════════════════════════════════════════
# T233-EVE-10 — EVE-VERIFY-0: tampered digest raises VerificationFailure
# ═══════════════════════════════════════════════════════════════════════════════
def test_T233_EVE_10_verify_fail_on_tamper():
    eng = _engine()
    b = eng.create_bundle("ep-tamper", chi_proofs=[_chi()])
    eng.seal_bundle(b.bundle_id, "DUSTIN L REID", time.time())
    # Force tamper by direct object mutation bypass
    object.__setattr__(b, "_sealed", False)
    object.__setattr__(b, "bundle_digest", "sha256:tampered000000")
    object.__setattr__(b, "_sealed", True)
    with pytest.raises(VerificationFailure, match="EVE-VERIFY-0"):
        eng.verify_bundle(b.bundle_id)

# ═══════════════════════════════════════════════════════════════════════════════
# T233-EVE-11 — EVE-IMMUT-0: field mutation after seal raises ImmutabilityViolation
# ═══════════════════════════════════════════════════════════════════════════════
def test_T233_EVE_11_immutability_after_seal():
    eng = _engine()
    b = eng.create_bundle("ep-immut", chi_proofs=[_chi()])
    eng.seal_bundle(b.bundle_id, "DUSTIN L REID", time.time())
    with pytest.raises(ImmutabilityViolation, match="EVE-IMMUT-0"):
        b.epoch_id = "hacked"

# ═══════════════════════════════════════════════════════════════════════════════
# T233-EVE-12 — EVE-EXTERN-0: export contains no private HMAC secret
# ═══════════════════════════════════════════════════════════════════════════════
def test_T233_EVE_12_export_no_private_secret():
    eng = _engine()
    b = eng.create_bundle("ep-export", chi_proofs=[_chi()])
    eng.seal_bundle(b.bundle_id, "DUSTIN L REID", time.time())
    export = eng.export_bundle(b.bundle_id)
    export_str = json.dumps(export)
    assert "eve-hmac-secret-DUSTIN" not in export_str

# ═══════════════════════════════════════════════════════════════════════════════
# T233-EVE-13 — EVE-EXTERN-0: export contains public key name + verify instructions
# ═══════════════════════════════════════════════════════════════════════════════
def test_T233_EVE_13_export_public_key_and_instructions():
    eng = _engine()
    b = eng.create_bundle("ep-export2", chi_proofs=[_chi()])
    eng.seal_bundle(b.bundle_id, "DUSTIN L REID", time.time())
    export = eng.export_bundle(b.bundle_id)
    assert "_public_hmac_key_name" in export
    assert "_verification_instructions" in export
    assert "bundle_digest" in export

# ═══════════════════════════════════════════════════════════════════════════════
# T233-EVE-14 — EVE-AUDIT-0: every operation recorded in audit log
# ═══════════════════════════════════════════════════════════════════════════════
def test_T233_EVE_14_audit_log_populated():
    eng = _engine()
    b = eng.create_bundle("ep-audit", chi_proofs=[_chi()])
    eng.seal_bundle(b.bundle_id, "DUSTIN L REID", time.time())
    eng.verify_bundle(b.bundle_id)
    records = eng.audit_records()
    ops = [r["operation"] for r in records]
    assert "create_bundle" in ops
    assert "seal_bundle" in ops
    assert "verify_bundle" in ops

# ═══════════════════════════════════════════════════════════════════════════════
# T233-EVE-15 — Multi-proof-type bundle: all 4 sources
# ═══════════════════════════════════════════════════════════════════════════════
def test_T233_EVE_15_all_four_proof_sources():
    eng = _engine()
    b = eng.create_bundle(
        "ep-multi",
        chi_proofs=[_chi()],
        aci_cycle_proofs=[_aci()],
        invariant_register_proofs=[_inv()],
        spie_proofs=[_spie()],
    )
    assert set(b.proof_sources) == {"CHI", "ACI_CYCLE", "INVARIANT_REGISTER", "SPIE"}
    eng.seal_bundle(b.bundle_id, "DUSTIN L REID", time.time())
    result = eng.verify_bundle(b.bundle_id)
    assert result["verification"] == "PASS"

# ═══════════════════════════════════════════════════════════════════════════════
# T233-EVE-16 — CHIProof canonical JSON deterministic
# ═══════════════════════════════════════════════════════════════════════════════
def test_T233_EVE_16_chi_proof_canonical_deterministic():
    p = _chi()
    assert p.canonical() == p.canonical()
    assert "CHI" in p.canonical()
    assert "944" in p.canonical()

# ═══════════════════════════════════════════════════════════════════════════════
# T233-EVE-17 — ACICycleProof canonical JSON deterministic
# ═══════════════════════════════════════════════════════════════════════════════
def test_T233_EVE_17_aci_proof_canonical_deterministic():
    p = _aci()
    assert p.canonical() == p.canonical()
    assert "PROMOTED" in p.canonical()

# ═══════════════════════════════════════════════════════════════════════════════
# T233-EVE-18 — InvariantRegisterProof canonical JSON
# ═══════════════════════════════════════════════════════════════════════════════
def test_T233_EVE_18_inv_proof_canonical():
    p = _inv()
    assert "944" in p.canonical()
    assert "10.43.0" in p.canonical()

# ═══════════════════════════════════════════════════════════════════════════════
# T233-EVE-19 — SPIEProof canonical JSON contains ratification
# ═══════════════════════════════════════════════════════════════════════════════
def test_T233_EVE_19_spie_proof_canonical():
    p = _spie()
    canon = p.canonical()
    assert "DUSTIN L. REID" in canon
    assert "spie:4f75db25a631a8fe" in canon

# ═══════════════════════════════════════════════════════════════════════════════
# T233-EVE-20 — publish lifecycle: DRAFT → SEALED → PUBLISHED
# ═══════════════════════════════════════════════════════════════════════════════
def test_T233_EVE_20_full_lifecycle():
    eng = _engine()
    b = eng.create_bundle("ep-lifecycle", chi_proofs=[_chi()])
    assert b.status == BundleStatus.DRAFT
    eng.seal_bundle(b.bundle_id, "DUSTIN L REID", time.time())
    assert b.status == BundleStatus.SEALED
    eng.publish_bundle(b.bundle_id, "DUSTIN L REID", time.time())
    assert b.status == BundleStatus.PUBLISHED
    assert b.published_by == "DUSTIN L REID"

# ═══════════════════════════════════════════════════════════════════════════════
# T233-EVE-21 — publish DRAFT (not sealed) raises PublicationGateError
# ═══════════════════════════════════════════════════════════════════════════════
def test_T233_EVE_21_publish_draft_raises():
    eng = _engine()
    b = eng.create_bundle("ep-pub-draft", chi_proofs=[_chi()])
    with pytest.raises(PublicationGateError):
        eng.publish_bundle(b.bundle_id, "DUSTIN L REID", time.time())

# ═══════════════════════════════════════════════════════════════════════════════
# T233-EVE-22 — unknown bundle_id raises KeyError
# ═══════════════════════════════════════════════════════════════════════════════
def test_T233_EVE_22_unknown_bundle_id():
    eng = _engine()
    with pytest.raises(KeyError):
        eng.seal_bundle("eve-bundle:nonexistent", "DUSTIN L REID", time.time())

# ═══════════════════════════════════════════════════════════════════════════════
# T233-EVE-23 — AttestationLedger chain verification
# ═══════════════════════════════════════════════════════════════════════════════
def test_T233_EVE_23_ledger_chain_verify():
    eng = _engine()
    for i in range(5):
        b = eng.create_bundle(f"ep-chain{i}", chi_proofs=[_chi()])
        eng.seal_bundle(b.bundle_id, "DUSTIN L REID", float(i * 100))
    assert eng.verify_ledger_chain() is True
    entries = eng.ledger_entries()
    assert len(entries) >= 5

# ═══════════════════════════════════════════════════════════════════════════════
# T233-EVE-24 — engine status reports correct counts
# ═══════════════════════════════════════════════════════════════════════════════
def test_T233_EVE_24_engine_status():
    eng = _engine()
    b1 = eng.create_bundle("ep-s1", chi_proofs=[_chi()])
    eng.seal_bundle(b1.bundle_id, "DUSTIN L REID", time.time())
    eng.publish_bundle(b1.bundle_id, "DUSTIN L REID", time.time())
    b2 = eng.create_bundle("ep-s2", aci_cycle_proofs=[_aci()])
    status = eng.status()
    assert status["bundle_count"] == 2
    assert status["published_bundles"] == 1
    assert status["chain_integrity"] is True

# ═══════════════════════════════════════════════════════════════════════════════
# T233-EVE-25 — API: GET /eve/status returns 200
# ═══════════════════════════════════════════════════════════════════════════════
def test_T233_EVE_25_api_status():
    r = client.get("/eve/status")
    assert r.status_code == 200
    assert "eve_version" in r.json()
    assert "chain_integrity" in r.json()

# ═══════════════════════════════════════════════════════════════════════════════
# T233-EVE-26 — API: POST /eve/bundles creates bundle
# ═══════════════════════════════════════════════════════════════════════════════
def test_T233_EVE_26_api_create_bundle():
    r = client.post("/eve/bundles", json={
        "epoch_id": "api-test-001",
        "chi_proofs": [{
            "epoch_id": "api-test-001",
            "chi_score": 0.91,
            "invariant_count": 944,
            "measurement_ts": 1700000000.0,
            "source_module": "CASL",
            "chain_ref": "hmac-sha256:test",
        }]
    })
    assert r.status_code == 201
    data = r.json()
    assert "bundle_id" in data
    assert data["status"] == "DRAFT"
    assert "CHI" in data["proof_sources"]

# ═══════════════════════════════════════════════════════════════════════════════
# T233-EVE-27 — API: POST /eve/bundles/{id}/seal seals bundle
# ═══════════════════════════════════════════════════════════════════════════════
def test_T233_EVE_27_api_seal_bundle():
    r_create = client.post("/eve/bundles", json={
        "epoch_id": "api-seal-001",
        "invariant_register_proofs": [{
            "epoch_id": "api-seal-001",
            "total_invariants": 944,
            "register_digest": "sha256:cafebabe",
            "snapshot_ts": 1700000000.0,
            "version": "10.43.0",
        }]
    })
    bundle_id = r_create.json()["bundle_id"]
    r_seal = client.post(f"/eve/bundles/{bundle_id}/seal",
                         json={"human0_identity": "DUSTIN L REID"})
    assert r_seal.status_code == 200
    data = r_seal.json()
    assert data["status"] == "SEALED"
    assert data["bundle_digest"].startswith("sha256:")

# ═══════════════════════════════════════════════════════════════════════════════
# T233-EVE-28 — API: GET /eve/bundles/{id}/verify returns PASS
# ═══════════════════════════════════════════════════════════════════════════════
def test_T233_EVE_28_api_verify():
    r_create = client.post("/eve/bundles", json={
        "epoch_id": "api-verify-001",
        "spie_proofs": [{
            "proposal_id": "spie:4f75db25a631a8fe",
            "epoch_id": "arc4-open-20260621",
            "ratified_by": "DUSTIN L. REID / HUMAN-0",
            "proposal_digest": "sha256:abc123",
            "chain_link": "hmac-sha256:def456",
        }]
    })
    bundle_id = r_create.json()["bundle_id"]
    client.post(f"/eve/bundles/{bundle_id}/seal",
                json={"human0_identity": "DUSTIN L REID"})
    r_verify = client.get(f"/eve/bundles/{bundle_id}/verify")
    assert r_verify.status_code == 200
    assert r_verify.json()["verification"] == "PASS"

# ═══════════════════════════════════════════════════════════════════════════════
# T233-EVE-29 — API: GET /eve/bundles/{id}/export — no private secret
# ═══════════════════════════════════════════════════════════════════════════════
def test_T233_EVE_29_api_export_no_secret():
    r_create = client.post("/eve/bundles", json={
        "epoch_id": "api-export-001",
        "aci_cycle_proofs": [{
            "cycle_id": "cycle-api-001",
            "outcome": "PROMOTED",
            "stages_completed": ["CASL", "CADE"],
            "cycle_started_at": 1700000000.0,
            "cycle_closed_at": 1700000100.0,
            "cacg_proof_digest": "sha256:deadbeef",
        }]
    })
    bundle_id = r_create.json()["bundle_id"]
    client.post(f"/eve/bundles/{bundle_id}/seal",
                json={"human0_identity": "DUSTIN L REID"})
    r_export = client.get(f"/eve/bundles/{bundle_id}/export")
    assert r_export.status_code == 200
    export_str = json.dumps(r_export.json())
    assert "eve-hmac-secret-DUSTIN" not in export_str
    assert "_verification_instructions" in r_export.json()

# ═══════════════════════════════════════════════════════════════════════════════
# T233-EVE-30 — API: GET /eve/ledger chain_integrity True
# ═══════════════════════════════════════════════════════════════════════════════
def test_T233_EVE_30_api_ledger_chain_integrity():
    r = client.get("/eve/ledger")
    assert r.status_code == 200
    assert r.json()["chain_integrity"] is True
