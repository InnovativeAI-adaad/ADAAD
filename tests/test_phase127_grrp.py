# SPDX-License-Identifier: Apache-2.0
"""Phase 127 — INNOV-37 GRRP test suite (30 tests).

Coverage groups:
  BASIC  (T127-GRRP-01..06)  — construction, classification, signing
  ROUTE  (T127-GRRP-07..12)  — GRRP-ROUTE-0 routing invariant
  SIGN   (T127-GRRP-13..16)  — GRRP-SIGN-0 integrity
  DETERM (T127-GRRP-17..20)  — GRRP-DETERM-0 determinism
  CHAIN  (T127-GRRP-21..24)  — GRRP-CHAIN-0 ledger chain
  GATE   (T127-GRRP-25..27)  — GRRP-0 epoch gate
  HUMAN0 (T127-GRRP-28..30)  — GRRP-HUMAN0-0 human gate
"""
import json
import tempfile
from dataclasses import asdict
from pathlib import Path

import pytest

from runtime.innovations30.red_team_response_protocol import (
    CLASS_ADVISORY, CLASS_BREACH, CLASS_CRITICAL, CLASS_WARNING,
    GRRP_INVARIANTS, GRRPEngine, AmendmentProposal, HumanEscalation,
    Finding, ResponseRecord,
    HumanGateBlockError, IntegrityError, RoutingViolationError,
    UnprocessedReportError,
)


# ── helpers ───────────────────────────────────────────────────────────────────
def _engine(tmp_path: Path) -> GRRPEngine:
    return GRRPEngine(ledger_path=tmp_path / "grrp.jsonl")


def _finding(fid: str, outcome: str, target: str = "SANDBOX-DIV-0") -> Finding:
    cls = GRRPEngine.classify(outcome, target)
    return Finding(finding_id=fid, invariant_target=target,
                   outcome=outcome, classification=cls)


# ── BASIC ─────────────────────────────────────────────────────────────────────
def test_T127_GRRP_01_invariant_list():
    """Six invariants declared."""
    assert len(GRRP_INVARIANTS) == 6
    assert "GRRP-0" in GRRP_INVARIANTS
    assert "GRRP-HUMAN0-0" in GRRP_INVARIANTS


def test_T127_GRRP_02_engine_constructs(tmp_path):
    e = _engine(tmp_path)
    assert e._tail_digest == "genesis"


def test_T127_GRRP_03_classify_gate_fired():
    assert GRRPEngine.classify("GATE_FIRED", "X") == CLASS_ADVISORY


def test_T127_GRRP_04_classify_gate_missed():
    assert GRRPEngine.classify("GATE_MISSED", "X") == CLASS_BREACH


def test_T127_GRRP_05_classify_error():
    assert GRRPEngine.classify("ERROR", "X") == CLASS_CRITICAL


def test_T127_GRRP_06_classify_out_of_scope():
    assert GRRPEngine.classify("OUT_OF_SCOPE", "X") == CLASS_WARNING


# ── ROUTE ─────────────────────────────────────────────────────────────────────
def test_T127_GRRP_07_advisory_yields_proposal(tmp_path):
    e = _engine(tmp_path)
    f = _finding("F1", "GATE_FIRED")
    rec = e.grrp_ingest("R1", [f])
    assert len(rec.amendments) == 1
    assert len(rec.escalations) == 0


def test_T127_GRRP_08_breach_yields_escalation(tmp_path):
    e = _engine(tmp_path)
    f = _finding("F2", "GATE_MISSED")
    rec = e.grrp_ingest("R2", [f])
    assert len(rec.escalations) == 1
    assert len(rec.amendments) == 0


def test_T127_GRRP_09_critical_yields_escalation(tmp_path):
    e = _engine(tmp_path)
    f = _finding("F3", "ERROR")
    rec = e.grrp_ingest("R3", [f])
    assert len(rec.escalations) == 1


def test_T127_GRRP_10_warning_yields_proposal(tmp_path):
    e = _engine(tmp_path)
    f = _finding("F4", "OUT_OF_SCOPE")
    rec = e.grrp_ingest("R4", [f])
    assert len(rec.amendments) == 1


def test_T127_GRRP_11_escalation_epoch_blocked(tmp_path):
    e = _engine(tmp_path)
    f = _finding("F5", "GATE_MISSED")
    rec = e.grrp_ingest("R5", [f])
    esc = rec.escalations[0]
    assert esc["epoch_blocked"] is True


def test_T127_GRRP_12_mixed_findings_routed_correctly(tmp_path):
    e = _engine(tmp_path)
    findings = [
        _finding("FA", "GATE_FIRED"),
        _finding("FB", "GATE_MISSED"),
        _finding("FC", "ERROR"),
    ]
    rec = e.grrp_ingest("RM", findings)
    assert len(rec.amendments) == 1
    assert len(rec.escalations) == 2


# ── SIGN ──────────────────────────────────────────────────────────────────────
def test_T127_GRRP_13_amendment_signed(tmp_path):
    e = _engine(tmp_path)
    f = _finding("F6", "GATE_FIRED")
    rec = e.grrp_ingest("R6", [f])
    assert rec.amendments[0]["hmac_digest"].startswith("hmac-sha256:")


def test_T127_GRRP_14_escalation_signed(tmp_path):
    e = _engine(tmp_path)
    f = _finding("F7", "GATE_MISSED")
    rec = e.grrp_ingest("R7", [f])
    assert rec.escalations[0]["hmac_digest"].startswith("hmac-sha256:")


def test_T127_GRRP_15_tampered_proposal_fails_verify():
    prop = AmendmentProposal(
        proposal_id="P-X", finding_id="FX", invariant_target="T",
        classification=CLASS_ADVISORY, patch_description="patch",
    )
    prop.sign()
    prop.patch_description = "TAMPERED"
    assert not prop.verify()


def test_T127_GRRP_16_tampered_escalation_fails_verify():
    esc = HumanEscalation(
        escalation_id="E-X", finding_id="FX", invariant_target="T",
        classification=CLASS_BREACH, reason="reason",
    )
    esc.sign()
    esc.reason = "TAMPERED"
    assert not esc.verify()


# ── DETERM ────────────────────────────────────────────────────────────────────
def test_T127_GRRP_17_response_digest_deterministic(tmp_path):
    e1, e2 = _engine(tmp_path / "a"), _engine(tmp_path / "b")
    f = _finding("FD", "GATE_FIRED")
    r1 = e1.grrp_ingest("RD", [f])
    r2 = e2.grrp_ingest("RD", [f])
    assert r1.response_digest == r2.response_digest


def test_T127_GRRP_18_different_findings_different_digest(tmp_path):
    e1, e2 = _engine(tmp_path / "a"), _engine(tmp_path / "b")
    r1 = e1.grrp_ingest("RD2", [_finding("F1", "GATE_FIRED")])
    r2 = e2.grrp_ingest("RD2", [_finding("F2", "GATE_MISSED")])
    assert r1.response_digest != r2.response_digest


def test_T127_GRRP_19_digest_starts_with_sha256(tmp_path):
    e = _engine(tmp_path)
    rec = e.grrp_ingest("R9", [_finding("FE", "GATE_FIRED")])
    assert rec.response_digest.startswith("sha256:")


def test_T127_GRRP_20_record_digest_deterministic(tmp_path):
    e1, e2 = _engine(tmp_path / "x"), _engine(tmp_path / "y")
    f = _finding("FF", "OUT_OF_SCOPE")
    r1 = e1.grrp_ingest("RR", [f])
    r2 = e2.grrp_ingest("RR", [f])
    assert r1.record_digest == r2.record_digest


# ── CHAIN ─────────────────────────────────────────────────────────────────────
def test_T127_GRRP_21_first_record_genesis(tmp_path):
    e = _engine(tmp_path)
    rec = e.grrp_ingest("RC1", [_finding("G1", "GATE_FIRED")])
    assert rec.prev_digest == "genesis"


def test_T127_GRRP_22_second_record_links_first(tmp_path):
    e = _engine(tmp_path)
    r1 = e.grrp_ingest("RC1", [_finding("G1", "GATE_FIRED")])
    r2 = e.grrp_ingest("RC2", [_finding("G2", "GATE_FIRED")])
    assert r2.prev_digest == r1.record_digest


def test_T127_GRRP_23_chain_three_records(tmp_path):
    e = _engine(tmp_path)
    r1 = e.grrp_ingest("RC1", [_finding("H1", "GATE_FIRED")])
    r2 = e.grrp_ingest("RC2", [_finding("H2", "GATE_FIRED")])
    r3 = e.grrp_ingest("RC3", [_finding("H3", "GATE_FIRED")])
    assert r3.prev_digest == r2.record_digest
    assert r2.prev_digest == r1.record_digest


def test_T127_GRRP_24_ledger_persisted(tmp_path):
    e = _engine(tmp_path)
    e.grrp_ingest("RL", [_finding("L1", "GATE_FIRED")])
    lines = (tmp_path / "grrp.jsonl").read_text().strip().split("\n")
    assert len(lines) == 1
    assert json.loads(lines[0])["report_id"] == "RL"


# ── GATE ──────────────────────────────────────────────────────────────────────
def test_T127_GRRP_25_pending_report_blocks_epoch(tmp_path):
    e = _engine(tmp_path)
    e.register_report("UNPROCESSED")
    with pytest.raises(UnprocessedReportError):
        e.assert_no_pending()


def test_T127_GRRP_26_processed_report_clears_gate(tmp_path):
    e = _engine(tmp_path)
    e.register_report("PR1")
    e.grrp_ingest("PR1", [_finding("PF1", "GATE_FIRED")])
    e.assert_no_pending()   # must not raise


def test_T127_GRRP_27_multiple_reports_all_must_clear(tmp_path):
    e = _engine(tmp_path)
    e.register_report("PR2")
    e.register_report("PR3")
    e.grrp_ingest("PR2", [_finding("PF2", "GATE_FIRED")])
    with pytest.raises(UnprocessedReportError):
        e.assert_no_pending()   # PR3 still pending


# ── HUMAN-0 ───────────────────────────────────────────────────────────────────
def test_T127_GRRP_28_breach_proposal_without_ack_raises(tmp_path):
    prop = AmendmentProposal(
        proposal_id="P-BREACH", finding_id="FB", invariant_target="X",
        classification=CLASS_BREACH, patch_description="fix",
    )
    with pytest.raises(HumanGateBlockError):
        GRRPEngine.assert_human0_ack(prop)


def test_T127_GRRP_29_critical_proposal_without_ack_raises(tmp_path):
    prop = AmendmentProposal(
        proposal_id="P-CRIT", finding_id="FC", invariant_target="X",
        classification=CLASS_CRITICAL, patch_description="fix",
    )
    with pytest.raises(HumanGateBlockError):
        GRRPEngine.assert_human0_ack(prop)


def test_T127_GRRP_30_breach_proposal_with_ack_passes(tmp_path):
    prop = AmendmentProposal(
        proposal_id="P-BREACH2", finding_id="FB2", invariant_target="X",
        classification=CLASS_BREACH, patch_description="fix",
        human0_ack="DUSTIN-L-REID-2026-04-06",
    )
    GRRPEngine.assert_human0_ack(prop)   # must not raise
