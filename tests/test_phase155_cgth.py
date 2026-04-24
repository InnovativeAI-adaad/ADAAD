# SPDX-License-Identifier: Apache-2.0
"""Phase 155 — INNOV-61 · CGTH — Constitutional Governance Telemetry Hub
Test suite: 30 tests covering all invariants and functional requirements.

CGTH-CHAIN-0   : hash-chain integrity
CGTH-DETERM-0  : deterministic event_id
CGTH-GATE-0    : registered emitter enforcement
CGTH-PERSIST-0 : ledger write before return
CGTH-HUMAN0-0  : prune requires HUMAN-0 authority
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest

from dorkllm.telemetry_hub import (
    CGTH_CHAIN_ROOT_HMAC,
    HUMAN0_AUTHORITY,
    CGTHChainError,
    CGTHEventType,
    CGTHHuman0Required,
    CGTHLedgerWriteError,
    CGTHUnregisteredEmitterError,
    ConstitutionalGovernanceTelemetryHub,
    TelemetryRecord,
    _canonical,
    _compute_event_id,
    _compute_hmac,
    verify_chain,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_hub(tmp_path: Path) -> ConstitutionalGovernanceTelemetryHub:
    ledger = tmp_path / "cgth_test.jsonl"
    return ConstitutionalGovernanceTelemetryHub(ledger_path=ledger)


def _sample_payload(label: str = "test") -> Dict[str, Any]:
    return {"label": label, "score": 0.42}


# ---------------------------------------------------------------------------
# 1. Module imports cleanly
# ---------------------------------------------------------------------------

def test_01_module_imports() -> None:
    """CGTH module imports without error."""
    from dorkllm import telemetry_hub  # noqa: F401
    assert telemetry_hub is not None


# ---------------------------------------------------------------------------
# 2. Event taxonomy completeness
# ---------------------------------------------------------------------------

def test_02_event_taxonomy_has_required_types() -> None:
    """All required governance event types are present."""
    required = {
        "GATE_VERDICT", "PRESSURE_SNAPSHOT", "THROTTLE_DECISION",
        "INVARIANT_FIRE", "MUTATION_PROPOSED", "MUTATION_OUTCOME",
        "PERM_SNAPSHOT", "CIRCUIT_BREAK", "ROLLBACK_EXECUTED",
        "LEDGER_AUDIT", "HUMAN0_AUTHORISATION", "CGTH_INIT",
    }
    actual = {e.value for e in CGTHEventType}
    assert required <= actual


# ---------------------------------------------------------------------------
# 3. CGTH-DETERM-0: deterministic event_id
# ---------------------------------------------------------------------------

def test_03_event_id_is_deterministic() -> None:
    """Same inputs always produce the same event_id (CGTH-DETERM-0)."""
    eid_a = _compute_event_id("GATE_VERDICT", '{"key":"val"}', CGTH_CHAIN_ROOT_HMAC)
    eid_b = _compute_event_id("GATE_VERDICT", '{"key":"val"}', CGTH_CHAIN_ROOT_HMAC)
    assert eid_a == eid_b


def test_04_event_id_changes_with_payload() -> None:
    """Different payloads produce different event IDs (CGTH-DETERM-0)."""
    eid_a = _compute_event_id("GATE_VERDICT", '{"key":"a"}', CGTH_CHAIN_ROOT_HMAC)
    eid_b = _compute_event_id("GATE_VERDICT", '{"key":"b"}', CGTH_CHAIN_ROOT_HMAC)
    assert eid_a != eid_b


def test_05_event_id_changes_with_prev_hmac() -> None:
    """Different prev_hmac produces different event IDs (CGTH-DETERM-0)."""
    eid_a = _compute_event_id("GATE_VERDICT", '{"k":1}', CGTH_CHAIN_ROOT_HMAC)
    eid_b = _compute_event_id("GATE_VERDICT", '{"k":1}', "a" * 64)
    assert eid_a != eid_b


def test_06_canonical_is_stable() -> None:
    """_canonical() produces sorted, whitespace-free JSON."""
    out = _canonical({"b": 2, "a": 1})
    assert out == '{"a":1,"b":2}'


# ---------------------------------------------------------------------------
# 4. CGTH-GATE-0: registered emitter enforcement
# ---------------------------------------------------------------------------

def test_07_registered_component_succeeds(tmp_hub: ConstitutionalGovernanceTelemetryHub) -> None:
    """Registered component emits without error (CGTH-GATE-0)."""
    eid = tmp_hub.emit_event("cpi", CGTHEventType.PRESSURE_SNAPSHOT, _sample_payload())
    assert isinstance(eid, str) and len(eid) == 64


def test_08_unregistered_component_raises(tmp_hub: ConstitutionalGovernanceTelemetryHub) -> None:
    """Unregistered emitter raises CGTHUnregisteredEmitterError (CGTH-GATE-0)."""
    with pytest.raises(CGTHUnregisteredEmitterError):
        tmp_hub.emit_event("rogue_module", CGTHEventType.GATE_VERDICT, {})


def test_09_all_known_components_accepted(tmp_hub: ConstitutionalGovernanceTelemetryHub) -> None:
    """All registered component IDs are accepted by the gate (CGTH-GATE-0)."""
    from dorkllm.telemetry_hub import _KNOWN_COMPONENTS
    for cid in _KNOWN_COMPONENTS:
        eid = tmp_hub.emit_event(cid, CGTHEventType.CGTH_INIT, {"cid": cid})
        assert len(eid) == 64


# ---------------------------------------------------------------------------
# 5. CGTH-PERSIST-0: ledger written before return
# ---------------------------------------------------------------------------

def test_10_event_persisted_to_ledger(tmp_hub: ConstitutionalGovernanceTelemetryHub) -> None:
    """emit_event writes to ledger before returning (CGTH-PERSIST-0)."""
    eid = tmp_hub.emit_event("amt", CGTHEventType.THROTTLE_DECISION, {"level": "high"})
    records = tmp_hub.query()
    assert any(r.event_id == eid for r in records)


def test_11_ledger_file_written_on_disk(tmp_path: Path) -> None:
    """Ledger JSONL file is created and populated (CGTH-PERSIST-0)."""
    ledger_path = tmp_path / "cgth.jsonl"
    hub = ConstitutionalGovernanceTelemetryHub(ledger_path=ledger_path)
    hub.emit_event("cpi", CGTHEventType.PRESSURE_SNAPSHOT, {"x": 1})
    assert ledger_path.exists()
    lines = ledger_path.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["event_type"] == "PRESSURE_SNAPSHOT"


# ---------------------------------------------------------------------------
# 6. CGTH-CHAIN-0: hash-chain integrity
# ---------------------------------------------------------------------------

def test_12_chain_root_prev_hmac_is_zeros(tmp_hub: ConstitutionalGovernanceTelemetryHub) -> None:
    """First record's prev_hmac is the 64-zero sentinel (CGTH-CHAIN-0)."""
    tmp_hub.emit_event("cpi", CGTHEventType.PRESSURE_SNAPSHOT, {"first": True})
    records = tmp_hub.query()
    assert records[0].prev_hmac == CGTH_CHAIN_ROOT_HMAC


def test_13_second_record_links_to_first(tmp_hub: ConstitutionalGovernanceTelemetryHub) -> None:
    """Second record's prev_hmac equals first record's this_hmac (CGTH-CHAIN-0)."""
    tmp_hub.emit_event("cpi", CGTHEventType.PRESSURE_SNAPSHOT, {"n": 1})
    tmp_hub.emit_event("amt", CGTHEventType.THROTTLE_DECISION, {"n": 2})
    records = tmp_hub.query()
    assert records[1].prev_hmac == records[0].this_hmac


def test_14_verify_chain_intact(tmp_hub: ConstitutionalGovernanceTelemetryHub) -> None:
    """verify_chain() returns True for an intact chain (CGTH-CHAIN-0)."""
    for i in range(5):
        tmp_hub.emit_event("cpi", CGTHEventType.PRESSURE_SNAPSHOT, {"i": i})
    records = tmp_hub.query()
    assert verify_chain(records) is True


def test_15_verify_chain_detects_tamper(tmp_hub: ConstitutionalGovernanceTelemetryHub) -> None:
    """verify_chain() raises CGTHChainError on tampered prev_hmac (CGTH-CHAIN-0)."""
    for i in range(3):
        tmp_hub.emit_event("cpi", CGTHEventType.PRESSURE_SNAPSHOT, {"i": i})
    records = tmp_hub.query()
    # Tamper: replace second record's prev_hmac
    tampered = list(records)
    good = tampered[1]
    bad = TelemetryRecord(
        event_id    = good.event_id,
        event_type  = good.event_type,
        component_id= good.component_id,
        payload     = good.payload,
        prev_hmac   = "deadbeef" * 8,
        this_hmac   = good.this_hmac,
        seq         = good.seq,
    )
    tampered[1] = bad
    with pytest.raises(CGTHChainError):
        verify_chain(tampered)


def test_16_verify_chain_detects_hmac_mismatch(tmp_hub: ConstitutionalGovernanceTelemetryHub) -> None:
    """verify_chain() raises CGTHChainError on tampered this_hmac (CGTH-CHAIN-0)."""
    tmp_hub.emit_event("cpi", CGTHEventType.PRESSURE_SNAPSHOT, {"x": 9})
    records = tmp_hub.query()
    bad = TelemetryRecord(
        event_id    = records[0].event_id,
        event_type  = records[0].event_type,
        component_id= records[0].component_id,
        payload     = records[0].payload,
        prev_hmac   = records[0].prev_hmac,
        this_hmac   = "0" * 64,  # wrong
        seq         = records[0].seq,
    )
    with pytest.raises(CGTHChainError):
        verify_chain([bad])


def test_17_empty_chain_verifies_clean() -> None:
    """verify_chain([]) returns True for empty sequence (CGTH-CHAIN-0)."""
    assert verify_chain([]) is True


# ---------------------------------------------------------------------------
# 7. CGTH-HUMAN0-0: prune authorisation
# ---------------------------------------------------------------------------

def test_18_human0_prune_with_correct_authority(tmp_hub: ConstitutionalGovernanceTelemetryHub) -> None:
    """human0_authorised_prune succeeds with DUSTIN L REID authority (CGTH-HUMAN0-0)."""
    eid = tmp_hub.human0_authorised_prune(
        authority=HUMAN0_AUTHORITY,
        reason="test prune",
        records_to_prune=10,
    )
    assert len(eid) == 64


def test_19_human0_prune_wrong_authority_raises(tmp_hub: ConstitutionalGovernanceTelemetryHub) -> None:
    """Prune with wrong authority raises CGTHHuman0Required (CGTH-HUMAN0-0)."""
    with pytest.raises(CGTHHuman0Required):
        tmp_hub.human0_authorised_prune(
            authority="some_other_person",
            reason="unauthorized",
            records_to_prune=5,
        )


def test_20_human0_prune_records_event_type(tmp_hub: ConstitutionalGovernanceTelemetryHub) -> None:
    """Prune authorisation event is recorded as HUMAN0_AUTHORISATION (CGTH-HUMAN0-0)."""
    tmp_hub.human0_authorised_prune(HUMAN0_AUTHORITY, "test", 1)
    records = tmp_hub.query(event_type=CGTHEventType.HUMAN0_AUTHORISATION)
    assert len(records) == 1
    assert records[0].payload["authority"] == HUMAN0_AUTHORITY


# ---------------------------------------------------------------------------
# 8. Functional: query and filtering
# ---------------------------------------------------------------------------

def test_21_query_by_event_type(tmp_hub: ConstitutionalGovernanceTelemetryHub) -> None:
    """query(event_type=...) filters correctly."""
    tmp_hub.emit_event("cpi", CGTHEventType.PRESSURE_SNAPSHOT, {"n": 1})
    tmp_hub.emit_event("amt", CGTHEventType.THROTTLE_DECISION, {"n": 2})
    snapshots = tmp_hub.query(event_type=CGTHEventType.PRESSURE_SNAPSHOT)
    assert all(r.event_type == CGTHEventType.PRESSURE_SNAPSHOT for r in snapshots)
    assert len(snapshots) == 1


def test_22_query_by_component_id(tmp_hub: ConstitutionalGovernanceTelemetryHub) -> None:
    """query(component_id=...) filters correctly."""
    tmp_hub.emit_event("cpi", CGTHEventType.PRESSURE_SNAPSHOT, {"x": 1})
    tmp_hub.emit_event("amt", CGTHEventType.THROTTLE_DECISION, {"x": 2})
    cpi_records = tmp_hub.query(component_id="cpi")
    assert all(r.component_id == "cpi" for r in cpi_records)


def test_23_query_limit_respected(tmp_hub: ConstitutionalGovernanceTelemetryHub) -> None:
    """query(limit=N) returns at most N records."""
    for i in range(10):
        tmp_hub.emit_event("cpi", CGTHEventType.PRESSURE_SNAPSHOT, {"i": i})
    records = tmp_hub.query(limit=3)
    assert len(records) <= 3


def test_24_tail_returns_last_n(tmp_hub: ConstitutionalGovernanceTelemetryHub) -> None:
    """tail(n) returns the last n records in insertion order."""
    for i in range(5):
        tmp_hub.emit_event("cpi", CGTHEventType.PRESSURE_SNAPSHOT, {"i": i})
    tail = tmp_hub.tail(2)
    assert len(tail) == 2
    assert tail[-1].payload["i"] == 4


# ---------------------------------------------------------------------------
# 9. Functional: PERM snapshot aggregation
# ---------------------------------------------------------------------------

def test_25_perm_snapshot_recorded(tmp_hub: ConstitutionalGovernanceTelemetryHub) -> None:
    """snapshot_perm_engines() records a PERM_SNAPSHOT event."""
    eid = tmp_hub.snapshot_perm_engines("CPI", {"score": 0.88})
    records = tmp_hub.query(event_type=CGTHEventType.PERM_SNAPSHOT)
    assert len(records) == 1
    assert records[0].payload["engine_id"] == "CPI"
    assert records[0].event_id == eid


# ---------------------------------------------------------------------------
# 10. Functional: audit_chain
# ---------------------------------------------------------------------------

def test_26_audit_chain_returns_summary(tmp_hub: ConstitutionalGovernanceTelemetryHub) -> None:
    """audit_chain() returns a summary dict and emits LEDGER_AUDIT event."""
    tmp_hub.emit_event("cpi", CGTHEventType.PRESSURE_SNAPSHOT, {"x": 1})
    summary = tmp_hub.audit_chain()
    assert summary["chain_intact"] is True
    assert summary["record_count"] >= 1
    # Audit event itself should be present
    audits = tmp_hub.query(event_type=CGTHEventType.LEDGER_AUDIT)
    assert len(audits) >= 1


def test_27_seq_increments_monotonically(tmp_hub: ConstitutionalGovernanceTelemetryHub) -> None:
    """seq field increments by 1 for each new event."""
    for i in range(4):
        tmp_hub.emit_event("cpi", CGTHEventType.PRESSURE_SNAPSHOT, {"i": i})
    records = tmp_hub.query()
    seqs = [r.seq for r in records]
    assert seqs == list(range(len(seqs)))


# ---------------------------------------------------------------------------
# 11. TelemetryRecord serialisation round-trip
# ---------------------------------------------------------------------------

def test_28_record_roundtrip(tmp_hub: ConstitutionalGovernanceTelemetryHub) -> None:
    """TelemetryRecord serialises and deserialises losslessly."""
    tmp_hub.emit_event("cpi", CGTHEventType.PRESSURE_SNAPSHOT, {"data": "round"})
    records = tmp_hub.query()
    r = records[0]
    d = r.to_dict()
    r2 = TelemetryRecord.from_dict(d)
    assert r2.event_id == r.event_id
    assert r2.event_type == r.event_type
    assert r2.payload == r.payload
    assert r2.prev_hmac == r.prev_hmac
    assert r2.this_hmac == r.this_hmac


# ---------------------------------------------------------------------------
# 12. Singleton module-level get_hub / emit
# ---------------------------------------------------------------------------

def test_29_module_level_emit(tmp_path: Path) -> None:
    """Module-level emit() delegates to the singleton hub."""
    import dorkllm.telemetry_hub as th
    ledger = tmp_path / "singleton.jsonl"
    # Temporarily reset singleton
    orig = th._default_hub
    th._default_hub = None
    try:
        with patch.dict(os.environ, {"ADAAD_CGTH_LEDGER_PATH": str(ledger)}):
            eid = th.emit("cpi", CGTHEventType.GATE_VERDICT, {"test": True})
        assert isinstance(eid, str) and len(eid) == 64
        assert ledger.exists()
    finally:
        th._default_hub = orig


# ---------------------------------------------------------------------------
# 13. REST router structural check
# ---------------------------------------------------------------------------

def test_30_rest_router_routes_defined() -> None:
    """governance_telemetry router defines all required route paths."""
    from app.api.governance_telemetry import router
    paths = {r.path for r in router.routes}
    assert "/api/governance/telemetry/stream" in paths
    assert "/api/governance/telemetry/audit" in paths
    assert "/api/governance/telemetry/summary" in paths
    assert "/api/governance/telemetry/emit" in paths
