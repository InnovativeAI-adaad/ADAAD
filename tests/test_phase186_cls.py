# SPDX-License-Identifier: Apache-2.0
"""
Test suite — INNOV-91 · CLS — CEL Loop Sentinel
Phase 186 · v9.119.0 · InnovativeAI LLC
Governor: DUSTIN L REID

30 tests covering: scan determinism, gate evaluation, chain integrity,
advisory emission, ledger persistence, REST endpoints, invariant counts,
closure scoring, status query, and constitutional boundary conditions.
"""

import json
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.phase186_cls


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_ledger(tmp_path):
    return tmp_path / "cls_ledger.jsonl"


@pytest.fixture
def sentinel(tmp_ledger):
    from dorkllm.cel_loop_sentinel import CELLoopSentinel
    return CELLoopSentinel(ledger_path=tmp_ledger)


@pytest.fixture
def client(tmp_ledger, monkeypatch):
    import dorkllm.cel_loop_sentinel as mod
    monkeypatch.setattr(mod, "_LEDGER_PATH", tmp_ledger)
    import app.api.cel_loop_sentinel as rmod
    rmod._engine = None
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(rmod.router)
    return TestClient(app)


# ── T186-CLS-01: module imports cleanly ──────────────────────────────────────
def test_cls_01_import():
    from dorkllm.cel_loop_sentinel import CELLoopSentinel
    assert CELLoopSentinel is not None


# ── T186-CLS-02: sentinel instantiates ───────────────────────────────────────
def test_cls_02_instantiate(sentinel):
    assert sentinel is not None


# ── T186-CLS-03: scan returns CLSSnapshot ────────────────────────────────────
def test_cls_03_scan_returns_snapshot(sentinel):
    from dorkllm.cel_loop_sentinel import CLSSnapshot
    snap = sentinel.scan()
    assert isinstance(snap, CLSSnapshot)


# ── T186-CLS-04: snapshot has 12 invariants active ───────────────────────────
def test_cls_04_invariant_count(sentinel):
    snap = sentinel.scan()
    assert len(snap.invariants_active) == 12


# ── T186-CLS-05: all expected invariant codes present ────────────────────────
def test_cls_05_invariant_codes(sentinel):
    snap = sentinel.scan()
    required = {
        "CLS-SCOPE-0", "CLS-DETERM-0", "CLS-CHAIN-0", "CLS-IMMUT-0",
        "CLS-ADVISORY-0", "CLS-SEAL-0", "CLS-READONLY-0", "CLS-AUDIT-0",
        "CLS-HUMAN0-0", "CLS-CLOSURE-0", "CLS-PERSIST-0", "CLS-SNAPSHOT-0",
    }
    assert required == set(snap.invariants_active)


# ── T186-CLS-06: closure score is float in [0, 1] ────────────────────────────
def test_cls_06_closure_score_range(sentinel):
    snap = sentinel.scan()
    assert 0.0 <= snap.closure_score <= 1.0


# ── T186-CLS-07: all 9 gates evaluated ───────────────────────────────────────
def test_cls_07_gate_count(sentinel):
    snap = sentinel.scan()
    assert len(snap.gate_results) == 9


# ── T186-CLS-08: gate IDs are G1–G9 ─────────────────────────────────────────
def test_cls_08_gate_ids(sentinel):
    snap = sentinel.scan()
    ids = {r.gate_id for r in snap.gate_results}
    assert ids == {"G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9"}


# ── T186-CLS-09: all gates PASS (all backed) ─────────────────────────────────
def test_cls_09_all_gates_pass(sentinel):
    snap = sentinel.scan()
    for r in snap.gate_results:
        assert r.status == "PASS", f"Gate {r.gate_id} unexpectedly failed"


# ── T186-CLS-10: closure status FULLY_CLOSED when all gates pass ─────────────
def test_cls_10_fully_closed(sentinel):
    snap = sentinel.scan()
    assert snap.closure_status == "FULLY_CLOSED"


# ── T186-CLS-11: no advisory when FULLY_CLOSED ───────────────────────────────
def test_cls_11_no_advisory_when_closed(sentinel):
    snap = sentinel.scan()
    # All gates backed → FULLY_CLOSED → no advisory
    assert snap.advisory_payload is None
    assert snap.human0_required is False


# ── T186-CLS-12: seal is non-empty hex string ────────────────────────────────
def test_cls_12_seal_hex(sentinel):
    snap = sentinel.scan()
    assert isinstance(snap.seal, str)
    assert len(snap.seal) == 64
    int(snap.seal, 16)  # valid hex


# ── T186-CLS-13: first snapshot has prev_seal None ───────────────────────────
def test_cls_13_first_prev_seal_none(sentinel):
    snap = sentinel.scan()
    assert snap.prev_seal is None


# ── T186-CLS-14: epoch counter increments monotonically ──────────────────────
def test_cls_14_epoch_monotonic(sentinel):
    s1 = sentinel.scan()
    s2 = sentinel.scan()
    assert s2.epoch_counter == s1.epoch_counter + 1


# ── T186-CLS-15: second snapshot has prev_seal from first ────────────────────
def test_cls_15_chain_linkage(sentinel):
    s1 = sentinel.scan()
    s2 = sentinel.scan()
    assert s2.prev_seal == s1.seal


# ── T186-CLS-16: ledger grows with each scan ─────────────────────────────────
def test_cls_16_ledger_grows(sentinel):
    assert len(sentinel.ledger()) == 0
    sentinel.scan()
    assert len(sentinel.ledger()) == 1
    sentinel.scan()
    assert len(sentinel.ledger()) == 2


# ── T186-CLS-17: ledger entries are valid JSON ───────────────────────────────
def test_cls_17_ledger_json(sentinel, tmp_ledger):
    sentinel.scan()
    for line in tmp_ledger.read_text().splitlines():
        obj = json.loads(line)
        assert "snapshot_id" in obj


# ── T186-CLS-18: chain verification passes on valid ledger ───────────────────
def test_cls_18_chain_verify_valid(sentinel):
    sentinel.scan()
    sentinel.scan()
    result = sentinel.verify_chain()
    assert result["chain_valid"] is True
    assert result["entry_count"] == 2
    assert result["first_broken_at"] is None


# ── T186-CLS-19: chain verify detects tampering ──────────────────────────────
def test_cls_19_chain_tamper_detected(sentinel, tmp_ledger):
    sentinel.scan()
    # tamper ledger
    lines = tmp_ledger.read_text().splitlines()
    entry = json.loads(lines[0])
    entry["closure_score"] = 0.0
    lines[0] = json.dumps(entry)
    tmp_ledger.write_text("\n".join(lines) + "\n")
    # fresh instance reads tampered ledger
    from dorkllm.cel_loop_sentinel import CELLoopSentinel
    s2 = CELLoopSentinel(ledger_path=tmp_ledger)
    result = s2.verify_chain()
    assert result["chain_valid"] is False
    assert result["first_broken_at"] == 0


# ── T186-CLS-20: snapshot_id is auto-generated if not provided ───────────────
def test_cls_20_auto_snapshot_id(sentinel):
    snap = sentinel.scan()
    assert snap.snapshot_id.startswith("CLS-")


# ── T186-CLS-21: custom snapshot_id is honoured ──────────────────────────────
def test_cls_21_custom_snapshot_id(sentinel):
    snap = sentinel.scan(snapshot_id="DUSTIN-RATIFIED-001")
    assert snap.snapshot_id == "DUSTIN-RATIFIED-001"


# ── T186-CLS-22: governor is DUSTIN L REID ───────────────────────────────────
def test_cls_22_governor(sentinel):
    snap = sentinel.scan()
    assert snap.governor == "DUSTIN L REID"


# ── T186-CLS-23: innovation tag is INNOV-91-CLS ──────────────────────────────
def test_cls_23_innovation_tag(sentinel):
    snap = sentinel.scan()
    assert snap.innovation == "INNOV-91-CLS"


# ── T186-CLS-24: status endpoint works before any scan ───────────────────────
def test_cls_24_status_pre_scan(sentinel):
    st = sentinel.status()
    assert st["gate_count"] == 9
    assert st["invariant_count"] == 12


# ── T186-CLS-25: status reflects last snapshot after scan ────────────────────
def test_cls_25_status_post_scan(sentinel):
    sentinel.scan()
    st = sentinel.status()
    assert "closure_score" in st
    assert "closure_status" in st


# ── T186-CLS-26: REST POST /api/cls/scan returns 200 ────────────────────────
def test_cls_26_rest_scan(client):
    r = client.post("/api/cls/scan", json={})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert "snapshot" in r.json()


# ── T186-CLS-27: REST GET /api/cls/status returns 200 ───────────────────────
def test_cls_27_rest_status(client):
    r = client.get("/api/cls/status")
    assert r.status_code == 200
    assert r.json()["ok"] is True


# ── T186-CLS-28: REST GET /api/cls/ledger returns entries ───────────────────
def test_cls_28_rest_ledger(client):
    client.post("/api/cls/scan", json={})
    r = client.get("/api/cls/ledger")
    assert r.status_code == 200
    assert len(r.json()["ledger"]) >= 1


# ── T186-CLS-29: REST GET /api/cls/verify passes on fresh ledger ─────────────
def test_cls_29_rest_verify(client):
    client.post("/api/cls/scan", json={})
    r = client.get("/api/cls/verify")
    assert r.status_code == 200
    assert r.json()["verification"]["chain_valid"] is True


# ── T186-CLS-30: closure score sums gate weights correctly ───────────────────
def test_cls_30_score_weights(sentinel):
    from dorkllm.cel_loop_sentinel import _CEL_GATES
    snap = sentinel.scan()
    expected = round(sum(g.weight for g in _CEL_GATES), 6)
    assert abs(snap.closure_score - expected) < 1e-5
