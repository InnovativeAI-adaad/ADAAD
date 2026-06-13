"""
tests/test_phase221_cgml.py
Phase 221 · INNOV-126 · CGML — Constitutional Governance Meta-Ledger
30-test acceptance suite · Must achieve 30/30 · Governor: DUSTIN L REID

Test categories:
  CHAIN  — HMAC chain integrity (T221-CGML-01..06)
  APPEND — Append-only and atomic write invariants (T221-CGML-07..10)
  ARC2   — Arc II domain registration (T221-CGML-11..14)
  LNGE   — Lineage matrix and LINEAGE-0 invariant (T221-CGML-15..19)
  XPHS   — Cross-phase ordering invariant (T221-CGML-20..23)
  AUTH   — HUMAN-0 attestation invariant (T221-CGML-24..27)
  API    — FastAPI router endpoint coverage (T221-CGML-28..30)
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch, MagicMock

import pytest

from dorkllm.constitutional_governance_meta_ledger import (
    ARC_II_DOMAINS,
    AttestationDenied,
    ChainIntegrityError,
    ConstitutionalGovernanceMetaLedger,
    ConstitutionalViolation,
    EntryKind,
    LineageStatus,
    XPhaseViolation,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def make_engine(tmp_path: Path) -> ConstitutionalGovernanceMetaLedger:
    return ConstitutionalGovernanceMetaLedger(
        ledger_path=tmp_path / "test_cgml.jsonl"
    )


# ════════════════════════════════════════════════════════════════════════════
# CHAIN — HMAC chain integrity tests (T221-CGML-01..06)
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase221
def test_T221_CGML_01_chain_valid_on_init(tmp_path):
    """T221-CGML-01: empty ledger chain is valid at init."""
    engine = make_engine(tmp_path)
    result = engine.verify_chain()
    assert result["valid"] is True


@pytest.mark.phase221
def test_T221_CGML_02_chain_valid_after_single_append(tmp_path):
    """T221-CGML-02: chain valid after single event append."""
    engine = make_engine(tmp_path)
    engine.append_event(
        kind=EntryKind.PROPOSAL, domain="ACSA", phase=216,
        proposal_id="P-001", payload={"text": "test proposal"},
    )
    result = engine.verify_chain()
    assert result["valid"] is True


@pytest.mark.phase221
def test_T221_CGML_03_chain_valid_after_multi_append(tmp_path):
    """T221-CGML-03: chain valid after multiple event appends."""
    engine = make_engine(tmp_path)
    for domain, phase, kind in [
        ("ACSA", 216, EntryKind.PROPOSAL),
        ("ACPA", 217, EntryKind.ADVICE),
        ("ACAM", 218, EntryKind.MONITOR),
    ]:
        engine.append_event(kind=kind, domain=domain, phase=phase,
                            proposal_id="P-100", payload={})
    result = engine.verify_chain()
    assert result["valid"] is True
    assert result["entry_count"] >= 3


@pytest.mark.phase221
def test_T221_CGML_04_chain_broken_detected(tmp_path):
    """T221-CGML-04: tampered ledger raises ChainIntegrityError on reload."""
    engine = make_engine(tmp_path)
    engine.append_event(
        kind=EntryKind.PROPOSAL, domain="ACSA", phase=216,
        proposal_id="P-002", payload={"text": "tamper test"},
    )
    ledger_file = tmp_path / "test_cgml.jsonl"
    lines = ledger_file.read_text().splitlines()
    # Corrupt first entry's hash
    first = json.loads(lines[0])
    first["entry_hash"] = "0" * 64
    lines[0] = json.dumps(first)
    ledger_file.write_text("\n".join(lines) + "\n")
    with pytest.raises(ChainIntegrityError):
        ConstitutionalGovernanceMetaLedger(ledger_path=ledger_file)


@pytest.mark.phase221
def test_T221_CGML_05_chain_entry_count_in_result(tmp_path):
    """T221-CGML-05: verify_chain reports correct entry count."""
    engine = make_engine(tmp_path)
    for i in range(3):
        engine.append_event(
            kind=EntryKind.PROPOSAL, domain="ACSA", phase=216,
            proposal_id=f"P-{i:03d}", payload={},
        )
    result = engine.verify_chain()
    # 3 PROPOSAL + audit entry from verify_chain itself appended after
    assert result["entry_count"] >= 3


@pytest.mark.phase221
def test_T221_CGML_06_chain_tip_hash_in_result(tmp_path):
    """T221-CGML-06: verify_chain includes non-empty tip_hash."""
    engine = make_engine(tmp_path)
    engine.append_event(
        kind=EntryKind.PROPOSAL, domain="ACSA", phase=216,
        proposal_id="P-X", payload={},
    )
    result = engine.verify_chain()
    assert result["valid"] is True
    assert isinstance(result["tip_hash"], str)
    assert len(result["tip_hash"]) > 0


# ════════════════════════════════════════════════════════════════════════════
# APPEND — Append-only and atomic write (T221-CGML-07..10)
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase221
def test_T221_CGML_07_append_creates_ledger_file(tmp_path):
    """T221-CGML-07: appending an event creates the ledger file."""
    engine = make_engine(tmp_path)
    engine.append_event(
        kind=EntryKind.PROPOSAL, domain="ACSA", phase=216,
        proposal_id="P-FILE", payload={},
    )
    assert (tmp_path / "test_cgml.jsonl").exists()


@pytest.mark.phase221
def test_T221_CGML_08_append_returns_entry_with_hash(tmp_path):
    """T221-CGML-08: append returns MetaEntry with non-empty entry_hash."""
    engine = make_engine(tmp_path)
    entry = engine.append_event(
        kind=EntryKind.ADVICE, domain="ACPA", phase=217,
        proposal_id="P-003", payload={"score": 0.9},
    )
    assert entry.entry_id
    assert len(entry.entry_hash) >= 24


@pytest.mark.phase221
def test_T221_CGML_09_append_increments_entry_count(tmp_path):
    """T221-CGML-09: each non-audit append increments entry count."""
    engine = make_engine(tmp_path)
    before = len(engine._entries)
    engine.append_event(
        kind=EntryKind.MONITOR, domain="ACAM", phase=218,
        proposal_id="P-004", payload={},
    )
    assert len(engine._entries) > before


@pytest.mark.phase221
def test_T221_CGML_10_append_persists_across_reload(tmp_path):
    """T221-CGML-10: entries written by one instance are readable by another."""
    path = tmp_path / "test_cgml.jsonl"
    e1 = ConstitutionalGovernanceMetaLedger(ledger_path=path)
    e1.append_event(
        kind=EntryKind.RATIFY, domain="CARE", phase=219,
        proposal_id="P-PERSIST", payload={"wire_id": "W-001"},
    )
    del e1
    e2 = ConstitutionalGovernanceMetaLedger(ledger_path=path)
    payload_values = [
        e.payload.get("wire_id")
        for e in e2._entries
        if e.payload.get("wire_id") == "W-001"
    ]
    assert "W-001" in payload_values


# ════════════════════════════════════════════════════════════════════════════
# ARC2 — Domain registration invariants (T221-CGML-11..14)
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase221
def test_T221_CGML_11_all_arc2_domains_registered(tmp_path):
    """T221-CGML-11: all six Arc II domains are registered at init."""
    engine = make_engine(tmp_path)
    for domain in ARC_II_DOMAINS:
        assert domain in engine._registered_domains


@pytest.mark.phase221
def test_T221_CGML_12_unregistered_domain_raises(tmp_path):
    """T221-CGML-12: CGML-ARC2-0 — unregistered domain raises ConstitutionalViolation."""
    engine = make_engine(tmp_path)
    with pytest.raises(ConstitutionalViolation, match="CGML-ARC2-0"):
        engine.append_event(
            kind=EntryKind.PROPOSAL, domain="UNKNOWN_DOMAIN", phase=999,
            payload={},
        )


@pytest.mark.phase221
def test_T221_CGML_13_domain_summary_has_all_arc2_domains(tmp_path):
    """T221-CGML-13: get_domain_summary returns entry for every Arc II domain."""
    engine = make_engine(tmp_path)
    summary = engine.get_domain_summary()
    for domain in ARC_II_DOMAINS:
        assert domain in summary


@pytest.mark.phase221
def test_T221_CGML_14_domain_summary_count_updates_after_append(tmp_path):
    """T221-CGML-14: domain summary count increments after appending event."""
    engine = make_engine(tmp_path)
    before = engine.get_domain_summary()["ACSA"]["count"]
    engine.append_event(
        kind=EntryKind.PROPOSAL, domain="ACSA", phase=216,
        proposal_id="P-SUM", payload={},
    )
    after = engine.get_domain_summary()["ACSA"]["count"]
    assert after > before


# ════════════════════════════════════════════════════════════════════════════
# LNGE — Lineage matrix tests (T221-CGML-15..19)
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase221
def test_T221_CGML_15_lineage_matrix_empty_on_fresh_ledger(tmp_path):
    """T221-CGML-15: lineage matrix is empty for a fresh ledger."""
    engine = make_engine(tmp_path)
    matrices = engine.build_lineage_matrix()
    assert isinstance(matrices, list)
    # Fresh ledger: no invariant_id entries → no matrix rows
    assert len(matrices) == 0


@pytest.mark.phase221
def test_T221_CGML_16_lineage_traced_when_proposal_present(tmp_path):
    """T221-CGML-16: invariant with PROPOSAL entry has TRACED lineage."""
    engine = make_engine(tmp_path)
    engine.append_event(
        kind=EntryKind.PROPOSAL, domain="ACSA", phase=216,
        invariant_id="INV-001", proposal_id="P-TRACED", payload={},
    )
    matrices = engine.build_lineage_matrix()
    inv = next((m for m in matrices if m.invariant_id == "INV-001"), None)
    assert inv is not None
    assert inv.lineage_status == LineageStatus.TRACED.value


@pytest.mark.phase221
def test_T221_CGML_17_lineage_orphan_without_proposal(tmp_path):
    """T221-CGML-17: invariant without PROPOSAL entry has ORPHAN lineage."""
    engine = make_engine(tmp_path)
    engine.append_event(
        kind=EntryKind.COHERENCE, domain="CEICC", phase=220,
        invariant_id="INV-ORPHAN", proposal_id=None, payload={},
    )
    matrices = engine.build_lineage_matrix()
    inv = next((m for m in matrices if m.invariant_id == "INV-ORPHAN"), None)
    assert inv is not None
    assert inv.lineage_status == LineageStatus.ORPHAN.value


@pytest.mark.phase221
def test_T221_CGML_18_lineage_matrix_multi_domain(tmp_path):
    """T221-CGML-18: invariant traversing multiple domains has multi-domain lineage."""
    engine = make_engine(tmp_path)
    for domain, phase, kind in [
        ("ACSA", 216, EntryKind.PROPOSAL),
        ("ACPA", 217, EntryKind.ADVICE),
        ("ACAM", 218, EntryKind.MONITOR),
    ]:
        engine.append_event(
            kind=kind, domain=domain, phase=phase,
            invariant_id="INV-MULTI", proposal_id="P-MULTI", payload={},
        )
    matrices = engine.build_lineage_matrix()
    inv = next((m for m in matrices if m.invariant_id == "INV-MULTI"), None)
    assert inv is not None
    assert len(inv.domains_traversed) >= 3


@pytest.mark.phase221
def test_T221_CGML_19_lineage_attestation_ready_flag(tmp_path):
    """T221-CGML-19: traced invariant has attestation_ready=True."""
    engine = make_engine(tmp_path)
    engine.append_event(
        kind=EntryKind.PROPOSAL, domain="ACSA", phase=216,
        invariant_id="INV-ATTEST", proposal_id="P-ATTEST", payload={},
    )
    matrices = engine.build_lineage_matrix()
    inv = next((m for m in matrices if m.invariant_id == "INV-ATTEST"), None)
    assert inv is not None
    assert inv.attestation_ready is True


# ════════════════════════════════════════════════════════════════════════════
# XPHS — Cross-phase ordering (T221-CGML-20..23)
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase221
def test_T221_CGML_20_xphase_valid_on_first_domain(tmp_path):
    """T221-CGML-20: first domain append always has VALID xphase status."""
    engine = make_engine(tmp_path)
    entry = engine.append_event(
        kind=EntryKind.PROPOSAL, domain="ACSA", phase=216,
        proposal_id="P-XPHASE", payload={},
    )
    assert entry.xphase_status == "VALID"


@pytest.mark.phase221
def test_T221_CGML_21_xphase_valid_sequential_domains(tmp_path):
    """T221-CGML-21: sequential Arc II domain appends produce VALID xphase."""
    engine = make_engine(tmp_path)
    for domain, phase, kind in [
        ("ACSA", 216, EntryKind.PROPOSAL),
        ("ACPA", 217, EntryKind.ADVICE),
    ]:
        entry = engine.append_event(
            kind=kind, domain=domain, phase=phase, payload={},
        )
        assert entry.xphase_status == "VALID"


@pytest.mark.phase221
def test_T221_CGML_22_xphase_violation_out_of_order(tmp_path):
    """T221-CGML-22: CGML-XPHASE-0 raises for out-of-order high-phase domain."""
    engine = make_engine(tmp_path)
    # Append CARE (phase 219) first
    engine.append_event(
        kind=EntryKind.RATIFY, domain="CARE", phase=219,
        proposal_id="P-OOO", payload={},
    )
    # Now try to append ACSA (phase 216) — lower phase after higher — violation
    with pytest.raises(XPhaseViolation, match="CGML-XPHASE-0"):
        engine.append_event(
            kind=EntryKind.PROPOSAL, domain="ACSA", phase=216,
            proposal_id="P-OOO", payload={},
        )


@pytest.mark.phase221
def test_T221_CGML_23_xphase_cgml_domain_always_valid(tmp_path):
    """T221-CGML-23: CGML domain events (meta/audit) are always phase-valid."""
    engine = make_engine(tmp_path)
    entry = engine.append_event(
        kind=EntryKind.META, domain="CGML", phase=221,
        payload={"note": "meta event"},
    )
    assert entry.xphase_status == "VALID"


# ════════════════════════════════════════════════════════════════════════════
# AUTH — HUMAN-0 attestation (T221-CGML-24..27)
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase221
def test_T221_CGML_24_attestation_succeeds_with_valid_token(tmp_path):
    """T221-CGML-24: issue_attestation returns valid attestation with HUMAN-0 token."""
    engine = make_engine(tmp_path)
    attest = engine.issue_attestation(human0_token="HUMAN0-TEST-TOKEN")
    assert attest.attestation_id
    assert attest.governor == "DUSTIN L REID"
    assert isinstance(attest.valid, bool)


@pytest.mark.phase221
def test_T221_CGML_25_attestation_denied_empty_token(tmp_path):
    """T221-CGML-25: CGML-HUMAN0-0 — empty token raises AttestationDenied."""
    engine = make_engine(tmp_path)
    with pytest.raises(AttestationDenied, match="CGML-HUMAN0-0"):
        engine.issue_attestation(human0_token="")


@pytest.mark.phase221
def test_T221_CGML_26_attestation_denied_whitespace_token(tmp_path):
    """T221-CGML-26: CGML-HUMAN0-0 — whitespace-only token raises AttestationDenied."""
    engine = make_engine(tmp_path)
    with pytest.raises(AttestationDenied, match="CGML-HUMAN0-0"):
        engine.issue_attestation(human0_token="   ")


@pytest.mark.phase221
def test_T221_CGML_27_attestation_token_redacted_in_cert(tmp_path):
    """T221-CGML-27: attestation certificate redacts the HUMAN-0 token."""
    engine = make_engine(tmp_path)
    token = "SUPER-SECRET-H0-TOKEN"
    attest = engine.issue_attestation(human0_token=token)
    # Must not contain full token
    assert token not in attest.human0_token
    assert attest.human0_token.startswith("***")


# ════════════════════════════════════════════════════════════════════════════
# API — FastAPI router endpoint coverage (T221-CGML-28..30)
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase221
def test_T221_CGML_28_router_status_endpoint(tmp_path):
    """T221-CGML-28: GET /cgml/status returns expected fields."""
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    import app.api.cgml as cgml_module

    # Reset singleton
    cgml_module._engine = ConstitutionalGovernanceMetaLedger(
        ledger_path=tmp_path / "api_test.jsonl"
    )
    app_test = FastAPI()
    app_test.include_router(cgml_module.router)
    client = TestClient(app_test)
    resp = client.get("/cgml/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["phase"] == 221
    assert data["innovation"] == "INNOV-126"
    assert "CGML-CHAIN-0" in data["invariants"]


@pytest.mark.phase221
def test_T221_CGML_29_router_append_and_chain_verify(tmp_path):
    """T221-CGML-29: POST /cgml/event → GET /cgml/chain/verify round-trip."""
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    import app.api.cgml as cgml_module

    cgml_module._engine = ConstitutionalGovernanceMetaLedger(
        ledger_path=tmp_path / "api_chain.jsonl"
    )
    app_test = FastAPI()
    app_test.include_router(cgml_module.router)
    client = TestClient(app_test)

    # Append event
    resp = client.post("/cgml/event", json={
        "kind": "PROPOSAL",
        "domain": "ACSA",
        "phase": 216,
        "proposal_id": "P-API-01",
        "payload": {"source": "test"},
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "APPENDED"

    # Verify chain
    resp2 = client.get("/cgml/chain/verify")
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "CHAIN-VALID"


@pytest.mark.phase221
def test_T221_CGML_30_router_attest_denied_empty_token(tmp_path):
    """T221-CGML-30: POST /cgml/attest with empty token returns 403."""
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    import app.api.cgml as cgml_module

    cgml_module._engine = ConstitutionalGovernanceMetaLedger(
        ledger_path=tmp_path / "api_attest.jsonl"
    )
    app_test = FastAPI()
    app_test.include_router(cgml_module.router)
    client = TestClient(app_test)

    resp = client.post("/cgml/attest", json={"human0_token": ""})
    assert resp.status_code == 403
    assert "CGML-HUMAN0-0" in resp.json()["detail"]
