# SPDX-License-Identifier: Apache-2.0
# tests/test_phase215_cgvf.py
# Phase 215 · INNOV-120 · CGVF — Constitutional Governance Validation Fusion
# 30/30 acceptance tests · Governor: DUSTIN L REID
"""
T215-CGVF-01  through  T215-CGVF-30
Marker: phase215, cgvf
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch, MagicMock

import pytest

# ── Module under test ──────────────────────────────────────────────────────────

from dorkllm.constitutional_governance_validation_fusion import (
    ConstitutionalGovernanceValidationFusion,
    FusionAttestation,
    FusionStatus,
    PeerSignal,
    CGVFError,
    CGVFCertError,
    CGVFScoreError,
    CGVFConsensusError,
    CGVFChainError,
    CGVFImmutError,
    CGVF_AUDIT_0,
    CGVF_CHAIN_0,
    CGVF_DETERM_0,
    CGVF_FAILCLOSED_0,
    CGVF_ATOMIC_0,
    CGVF_HUMAN0_0,
    CGVF_SCORE_0,
    CGVF_PEER_0,
    CGVF_SEAL_0,
    CGVF_IMMUT_0,
    CGVF_CERT_0,
    CGVF_CONSENSUS_0,
    _HMAC_KEY,
    GOVERNOR,
)

pytestmark = [pytest.mark.phase215, pytest.mark.cgvf]


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture()
def tmp_ledger(tmp_path: Path) -> Path:
    return tmp_path / "cgvf_test_ledger.jsonl"


@pytest.fixture()
def engine(tmp_ledger: Path) -> ConstitutionalGovernanceValidationFusion:
    """Engine with isolated ledger; peers mocked to return healthy signals."""
    eng = ConstitutionalGovernanceValidationFusion(ledger_path=tmp_ledger)
    return eng


def _mock_peers(cgva=0.90, cgvr="REMEDIATED", cgve="COMPLIANT", cgpr="PROOF_PRESENT"):
    """Patch _PEER_QUERIES dict directly so dict-dispatch is covered."""
    from dorkllm import constitutional_governance_validation_fusion as mod

    def fake_cgva():
        return cgva, cgva

    def fake_cgvr():
        score_map = {"REMEDIATED": 1.0, "PARTIAL": 0.6, "BLOCKED": 0.3,
                     "HUMAN0_REQUIRED": 0.0, "FAILED": 0.0, "NO_HISTORY": 1.0}
        return score_map.get(cgvr, 0.5), cgvr

    def fake_cgve():
        score_map = {"COMPLIANT": 1.0, "REPAIRED": 0.8, "DRIFTED": 0.3,
                     "FAILED": 0.0, "BLOCKED": 0.1, "NO_HISTORY": 1.0}
        return score_map.get(cgve, 0.5), cgve

    def fake_cgpr():
        return (1.0, "PROOF_PRESENT") if cgpr == "PROOF_PRESENT" else (0.5, "NO_HISTORY")

    fake_queries = {
        "CGVA": fake_cgva,
        "CGVR": fake_cgvr,
        "CGVE": fake_cgve,
        "CGPR": fake_cgpr,
    }
    return patch.object(mod, "_PEER_QUERIES", fake_queries)


# ── T215-CGVF-01: Module imports cleanly ──────────────────────────────────────

def test_cgvf_01_module_imports():
    """T215-CGVF-01: Module and all public symbols importable."""
    from dorkllm.constitutional_governance_validation_fusion import (
        ConstitutionalGovernanceValidationFusion,
        FusionAttestation,
        FusionStatus,
        PeerSignal,
        CGVFError,
    )
    assert ConstitutionalGovernanceValidationFusion is not None


# ── T215-CGVF-02: Invariant constants are defined ─────────────────────────────

def test_cgvf_02_invariant_constants():
    """T215-CGVF-02: All 12 Hard-class invariant constants defined."""
    constants = [
        CGVF_AUDIT_0, CGVF_CHAIN_0, CGVF_DETERM_0, CGVF_FAILCLOSED_0,
        CGVF_ATOMIC_0, CGVF_HUMAN0_0, CGVF_SCORE_0, CGVF_PEER_0,
        CGVF_SEAL_0, CGVF_IMMUT_0, CGVF_CERT_0, CGVF_CONSENSUS_0,
    ]
    assert len(constants) == 12
    for c in constants:
        assert c.startswith("CGVF-")


# ── T215-CGVF-03: Invariant constant names match values ───────────────────────

def test_cgvf_03_invariant_name_value_parity():
    """T215-CGVF-03: Named constants match their string values."""
    assert CGVF_AUDIT_0      == "CGVF-AUDIT-0"
    assert CGVF_CHAIN_0      == "CGVF-CHAIN-0"
    assert CGVF_HUMAN0_0     == "CGVF-HUMAN0-0"
    assert CGVF_SCORE_0      == "CGVF-SCORE-0"
    assert CGVF_CONSENSUS_0  == "CGVF-CONSENSUS-0"


# ── T215-CGVF-04: Typed exception hierarchy ───────────────────────────────────

def test_cgvf_04_exception_hierarchy():
    """T215-CGVF-04: All CGVF exceptions are RuntimeError subclasses."""
    for exc_cls in (CGVFError, CGVFCertError, CGVFScoreError,
                    CGVFConsensusError, CGVFChainError, CGVFImmutError):
        assert issubclass(exc_cls, RuntimeError)


# ── T215-CGVF-05: FusionStatus enum values ────────────────────────────────────

def test_cgvf_05_fusion_status_values():
    """T215-CGVF-05: FusionStatus has required states."""
    expected = {"HEALTHY", "DEGRADED", "CRITICAL", "HUMAN0_REQUIRED"}
    assert {s.value for s in FusionStatus} == expected


# ── T215-CGVF-06: Successful fuse returns FusionAttestation ──────────────────

def test_cgvf_06_fuse_returns_attestation(engine, tmp_ledger):
    """T215-CGVF-06: fuse() returns a FusionAttestation."""
    with _mock_peers():
        result = engine.fuse()
    assert isinstance(result, FusionAttestation)


# ── T215-CGVF-07: consensus_score in [0.0, 1.0] ──────────────────────────────

def test_cgvf_07_score_in_range(engine):
    """T215-CGVF-07: consensus_score is within [0.0, 1.0]. CGVF-SCORE-0."""
    with _mock_peers():
        result = engine.fuse()
    assert 0.0 <= result.consensus_score <= 1.0


# ── T215-CGVF-08: Healthy peers produce HEALTHY status ───────────────────────

def test_cgvf_08_healthy_status(engine):
    """T215-CGVF-08: All healthy peers → FusionStatus.HEALTHY."""
    with _mock_peers(cgva=0.95, cgvr="REMEDIATED", cgve="COMPLIANT", cgpr="PROOF_PRESENT"):
        result = engine.fuse()
    assert result.overall_status == FusionStatus.HEALTHY
    assert result.consensus_score >= 0.85


# ── T215-CGVF-09: Low CGVA score degrades consensus ──────────────────────────

def test_cgvf_09_low_cgva_degrades(engine):
    """T215-CGVF-09: Low CGVA score (0.30) produces DEGRADED or worse."""
    with _mock_peers(cgva=0.30, cgvr="REMEDIATED", cgve="COMPLIANT", cgpr="PROOF_PRESENT"):
        result = engine.fuse()
    assert result.overall_status in (
        FusionStatus.DEGRADED, FusionStatus.HUMAN0_REQUIRED, FusionStatus.CRITICAL
    )


# ── T215-CGVF-10: HUMAN-0 required below threshold ───────────────────────────

def test_cgvf_10_human0_required(engine):
    """T215-CGVF-10: consensus_score < 0.70 → human0_required=True. CGVF-HUMAN0-0."""
    with _mock_peers(cgva=0.10, cgvr="FAILED", cgve="FAILED", cgpr="NO_HISTORY"):
        result = engine.fuse()
    assert result.human0_required is True


# ── T215-CGVF-11: High score → human0_required=False ─────────────────────────

def test_cgvf_11_no_human0_required_healthy(engine):
    """T215-CGVF-11: Healthy consensus → human0_required=False."""
    with _mock_peers(cgva=0.95, cgvr="REMEDIATED", cgve="COMPLIANT", cgpr="PROOF_PRESENT"):
        result = engine.fuse()
    assert result.human0_required is False


# ── T215-CGVF-12: CGVF-DETERM-0 — fusion_id is deterministic ────────────────

def test_cgvf_12_fusion_id_is_sha256(engine):
    """T215-CGVF-12: fusion_id is a 64-char hex string (SHA-256). CGVF-DETERM-0."""
    with _mock_peers():
        result = engine.fuse()
    assert len(result.fusion_id) == 64
    int(result.fusion_id, 16)  # raises if not hex


# ── T215-CGVF-13: CGVF-SEAL-0 — hmac_digest is present ──────────────────────

def test_cgvf_13_hmac_digest_present(engine):
    """T215-CGVF-13: Every FusionAttestation carries a non-empty hmac_digest."""
    with _mock_peers():
        result = engine.fuse()
    assert len(result.hmac_digest) == 64


# ── T215-CGVF-14: CGVF-AUDIT-0 — ledger written before return ────────────────

def test_cgvf_14_ledger_written(engine, tmp_ledger):
    """T215-CGVF-14: fuse() writes to ledger. CGVF-AUDIT-0."""
    assert not tmp_ledger.exists() or tmp_ledger.stat().st_size == 0
    with _mock_peers():
        engine.fuse()
    assert tmp_ledger.exists() and tmp_ledger.stat().st_size > 0


# ── T215-CGVF-15: CGVF-CHAIN-0 — prev_digest links ──────────────────────────

def test_cgvf_15_chain_prev_digest(engine, tmp_ledger):
    """T215-CGVF-15: Second fuse() has prev_digest = HMAC of first line. CGVF-CHAIN-0."""
    with _mock_peers():
        first  = engine.fuse()
        second = engine.fuse()
    lines = [l.strip() for l in tmp_ledger.read_text().splitlines() if l.strip()]
    assert len(lines) == 2
    expected_prev = hmac.new(_HMAC_KEY, lines[0].encode(), "sha256").hexdigest()
    assert second.prev_digest == expected_prev


# ── T215-CGVF-16: CGVF-CHAIN-0 — first entry prev_digest is zeros ────────────

def test_cgvf_16_first_prev_digest_zeros(engine):
    """T215-CGVF-16: First ledger entry has prev_digest = 64 zeros."""
    with _mock_peers():
        first = engine.fuse()
    assert first.prev_digest == "0" * 64


# ── T215-CGVF-17: verify_chain returns True on clean ledger ──────────────────

def test_cgvf_17_verify_chain_clean(engine):
    """T215-CGVF-17: verify_chain() returns valid=True after fuse(). CGVF-CHAIN-0."""
    with _mock_peers():
        engine.fuse()
        engine.fuse()
    result = engine.verify_chain()
    assert result["valid"] is True
    assert result["entries"] == 2


# ── T215-CGVF-18: history() returns correct records ──────────────────────────

def test_cgvf_18_history_returns_records(engine):
    """T215-CGVF-18: history() returns FusionAttestation list."""
    with _mock_peers():
        engine.fuse()
        engine.fuse()
    records = engine.history(limit=10)
    assert len(records) == 2
    assert all(isinstance(r, FusionAttestation) for r in records)


# ── T215-CGVF-19: consensus_score() returns latest score ─────────────────────

def test_cgvf_19_consensus_score_method(engine):
    """T215-CGVF-19: consensus_score() returns float score from latest record."""
    with _mock_peers():
        att = engine.fuse()
    score = engine.consensus_score()
    assert score == att.consensus_score


# ── T215-CGVF-20: consensus_score() returns 0.0 on empty ledger ──────────────

def test_cgvf_20_consensus_score_empty(tmp_ledger):
    """T215-CGVF-20: consensus_score() returns 0.0 when ledger is empty."""
    eng = ConstitutionalGovernanceValidationFusion(ledger_path=tmp_ledger)
    assert eng.consensus_score() == 0.0


# ── T215-CGVF-21: CGVF-CERT-0 — certify() seals attestation ─────────────────

def test_cgvf_21_certify_seals(engine):
    """T215-CGVF-21: certify() produces human0_certified=True. CGVF-CERT-0."""
    with _mock_peers():
        att = engine.fuse()
    certified = engine.certify(att.fusion_id, certified_by="DUSTIN L REID")
    assert certified.human0_certified is True
    assert certified.certified_by == "DUSTIN L REID"
    assert certified.human0_required is False


# ── T215-CGVF-22: CGVF-CERT-0 — double-certify raises ───────────────────────

def test_cgvf_22_double_certify_raises(engine):
    """T215-CGVF-22: Re-certification raises CGVFCertError. CGVF-CERT-0."""
    with _mock_peers():
        att = engine.fuse()
    engine.certify(att.fusion_id, certified_by=GOVERNOR)
    # The certified record has a different fusion_id but same original_id concept
    # certify on the same original fusion_id should find the now-certified record
    # and raise on re-certify attempt
    with pytest.raises(CGVFCertError):
        engine.certify(att.fusion_id, certified_by=GOVERNOR)


# ── T215-CGVF-23: certify on unknown id raises CGVFError ─────────────────────

def test_cgvf_23_certify_unknown_raises(engine):
    """T215-CGVF-23: certify() on unknown fusion_id raises CGVFError."""
    with pytest.raises(CGVFError):
        engine.certify("nonexistent_id_" + "a" * 48, certified_by=GOVERNOR)


# ── T215-CGVF-24: CGVF-SCORE-0 — bad score raises CGVFScoreError ─────────────

def test_cgvf_24_score_validation():
    """T215-CGVF-24: FusionAttestation with score > 1.0 raises CGVFScoreError."""
    with pytest.raises(CGVFScoreError):
        FusionAttestation(
            fusion_id="a" * 64,
            timestamp_ns=time.time_ns(),
            peer_signals=[],
            consensus_score=1.5,  # invalid
            overall_status=FusionStatus.HEALTHY,
            human0_required=False,
            human0_certified=False,
            certified_by=None,
            prev_digest="0" * 64,
        )


# ── T215-CGVF-25: CGVF-IMMUT-0 — records property returns tuple ──────────────

def test_cgvf_25_records_immutable(engine):
    """T215-CGVF-25: records property returns a tuple. CGVF-IMMUT-0."""
    with _mock_peers():
        engine.fuse()
    assert isinstance(engine.records, tuple)


# ── T215-CGVF-26: Unavailable peer degrades score ────────────────────────────

def test_cgvf_26_unavailable_peer_degrades(engine, tmp_ledger):
    """T215-CGVF-26: Unavailable CGVA peer → score lower than all-healthy."""
    from dorkllm import constitutional_governance_validation_fusion as mod

    def failing_cgva():
        raise RuntimeError("CGVA unavailable")

    fake_queries = {
        "CGVA": failing_cgva,
        "CGVR": lambda: (1.0, "REMEDIATED"),
        "CGVE": lambda: (1.0, "COMPLIANT"),
        "CGPR": lambda: (1.0, "PROOF_PRESENT"),
    }
    with patch.object(mod, "_PEER_QUERIES", fake_queries):
        result = engine.fuse()

    # CGVA contributes 0.0 (weight 0.40), others contribute 1.0
    assert result.consensus_score < 1.0
    cgva_signal = next(s for s in result.peer_signals if s.peer_id == "CGVA")
    assert cgva_signal.available is False


# ── T215-CGVF-27: PeerSignal to_dict contains required keys ──────────────────

def test_cgvf_27_peer_signal_to_dict(engine):
    """T215-CGVF-27: PeerSignal.to_dict() contains all required keys."""
    with _mock_peers():
        result = engine.fuse()
    for signal in result.peer_signals:
        d = signal.to_dict()
        for key in ("peer_id", "raw_value", "normalised", "weight", "available"):
            assert key in d


# ── T215-CGVF-28: FusionAttestation to_dict is JSON serializable ─────────────

def test_cgvf_28_to_dict_json_serializable(engine):
    """T215-CGVF-28: FusionAttestation.to_dict() is fully JSON serializable."""
    with _mock_peers():
        result = engine.fuse()
    d = result.to_dict()
    serialized = json.dumps(d)
    assert len(serialized) > 0


# ── T215-CGVF-29: status() returns module info dict ──────────────────────────

def test_cgvf_29_status_returns_dict(engine):
    """T215-CGVF-29: status() returns dict with required keys."""
    with _mock_peers():
        engine.fuse()
    s = engine.status()
    for key in ("module", "innovation", "phase", "governor", "invariants"):
        assert key in s
    assert s["module"] == "CGVF"
    assert s["phase"] == 215
    assert len(s["invariants"]) == 12


# ── T215-CGVF-30: CGVF-ATOMIC-0 — ledger is JSONL (one record per line) ─────

def test_cgvf_30_ledger_is_jsonl(engine, tmp_ledger):
    """T215-CGVF-30: Ledger is valid JSONL — each line parseable independently."""
    with _mock_peers():
        for _ in range(3):
            engine.fuse()
    lines = [l.strip() for l in tmp_ledger.read_text().splitlines() if l.strip()]
    assert len(lines) == 3
    for line in lines:
        parsed = json.loads(line)
        assert "fusion_id" in parsed
        assert "consensus_score" in parsed
        assert "hmac_digest" in parsed
