"""
Phase 222 · INNOV-127 · ACDR — Autonomous Constitutional Drift Reporter
Test suite: 30 acceptance tests
InnovativeAI LLC · Governor: DUSTIN L REID

Test categories:
  DETECT (T222-DETECT-01..05) — Detection run execution & domain coverage
  ENTROPY (T222-ENTR-01..05)  — Entropy scoring and severity classification
  HMAC   (T222-HMAC-01..05)   — HMAC chain construction and verification
  CHAIN  (T222-CHAIN-01..03)  — Chain integrity traversal and replay
  HUMAN0 (T222-H0-01..04)     — HUMAN-0 quarantine and acknowledgment
  REPORT (T222-RPT-01..04)    — Report generation and remediation content
  API    (T222-API-01..04)    — FastAPI endpoint smoke tests
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest

from dorkllm.autonomous_constitutional_drift_reporter import (
    AutonomousConstitutionalDriftReporter,
    DriftSeverity,
    DriftEventType,
    DriftDomain,
    LedgerEntry,
    _CONSTITUTIONAL_DOMAINS,
    _HMAC_KEY,
)


# ── Fixture ───────────────────────────────────────────────────────────────────
@pytest.fixture
def engine(tmp_path):
    ledger = tmp_path / "acdr_drift_ledger.jsonl"
    state  = tmp_path / "acdr_state.json"
    return AutonomousConstitutionalDriftReporter(
        ledger_path=ledger, state_path=state
    )


@pytest.fixture
def engine_with_events(engine):
    """Engine pre-populated with a detection run."""
    contexts = {
        "CARE": {
            "expected_invariants": 10,
            "observed_invariants": 7,   # gap → event
        },
        "CGML": {
            "coherence_score":       0.60,
            "prior_coherence_score": 0.95,  # decay → event
        },
    }
    engine.run_detection(domain_contexts=contexts)
    return engine


@pytest.fixture
def engine_with_critical(engine):
    """Engine pre-populated with a CRITICAL authority breach."""
    contexts = {
        "CARE": {
            "authority_violations": ["UNSIGNED_PROMOTE_0001"],
        }
    }
    engine.run_detection(domain_contexts=contexts)
    return engine


# ══ DETECT category ══════════════════════════════════════════════════════════
@pytest.mark.phase222
class TestDetect:

    def test_T222_DETECT_01_run_returns_report(self, engine):
        """T222-DETECT-01: run_detection returns a DriftReport with correct structure."""
        report = engine.run_detection()
        assert report.report_id
        assert report.run_id
        assert isinstance(report.domains_evaluated, list)

    def test_T222_DETECT_02_all_domains_evaluated(self, engine):
        """T222-DETECT-02: ACDR-DETECT-0 — every registered domain appears in report."""
        report = engine.run_detection()
        for domain in _CONSTITUTIONAL_DOMAINS:
            assert domain in report.domains_evaluated

    def test_T222_DETECT_03_domain_count(self, engine):
        """T222-DETECT-03: exactly 7 constitutional domains evaluated."""
        report = engine.run_detection()
        assert len(report.domains_evaluated) == 7

    def test_T222_DETECT_04_nominal_run_zero_events(self, engine):
        """T222-DETECT-04: clean context produces no drift events."""
        report = engine.run_detection(domain_contexts={})
        assert len(report.events) == 0
        assert report.overall_severity == DriftSeverity.NOMINAL.value

    def test_T222_DETECT_05_events_generated_on_gap(self, engine):
        """T222-DETECT-05: invariant coverage gap produces at least one event."""
        report = engine.run_detection(domain_contexts={
            "ACSA": {"expected_invariants": 10, "observed_invariants": 5}
        })
        assert any(
            e.event_type == DriftEventType.INVARIANT_GAP.value
            for e in report.events
        )


# ══ ENTROPY category ══════════════════════════════════════════════════════════
@pytest.mark.phase222
class TestEntropy:

    def test_T222_ENTR_01_entropy_bounds(self, engine):
        """T222-ENTR-01: ACDR-ENTROPY-0 — entropy always in [0.0, 1.0]."""
        report = engine.run_detection(domain_contexts={
            "CARE": {"expected_invariants": 10, "observed_invariants": 0}
        })
        for ev in report.events:
            assert 0.0 <= ev.entropy <= 1.0

    def test_T222_ENTR_02_nominal_threshold(self, engine):
        """T222-ENTR-02: entropy < 0.20 maps to NOMINAL severity."""
        assert engine._entropy_to_severity(0.10) == DriftSeverity.NOMINAL

    def test_T222_ENTR_03_critical_threshold(self, engine):
        """T222-ENTR-03: entropy ≥ 0.85 maps to CRITICAL severity."""
        assert engine._entropy_to_severity(0.90) == DriftSeverity.CRITICAL

    def test_T222_ENTR_04_score_clamp_high(self, engine):
        """T222-ENTR-04: _score_entropy clamps values > 1.0 to 1.0."""
        assert engine._score_entropy(99.9) == 1.0

    def test_T222_ENTR_05_overall_entropy_non_negative(self, engine):
        """T222-ENTR-05: overall_entropy is always ≥ 0.0."""
        report = engine.run_detection()
        assert report.overall_entropy >= 0.0


# ══ HMAC category ═════════════════════════════════════════════════════════════
@pytest.mark.phase222
class TestHMAC:

    def test_T222_HMAC_01_entry_seal_produces_digest(self, engine):
        """T222-HMAC-01: sealing a LedgerEntry produces a non-empty hmac digest."""
        entry = LedgerEntry(
            seq=1, entry_id=str(uuid.uuid4()),
            entry_type="TEST", payload={"x": 1},
            timestamp=time.time(), prev_hmac="GENESIS",
        ).seal()
        assert len(entry.hmac) == 64  # sha256 hex = 64 chars

    def test_T222_HMAC_02_verify_passes_on_unmodified(self, engine):
        """T222-HMAC-02: ACDR-HMAC-0 — verify() returns True for unmodified entry."""
        entry = LedgerEntry(
            seq=1, entry_id=str(uuid.uuid4()),
            entry_type="TEST", payload={"x": 1},
            timestamp=time.time(), prev_hmac="GENESIS",
        ).seal()
        assert entry.verify() is True

    def test_T222_HMAC_03_verify_fails_on_tamper(self, engine):
        """T222-HMAC-03: tampering with payload breaks verify()."""
        entry = LedgerEntry(
            seq=1, entry_id=str(uuid.uuid4()),
            entry_type="TEST", payload={"x": 1},
            timestamp=time.time(), prev_hmac="GENESIS",
        ).seal()
        entry.payload["x"] = 99
        assert entry.verify() is False

    def test_T222_HMAC_04_detection_run_appends_audit_entry(self, engine):
        """T222-HMAC-04: each detection run produces at least one ledger entry."""
        before = engine._seq
        engine.run_detection()
        assert engine._seq > before

    def test_T222_HMAC_05_chain_head_advances(self, engine):
        """T222-HMAC-05: ACDR-HMAC-0 — chain head changes after each detection run."""
        head1 = engine._chain_head
        engine.run_detection()
        head2 = engine._chain_head
        assert head1 != head2


# ══ CHAIN category ════════════════════════════════════════════════════════════
@pytest.mark.phase222
class TestChain:

    def test_T222_CHAIN_01_empty_ledger_is_valid(self, engine):
        """T222-CHAIN-01: ACDR-CHAIN-0 — empty ledger reports valid."""
        result = engine.verify_chain()
        assert result["valid"] is True
        assert result["entries"] == 0

    def test_T222_CHAIN_02_chain_valid_after_run(self, engine):
        """T222-CHAIN-02: ACDR-CHAIN-0 — chain remains valid after detection run."""
        engine.run_detection()
        result = engine.verify_chain()
        assert result["valid"] is True
        assert result["entries"] > 0

    def test_T222_CHAIN_03_chain_valid_after_multiple_runs(self, engine):
        """T222-CHAIN-03: ACDR-REPLAY-0 — chain is valid across multiple detection runs."""
        for _ in range(3):
            engine.run_detection(domain_contexts={
                "ACSA": {"expected_invariants": 10, "observed_invariants": 8}
            })
        result = engine.verify_chain()
        assert result["valid"] is True


# ══ HUMAN-0 category ══════════════════════════════════════════════════════════
@pytest.mark.phase222
class TestHuman0:

    def test_T222_H0_01_critical_event_enters_quarantine(self, engine_with_critical):
        """T222-H0-01: ACDR-HUMAN0-0 — CRITICAL events are quarantined automatically."""
        quarantine = engine_with_critical.get_quarantine()
        assert quarantine["count"] > 0

    def test_T222_H0_02_ack_removes_from_quarantine(self, engine_with_critical):
        """T222-H0-02: ACDR-HUMAN0-0 — acknowledgment lifts quarantine."""
        q = engine_with_critical.get_quarantine()
        assert q["count"] > 0
        event_id = q["quarantined_events"][0]["event_id"]
        result   = engine_with_critical.human0_acknowledge(event_id)
        assert result["status"] == "ACKNOWLEDGED"
        assert engine_with_critical.get_quarantine()["count"] == q["count"] - 1

    def test_T222_H0_03_ack_unknown_event_returns_not_found(self, engine):
        """T222-H0-03: ACDR-HUMAN0-0 — acking unknown event returns NOT_FOUND."""
        result = engine.human0_acknowledge(str(uuid.uuid4()))
        assert result["status"] == "NOT_FOUND"

    def test_T222_H0_04_ack_sealed_in_ledger(self, engine_with_critical):
        """T222-H0-04: ACDR-AUDIT-0 — acknowledgment is ledger-sealed."""
        before = engine_with_critical._seq
        q      = engine_with_critical.get_quarantine()
        eid    = q["quarantined_events"][0]["event_id"]
        engine_with_critical.human0_acknowledge(eid)
        assert engine_with_critical._seq > before


# ══ REPORT category ═══════════════════════════════════════════════════════════
@pytest.mark.phase222
class TestReport:

    def test_T222_RPT_01_report_has_remediation(self, engine_with_events):
        """T222-RPT-01: ACDR-REPORT-0 — events carry remediation recommendations."""
        report_data = engine_with_events.get_report()
        for ev in report_data["events"]:
            assert isinstance(ev["remediation"], list)
            assert len(ev["remediation"]) >= 1

    def test_T222_RPT_02_report_governor_field(self, engine):
        """T222-RPT-02: drift report includes HUMAN-0 governor attribution."""
        engine.run_detection()
        report = engine.get_report()
        assert report["governor"] == "DUSTIN L REID"

    def test_T222_RPT_03_report_innovation_field(self, engine):
        """T222-RPT-03: drift report carries INNOV-127 attribution."""
        engine.run_detection()
        report = engine.get_report()
        assert report["innovation"] == "INNOV-127"

    def test_T222_RPT_04_report_chain_head_present(self, engine):
        """T222-RPT-04: ACDR-REPLAY-0 — report includes chain head for replay."""
        engine.run_detection()
        report = engine.get_report()
        assert "chain_head" in report


# ══ API category ══════════════════════════════════════════════════════════════
@pytest.mark.phase222
class TestAPI:

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from app.api.acdr import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_T222_API_01_status_200(self, client):
        """T222-API-01: GET /acdr/status returns 200."""
        r = client.get("/acdr/status")
        assert r.status_code == 200
        data = r.json()
        assert data["engine"] == "ACDR"

    def test_T222_API_02_detect_200(self, client):
        """T222-API-02: POST /acdr/detect returns 200 and report fields."""
        r = client.post("/acdr/detect", json={})
        assert r.status_code == 200
        data = r.json()
        assert "report_id" in data
        assert "overall_entropy" in data

    def test_T222_API_03_chain_verify_200(self, client):
        """T222-API-03: GET /acdr/chain/verify returns 200 on intact chain."""
        r = client.get("/acdr/chain/verify")
        assert r.status_code == 200
        assert r.json()["status"] == "CHAIN_INTACT"

    def test_T222_API_04_quarantine_200(self, client):
        """T222-API-04: GET /acdr/quarantine returns 200 and count field."""
        r = client.get("/acdr/quarantine")
        assert r.status_code == 200
        assert "count" in r.json()
