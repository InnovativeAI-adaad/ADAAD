# SPDX-License-Identifier: Apache-2.0
# INNOV-124 · CARE — Constitutional Amendment Ratification Engine
# Phase 219 Test Suite · v10.30.0 · Governor: DUSTIN L REID
"""
30-test acceptance suite for CARE — Constitutional Amendment Ratification Engine.
Tests cover all 10 hard-class invariants, happy-path promotion, diff engine,
certificate emission, rollback, chain verification, and API router.

Invariants under test:
  CARE-INTAKE-0    CARE-ATOMIC-0    CARE-HMAC-0      CARE-HASH-0
  CARE-ROLLBACK-0  CARE-TOMBSTONE-0 CARE-CERT-0      CARE-HUMAN0-0
  CARE-REPLAY-0    CARE-AUDIT-0
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.phase219

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_care_dirs(tmp_path):
    """Isolated CARE directories for each test."""
    return {
        "ledger": tmp_path / "ledger" / "care_ratification_ledger.jsonl",
        "registry": tmp_path / "data" / "care" / "invariant_registry.json",
        "cert_dir": tmp_path / "data" / "care" / "certificates",
        "rollback_dir": tmp_path / "data" / "care" / "rollbacks",
    }


@pytest.fixture
def engine(tmp_care_dirs):
    """Fresh CARE engine with isolated paths."""
    from dorkllm.constitutional_amendment_ratification_engine import (
        ConstitutionalAmendmentRatificationEngine,
    )
    return ConstitutionalAmendmentRatificationEngine(
        ledger_path=tmp_care_dirs["ledger"],
        registry_path=tmp_care_dirs["registry"],
        cert_dir=tmp_care_dirs["cert_dir"],
        rollback_dir=tmp_care_dirs["rollback_dir"],
    )


@pytest.fixture
def valid_payload():
    """Valid minimal RatificationPayload for happy-path tests."""
    from dorkllm.constitutional_amendment_ratification_engine import RatificationPayload
    return RatificationPayload(
        wire_id=str(uuid.uuid4()),
        amendment_id=str(uuid.uuid4()),
        title="Strengthen CEL gate validation",
        amendment_class="SOFT",
        human0_ratification_ts="2026-06-10T12:00:00Z",
        human0_ratification_ref="GPG:5C85F8737C93DC0F1E639F9CDD5C7176E87C213E",
        proposed_by="DEVADAAD",
        diff_entries=[
            {"action": "ADD", "invariant_id": "TEST-NEW-0", "new_text": "New invariant text"},
            {"action": "STABLE", "invariant_id": "CEL-GATE-0"},
        ],
        supporting_invariant_ids=["CEL-GATE-0", "ACSA-CHAIN-0", "CGVF-AUDIT-0"],
        revert_hash="abc123",
        content_hash="def456",
    )


@pytest.fixture
def client(tmp_care_dirs, monkeypatch):
    """FastAPI test client with CARE router wired and isolated engine."""
    from dorkllm.constitutional_amendment_ratification_engine import (
        ConstitutionalAmendmentRatificationEngine,
    )
    import app.api.care as care_module
    isolated_engine = ConstitutionalAmendmentRatificationEngine(
        ledger_path=tmp_care_dirs["ledger"],
        registry_path=tmp_care_dirs["registry"],
        cert_dir=tmp_care_dirs["cert_dir"],
        rollback_dir=tmp_care_dirs["rollback_dir"],
    )
    monkeypatch.setattr(care_module, "_engine", isolated_engine)
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(care_module.router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# T219-CARE-01 — Module imports and constants
# ---------------------------------------------------------------------------
def test_care_module_imports():
    from dorkllm.constitutional_amendment_ratification_engine import (
        ConstitutionalAmendmentRatificationEngine,
        GOVERNOR, INNOV, VERSION, MODULE,
        HARD_CLASS_INVARIANTS,
    )
    assert GOVERNOR == "DUSTIN L REID"
    assert INNOV == "INNOV-124"
    assert VERSION == "10.30.0"
    assert MODULE == "CARE"
    assert len(HARD_CLASS_INVARIANTS) == 10


# T219-CARE-02 — All 10 invariant IDs present
def test_care_all_invariant_ids_present():
    from dorkllm.constitutional_amendment_ratification_engine import HARD_CLASS_INVARIANTS
    required = {
        "CARE-INTAKE-0", "CARE-ATOMIC-0", "CARE-HMAC-0", "CARE-HASH-0",
        "CARE-ROLLBACK-0", "CARE-TOMBSTONE-0", "CARE-CERT-0",
        "CARE-HUMAN0-0", "CARE-REPLAY-0", "CARE-AUDIT-0",
    }
    assert required == HARD_CLASS_INVARIANTS


# T219-CARE-03 — Happy-path promote() succeeds
def test_care_promote_happy_path(engine, valid_payload):
    result = engine.promote(valid_payload)
    assert result["stage"] == "CERTIFIED"
    assert result["wire_id"] == valid_payload.wire_id
    assert result["diff_count"] == 2
    assert result["execution_id"]
    assert result["certificate_id"]


# T219-CARE-04 — Pre/post registry hashes populated (CARE-HASH-0)
def test_care_hash_pre_post_recorded(engine, valid_payload):
    result = engine.promote(valid_payload)
    assert result["pre_registry_hash"]
    assert result["post_registry_hash"]
    assert len(result["pre_registry_hash"]) == 64
    assert len(result["post_registry_hash"]) == 64


# T219-CARE-05 — CARE-INTAKE-0: empty wire_id rejected
def test_care_intake_empty_wire_id(engine, valid_payload):
    from dorkllm.constitutional_amendment_ratification_engine import CAREIntakeError
    valid_payload.wire_id = ""
    with pytest.raises(CAREIntakeError):
        engine.promote(valid_payload)


# T219-CARE-06 — CARE-INTAKE-0: empty amendment_id rejected
def test_care_intake_empty_amendment_id(engine, valid_payload):
    from dorkllm.constitutional_amendment_ratification_engine import CAREIntakeError
    valid_payload.amendment_id = ""
    with pytest.raises(CAREIntakeError):
        engine.promote(valid_payload)


# T219-CARE-07 — CARE-INTAKE-0: empty diff_entries rejected
def test_care_intake_empty_diff_entries(engine, valid_payload):
    from dorkllm.constitutional_amendment_ratification_engine import CAREIntakeError
    valid_payload.diff_entries = []
    with pytest.raises(CAREIntakeError):
        engine.promote(valid_payload)


# T219-CARE-08 — CARE-HUMAN0-0: missing ratification timestamp rejected
def test_care_human0_missing_ts(engine, valid_payload):
    from dorkllm.constitutional_amendment_ratification_engine import CAREHuman0Error
    valid_payload.human0_ratification_ts = ""
    with pytest.raises(CAREHuman0Error):
        engine.promote(valid_payload)


# T219-CARE-09 — CARE-HUMAN0-0: missing ratification ref rejected
def test_care_human0_missing_ref(engine, valid_payload):
    from dorkllm.constitutional_amendment_ratification_engine import CAREHuman0Error
    valid_payload.human0_ratification_ref = ""
    with pytest.raises(CAREHuman0Error):
        engine.promote(valid_payload)


# T219-CARE-10 — CARE-REPLAY-0: duplicate execution_id rejected
def test_care_replay_duplicate_execution_id(engine, valid_payload):
    from dorkllm.constitutional_amendment_ratification_engine import (
        CAREReplayError, RatificationPayload,
    )
    result = engine.promote(valid_payload)
    execution_id = result["execution_id"]
    # Inject same ID into seen set
    engine._seen_execution_ids.add(execution_id)
    payload2 = RatificationPayload(
        wire_id=str(uuid.uuid4()),
        amendment_id=str(uuid.uuid4()),
        title="Second attempt",
        amendment_class="SOFT",
        human0_ratification_ts="2026-06-10T13:00:00Z",
        human0_ratification_ref="GPG:5C85F8737C93DC0F1E639F9CDD5C7176E87C213E",
        proposed_by="DEVADAAD",
        diff_entries=[{"action": "STABLE", "invariant_id": "CEL-GATE-0"}],
        supporting_invariant_ids=[],
        revert_hash="",
        content_hash="",
    )
    # Force same execution_id
    from dorkllm import constitutional_amendment_ratification_engine as m
    orig = m.PromotionRecord.__init__

    import functools
    call_count = {"n": 0}
    real_init = m.PromotionRecord.__init__

    def patched_init(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        if call_count["n"] == 0:
            self.execution_id = execution_id
        call_count["n"] += 1

    m.PromotionRecord.__init__ = patched_init
    try:
        with pytest.raises(CAREReplayError):
            engine.promote(payload2)
    finally:
        m.PromotionRecord.__init__ = real_init


# T219-CARE-11 — CARE-ATOMIC-0: registry written atomically
def test_care_atomic_registry_write(engine, valid_payload, tmp_care_dirs):
    engine.promote(valid_payload)
    reg_path = tmp_care_dirs["registry"]
    assert reg_path.exists()
    # Should be valid JSON (not corrupt)
    data = json.loads(reg_path.read_text())
    assert "invariants" in data


# T219-CARE-12 — CARE-HMAC-0: ledger appended after promotion
def test_care_hmac_ledger_appended(engine, valid_payload, tmp_care_dirs):
    engine.promote(valid_payload)
    ledger = tmp_care_dirs["ledger"]
    assert ledger.exists()
    lines = [l for l in ledger.read_text().splitlines() if l.strip()]
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["event"] == "PROMOTED"
    assert "digest" in entry
    assert "prev_digest" in entry


# T219-CARE-13 — CARE-HMAC-0: chain valid after single promotion
def test_care_hmac_chain_valid_after_promote(engine, valid_payload):
    engine.promote(valid_payload)
    result = engine.verify_chain()
    assert result["chain_valid"] is True


# T219-CARE-14 — CARE-HMAC-0: chain valid after multiple promotions
def test_care_hmac_chain_valid_multiple(engine, tmp_care_dirs):
    from dorkllm.constitutional_amendment_ratification_engine import RatificationPayload
    for i in range(3):
        p = RatificationPayload(
            wire_id=str(uuid.uuid4()),
            amendment_id=str(uuid.uuid4()),
            title=f"Amendment {i}",
            amendment_class="SOFT",
            human0_ratification_ts="2026-06-10T12:00:00Z",
            human0_ratification_ref="GPG:5C85F8737C93DC0F1E639F9CDD5C7176E87C213E",
            proposed_by="DEVADAAD",
            diff_entries=[{"action": "STABLE", "invariant_id": f"INV-{i}-0"}],
            supporting_invariant_ids=[],
            revert_hash="", content_hash="",
        )
        engine.promote(p)
    result = engine.verify_chain()
    assert result["chain_valid"] is True
    assert result["entry_count"] == 3


# T219-CARE-15 — CARE-CERT-0: certificate emitted and persisted
def test_care_cert_emitted(engine, valid_payload, tmp_care_dirs):
    result = engine.promote(valid_payload)
    cert_dir = tmp_care_dirs["cert_dir"]
    certs = list(cert_dir.glob("*.json"))
    assert len(certs) == 1
    cert_data = json.loads(certs[0].read_text())
    assert cert_data["wire_id"] == valid_payload.wire_id
    assert cert_data["hmac_signature"]
    assert cert_data["certificate_id"] == result["certificate_id"]


# T219-CARE-16 — CARE-CERT-0: certificate HMAC signature non-empty
def test_care_cert_hmac_signature_non_empty(engine, valid_payload, tmp_care_dirs):
    engine.promote(valid_payload)
    certs = list(tmp_care_dirs["cert_dir"].glob("*.json"))
    cert = json.loads(certs[0].read_text())
    assert len(cert["hmac_signature"]) == 64


# T219-CARE-17 — CARE-TOMBSTONE-0: tombstoned invariant moved not deleted
def test_care_tombstone_invariant_preserved(engine, tmp_care_dirs):
    from dorkllm.constitutional_amendment_ratification_engine import RatificationPayload
    # First: ADD an invariant
    p1 = RatificationPayload(
        wire_id=str(uuid.uuid4()),
        amendment_id=str(uuid.uuid4()),
        title="Add tombstone test invariant",
        amendment_class="SOFT",
        human0_ratification_ts="2026-06-10T12:00:00Z",
        human0_ratification_ref="GPG:TEST",
        proposed_by="DEVADAAD",
        diff_entries=[{"action": "ADD", "invariant_id": "TOMB-TEST-0", "new_text": "To be tombstoned"}],
        supporting_invariant_ids=[], revert_hash="", content_hash="",
    )
    engine.promote(p1)

    # Then: TOMBSTONE the same invariant
    p2 = RatificationPayload(
        wire_id=str(uuid.uuid4()),
        amendment_id=str(uuid.uuid4()),
        title="Tombstone test invariant",
        amendment_class="SOFT",
        human0_ratification_ts="2026-06-10T12:30:00Z",
        human0_ratification_ref="GPG:TEST",
        proposed_by="DEVADAAD",
        diff_entries=[{
            "action": "TOMBSTONE",
            "invariant_id": "TOMB-TEST-0",
            "tombstone_reason": "superseded by TOMB-TEST-1",
            "successor_id": "TOMB-TEST-1",
        }],
        supporting_invariant_ids=[], revert_hash="", content_hash="",
    )
    engine.promote(p2)

    reg = json.loads(tmp_care_dirs["registry"].read_text())
    # CARE-TOMBSTONE-0: not in active invariants
    assert "TOMB-TEST-0" not in reg["invariants"]
    # CARE-TOMBSTONE-0: present in tombstones
    assert "TOMB-TEST-0" in reg["tombstones"]
    tomb = reg["tombstones"]["TOMB-TEST-0"]
    assert tomb["tombstone_reason"] == "superseded by TOMB-TEST-1"
    assert tomb["successor_id"] == "TOMB-TEST-1"
    assert "tombstoned_at_utc" in tomb


# T219-CARE-18 — CARE-ROLLBACK-0: failed promotion writes rollback manifest
def test_care_rollback_manifest_on_failure(engine, valid_payload, tmp_care_dirs):
    from dorkllm.constitutional_amendment_ratification_engine import CAREIntakeError
    valid_payload.wire_id = "  "  # CARE-INTAKE-0 violation
    with pytest.raises(CAREIntakeError):
        engine.promote(valid_payload)
    rollbacks = list(tmp_care_dirs["rollback_dir"].glob("*.json"))
    assert len(rollbacks) == 1
    manifest = json.loads(rollbacks[0].read_text())
    assert manifest["schema"] == "care-rollback-v1"
    assert "error" in manifest
    assert "rollback_instruction" in manifest


# T219-CARE-19 — CARE-AUDIT-0: failed promotion still appends to ledger
def test_care_audit_failed_appends_ledger(engine, valid_payload, tmp_care_dirs):
    from dorkllm.constitutional_amendment_ratification_engine import CAREHuman0Error
    valid_payload.human0_ratification_ts = ""
    with pytest.raises(CAREHuman0Error):
        engine.promote(valid_payload)
    ledger = tmp_care_dirs["ledger"]
    assert ledger.exists()
    lines = [l for l in ledger.read_text().splitlines() if l.strip()]
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["event"] == "FAILED"


# T219-CARE-20 — CARE-REPLAY-0: full execution is replayable from ledger
def test_care_replay_from_ledger(engine, valid_payload, tmp_care_dirs):
    result = engine.promote(valid_payload)
    ledger_lines = [
        l for l in tmp_care_dirs["ledger"].read_text().splitlines() if l.strip()
    ]
    entry = json.loads(ledger_lines[0])
    assert entry["execution_id"] == result["execution_id"]
    assert entry["wire_id"] == valid_payload.wire_id
    assert entry["pre_registry_hash"] == result["pre_registry_hash"]
    assert entry["post_registry_hash"] == result["post_registry_hash"]
    assert entry["governor"] == "DUSTIN L REID"


# T219-CARE-21 — get_status() returns NOT_FOUND for unknown wire_id
def test_care_get_status_not_found(engine):
    result = engine.get_status("non-existent-wire-id")
    assert result["status"] == "NOT_FOUND"


# T219-CARE-22 — get_status() returns PROMOTED for known wire_id
def test_care_get_status_promoted(engine, valid_payload):
    engine.promote(valid_payload)
    result = engine.get_status(valid_payload.wire_id)
    assert result["status"] == "PROMOTED"
    assert result["wire_id"] == valid_payload.wire_id
    assert result["ledger_entries"] == 1


# T219-CARE-23 — get_certificate() returns cert for known wire_id
def test_care_get_certificate(engine, valid_payload):
    engine.promote(valid_payload)
    cert = engine.get_certificate(valid_payload.wire_id)
    assert cert is not None
    assert cert["wire_id"] == valid_payload.wire_id
    assert cert["hmac_signature"]


# T219-CARE-24 — get_certificate() returns None for unknown wire_id
def test_care_get_certificate_not_found(engine):
    assert engine.get_certificate("unknown-wire-id") is None


# T219-CARE-25 — registry_diff() returns diff data after promotion
def test_care_registry_diff_after_promote(engine, valid_payload):
    engine.promote(valid_payload)
    diff = engine.registry_diff()
    assert diff["wire_id"] == valid_payload.wire_id
    assert diff["diff_count"] == 2
    assert diff["pre_registry_hash"]
    assert diff["post_registry_hash"]


# T219-CARE-26 — registry_diff() returns no-entries message when empty
def test_care_registry_diff_empty(engine):
    result = engine.registry_diff()
    assert result["last_diff"] is None


# T219-CARE-27 — status() returns module health
def test_care_status_returns_health(engine, valid_payload):
    engine.promote(valid_payload)
    s = engine.status()
    assert s["module"] == "CARE"
    assert s["innov"] == "INNOV-124"
    assert s["version"] == "10.30.0"
    assert s["promotions_successful"] == 1
    assert s["promotions_failed"] == 0
    assert s["chain_valid"] is True
    assert s["active_invariants"] >= 1


# T219-CARE-28 — CARE-HASH-0: pre != post after ADD promotion
def test_care_hash_changes_after_add(engine, valid_payload):
    result = engine.promote(valid_payload)
    # ADD action should change the registry
    assert result["pre_registry_hash"] != result["post_registry_hash"]


# ---------------------------------------------------------------------------
# API router tests (T219-CARE-29, T219-CARE-30)
# ---------------------------------------------------------------------------

# T219-CARE-29 — POST /care/promote returns 200 on valid payload
def test_care_api_promote_success(client):
    payload = {
        "wire_id": str(uuid.uuid4()),
        "amendment_id": str(uuid.uuid4()),
        "title": "API test amendment",
        "amendment_class": "SOFT",
        "human0_ratification_ts": "2026-06-10T12:00:00Z",
        "human0_ratification_ref": "GPG:5C85F8737C93DC0F1E639F9CDD5C7176E87C213E",
        "proposed_by": "DEVADAAD",
        "diff_entries": [
            {"action": "ADD", "invariant_id": "API-TEST-0", "new_text": "API test invariant"},
        ],
        "supporting_invariant_ids": ["CEL-GATE-0"],
        "revert_hash": "abc", "content_hash": "def",
    }
    resp = client.post("/care/promote", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["stage"] == "CERTIFIED"


# T219-CARE-30 — GET /care/status/{wire_id} + GET /care/registry/diff wired
def test_care_api_status_and_diff(client):
    wire_id = str(uuid.uuid4())
    # First promote
    payload = {
        "wire_id": wire_id,
        "amendment_id": str(uuid.uuid4()),
        "title": "Status test",
        "amendment_class": "SOFT",
        "human0_ratification_ts": "2026-06-10T12:00:00Z",
        "human0_ratification_ref": "GPG:TEST",
        "proposed_by": "DEVADAAD",
        "diff_entries": [{"action": "STABLE", "invariant_id": "STABLE-0"}],
        "supporting_invariant_ids": [],
        "revert_hash": "", "content_hash": "",
    }
    client.post("/care/promote", json=payload)

    # Status endpoint
    resp_status = client.get(f"/care/status/{wire_id}")
    assert resp_status.status_code == 200
    assert resp_status.json()["data"]["status"] == "PROMOTED"

    # Diff endpoint
    resp_diff = client.get("/care/registry/diff")
    assert resp_diff.status_code == 200
    assert resp_diff.json()["data"]["wire_id"] == wire_id
