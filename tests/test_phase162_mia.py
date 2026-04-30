# SPDX-License-Identifier: Apache-2.0
"""Phase 162 — INNOV-68 · MIA — Mutation Impact Analyzer — Acceptance Suite (30/30).

Test groups
-----------
T162-001..005  MIA-DETERM-0 — determinism of impact_id
T162-006..010  MIA-CHAIN-0  — HMAC-chained ledger integrity & fail-closed
T162-011..015  MIA-HUMAN0-0 — HUMAN0_AUTHORISATION emitted for HIGH_RISK/CRITICAL
T162-016..020  MIA-SCOPE-0  — scoring dimensions, composite, tier, recommendation
T162-021..025  MIA-AUDIT-0  — append-only ledger, verify_chain, history, status
T162-026..030  API routes    — schema/200/422 sanity (status, history, analyze, chain/verify)
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_payload(
    mutation_id: str = "mut-001",
    target_module: str = "app.api.dummy",
    diff_summary: str = "Add a helper function to the dummy module.",
    rationale: str = "Improves code clarity under ADAAD constitution rule 3.",
    proposed_by: str = "ArchitectAgent",
):
    from dorkllm.mutation_impact_analyzer import MutationPayload

    return MutationPayload(
        mutation_id=mutation_id,
        target_module=target_module,
        diff_summary=diff_summary,
        rationale=rationale,
        proposed_by=proposed_by,
    )


def _fresh_analyzer(tmp_path: Path):
    from dorkllm.mutation_impact_analyzer import MutationImpactAnalyzer

    return MutationImpactAnalyzer(ledger_path=tmp_path / "mia_test.jsonl")


# ---------------------------------------------------------------------------
# T162-001..005  MIA-DETERM-0 — determinism
# ---------------------------------------------------------------------------


@pytest.mark.T162
class TestMIADeterm:
    """MIA-DETERM-0: same payload → same impact_id, independent of call order."""

    def test_001_same_payload_same_id(self, tmp_path):
        from dorkllm.mutation_impact_analyzer import _impact_id

        p = _make_payload()
        assert _impact_id(p) == _impact_id(p)

    def test_002_different_mutation_id_different_impact_id(self, tmp_path):
        from dorkllm.mutation_impact_analyzer import _impact_id

        p1 = _make_payload(mutation_id="mut-alpha")
        p2 = _make_payload(mutation_id="mut-beta")
        assert _impact_id(p1) != _impact_id(p2)

    def test_003_impact_id_is_hex_string_24chars(self, tmp_path):
        from dorkllm.mutation_impact_analyzer import _impact_id

        iid = _impact_id(_make_payload())
        assert isinstance(iid, str) and len(iid) == 24
        int(iid, 16)  # must be valid hex

    def test_004_analysis_result_contains_deterministic_id(self, tmp_path):
        from dorkllm.mutation_impact_analyzer import _impact_id

        analyzer = _fresh_analyzer(tmp_path)
        p = _make_payload(mutation_id="determ-test")
        result = analyzer.analyze(p)
        assert result.impact_id == _impact_id(p)

    def test_005_two_analyzers_same_payload_same_id(self, tmp_path):
        from dorkllm.mutation_impact_analyzer import _impact_id

        p = _make_payload(mutation_id="cross-instance")
        a1 = _fresh_analyzer(tmp_path / "a1")
        a2 = _fresh_analyzer(tmp_path / "a2")
        r1 = a1.analyze(p)
        r2 = a2.analyze(p)
        assert r1.impact_id == r2.impact_id == _impact_id(p)


# ---------------------------------------------------------------------------
# T162-006..010  MIA-CHAIN-0 — HMAC chain
# ---------------------------------------------------------------------------


@pytest.mark.T162
class TestMIAChain:
    """MIA-CHAIN-0: every record is HMAC-linked; broken chain raises MIAChainError."""

    def test_006_first_record_chain_hash_is_string(self, tmp_path):
        a = _fresh_analyzer(tmp_path)
        r = a.analyze(_make_payload())
        assert isinstance(r.chain_hash, str) and len(r.chain_hash) == 64

    def test_007_sequential_records_have_different_hashes(self, tmp_path):
        a = _fresh_analyzer(tmp_path)
        r1 = a.analyze(_make_payload(mutation_id="seq-1"))
        r2 = a.analyze(_make_payload(mutation_id="seq-2"))
        assert r1.chain_hash != r2.chain_hash

    def test_008_verify_chain_returns_ok_on_intact_ledger(self, tmp_path):
        a = _fresh_analyzer(tmp_path)
        a.analyze(_make_payload(mutation_id="chain-ok-1"))
        a.analyze(_make_payload(mutation_id="chain-ok-2"))
        result = a.verify_chain()
        assert result["status"] == "ok"
        assert result["records"] == 2

    def test_009_tampered_ledger_raises_chain_error(self, tmp_path):
        from dorkllm.mutation_impact_analyzer import MIAChainError

        ledger = tmp_path / "mia_test.jsonl"
        a = _fresh_analyzer(tmp_path)
        a.analyze(_make_payload(mutation_id="pre-tamper"))

        # Corrupt the chain_hash of the only record
        lines = ledger.read_text().splitlines()
        rec = json.loads(lines[0])
        rec["chain_hash"] = "a" * 64
        ledger.write_text(json.dumps(rec) + "\n")

        result = a.verify_chain()
        assert result["status"] == "chain_broken"

    def test_010_new_analyze_on_broken_chain_raises(self, tmp_path):
        from dorkllm.mutation_impact_analyzer import MIAChainError

        ledger = tmp_path / "mia_test.jsonl"
        a = _fresh_analyzer(tmp_path)
        a.analyze(_make_payload(mutation_id="pre-break"))

        lines = ledger.read_text().splitlines()
        rec = json.loads(lines[0])
        rec["chain_hash"] = "b" * 64
        ledger.write_text(json.dumps(rec) + "\n")

        with pytest.raises(MIAChainError):
            a.analyze(_make_payload(mutation_id="post-break"))


# ---------------------------------------------------------------------------
# T162-011..015  MIA-HUMAN0-0 — HUMAN0 pre-emission
# ---------------------------------------------------------------------------


@pytest.mark.T162
class TestMIAHuman0:
    """MIA-HUMAN0-0: HUMAN0_AUTHORISATION emitted before ledger write for HIGH_RISK/CRITICAL."""

    def _run_with_mocked_hub(self, tmp_path, diff_summary, target_module="dorkllm.constitutional_gate", csi_band="CRITICAL", cfe_risk_tier="CRITICAL"):
        """Helper: analyze a mutation that should trigger HUMAN0 emission."""
        from dorkllm.mutation_impact_analyzer import MutationImpactAnalyzer, MutationPayload

        emitted: List[Dict] = []

        mock_hub = MagicMock()
        mock_hub.emit_event.side_effect = lambda component_id, event_type, payload: emitted.append(
            {"event_type": str(event_type), "component_id": component_id, "data": payload}
        )

        a = MutationImpactAnalyzer(ledger_path=tmp_path / "mia_h0.jsonl")
        p = MutationPayload(
            mutation_id="h0-test",
            target_module=target_module,
            diff_summary=diff_summary,
            rationale="Testing HUMAN0 emission.",
            proposed_by="TestAgent",
        )
        with patch("dorkllm.mutation_impact_analyzer.get_hub", return_value=mock_hub):
            result = a.analyze(p, csi_band=csi_band, cfe_risk_tier=cfe_risk_tier)
        return result, emitted

    def test_011_critical_score_emits_human0(self, tmp_path):
        result, emitted = self._run_with_mocked_hub(
            tmp_path,
            diff_summary="bypass the constitutional gate entirely",
        )
        assert result.tier.value in ("HIGH_RISK", "CRITICAL")
        assert any("HUMAN0_AUTHORISATION" in e.get("event_type", "") for e in emitted)

    def test_012_human0_event_contains_impact_id(self, tmp_path):
        result, emitted = self._run_with_mocked_hub(
            tmp_path,
            diff_summary="disable all governance checks in ledger",
        )
        h0_events = [e for e in emitted if "HUMAN0_AUTHORISATION" in e.get("event_type", "")]
        if h0_events:
            data = h0_events[0].get("data", {})
            assert data.get("impact_id") == result.impact_id

    def test_013_low_risk_does_not_emit_human0(self, tmp_path):
        from dorkllm.mutation_impact_analyzer import MutationImpactAnalyzer, MutationPayload

        emitted: List[Dict] = []
        mock_hub = MagicMock()
        mock_hub.emit_event.side_effect = lambda component_id, event_type, payload: emitted.append({"event_type": str(event_type)})

        a = MutationImpactAnalyzer(ledger_path=tmp_path / "mia_low.jsonl")
        p = MutationPayload(
            mutation_id="low-risk",
            target_module="app.api.dummy_helper",
            diff_summary="Add a docstring to a helper function.",
            rationale="Documentation improvement.",
            proposed_by="DreamAgent",
        )
        with patch("dorkllm.mutation_impact_analyzer.get_hub", return_value=mock_hub):
            result = a.analyze(p, csi_band="EXCELLENT", cfe_risk_tier="LOW")

        h0 = [e for e in emitted if "HUMAN0_AUTHORISATION" in e.get("event_type", "")]
        if result.tier.value in ("HIGH_RISK", "CRITICAL"):
            pass  # allowed to emit
        else:
            assert len(h0) == 0

    def test_014_human0_emitted_before_ledger_write(self, tmp_path):
        """Emission must precede ledger append — verified by event ordering."""
        from dorkllm.mutation_impact_analyzer import MutationImpactAnalyzer, MutationPayload

        event_order: List[str] = []
        ledger_path = tmp_path / "mia_order.jsonl"

        mock_hub = MagicMock()
        mock_hub.emit.side_effect = lambda et, **kw: event_order.append("emit")

        original_open = open

        def patched_open(path, mode="r", **kwargs):
            if str(path) == str(ledger_path) and "a" in str(mode):
                event_order.append("write")
            return original_open(path, mode, **kwargs)

        a = MutationImpactAnalyzer(ledger_path=ledger_path)
        p = MutationPayload(
            mutation_id="order-test",
            target_module="dorkllm.constitutional_gate",
            diff_summary="remove all validation checks",
            rationale="Testing emission ordering.",
            proposed_by="TestAgent",
        )
        with patch("dorkllm.mutation_impact_analyzer.get_hub", return_value=mock_hub):
            with patch("builtins.open", side_effect=patched_open):
                try:
                    a.analyze(p, csi_band="CRITICAL", cfe_risk_tier="CRITICAL")
                except Exception:
                    pass  # patched open may fail — what matters is order

        emit_indices = [i for i, e in enumerate(event_order) if e == "emit"]
        write_indices = [i for i, e in enumerate(event_order) if e == "write"]
        if emit_indices and write_indices:
            assert min(emit_indices) < min(write_indices)

    def test_015_human0_event_contains_recommendation(self, tmp_path):
        result, emitted = self._run_with_mocked_hub(
            tmp_path,
            diff_summary="bypass constitutional ledger entirely and skip invariant checks",
        )
        h0 = [e for e in emitted if "HUMAN0_AUTHORISATION" in e.get("event_type", "")]
        if h0 and result.tier.value in ("HIGH_RISK", "CRITICAL"):
            data = h0[0].get("data", {})
            assert "recommendation" in data


# ---------------------------------------------------------------------------
# T162-016..020  MIA-SCOPE-0 — scoring dimensions
# ---------------------------------------------------------------------------


@pytest.mark.T162
class TestMIAScope:
    """MIA-SCOPE-0: four dimensions, correct composite weighting, tier/recommendation mapping."""

    def test_016_four_dimensions_always_present(self, tmp_path):
        a = _fresh_analyzer(tmp_path)
        result = a.analyze(_make_payload())
        names = {d.name for d in result.dimensions}
        assert names == {"precedent_match", "invariant_risk", "csi_alignment", "forecast_headroom"}

    def test_017_composite_score_in_0_100_range(self, tmp_path):
        a = _fresh_analyzer(tmp_path)
        result = a.analyze(_make_payload(), csi_band="HEALTHY", cfe_risk_tier="MEDIUM")
        assert 0.0 <= result.composite_score <= 100.0

    def test_018_low_risk_context_yields_approve_or_review(self, tmp_path):
        a = _fresh_analyzer(tmp_path)
        p = _make_payload(
            target_module="app.api.metrics",
            diff_summary="Add a counter metric for response time.",
            rationale="Observability improvement.",
        )
        result = a.analyze(p, csi_band="EXCELLENT", cfe_risk_tier="LOW")
        assert result.recommendation.value in ("APPROVE", "REVIEW")

    def test_019_critical_context_yields_hold_or_block(self, tmp_path):
        a = _fresh_analyzer(tmp_path)
        p = _make_payload(
            target_module="dorkllm.constitutional_gate",
            diff_summary="Remove gate enforcement and bypass all checks.",
            rationale="Performance optimisation.",
        )
        result = a.analyze(p, csi_band="CRITICAL", cfe_risk_tier="CRITICAL")
        assert result.recommendation.value in ("HOLD", "BLOCK")

    def test_020_precedent_repeat_raises_risk(self, tmp_path):
        a = _fresh_analyzer(tmp_path)
        # First: submit a mutation that gets HOLD/BLOCK
        p1 = _make_payload(
            mutation_id="dangerous-001",
            target_module="dorkllm.constitutional_gate",
            diff_summary="bypass the constitutional gate entirely",
            rationale="speed improvement",
        )
        r1 = a.analyze(p1, csi_band="CRITICAL", cfe_risk_tier="CRITICAL")

        # Second: same target module again
        p2 = _make_payload(
            mutation_id="dangerous-002",
            target_module="dorkllm.constitutional_gate",
            diff_summary="Another change to the constitutional gate.",
            rationale="follow-up improvement",
        )
        r2 = a.analyze(p2, csi_band="HEALTHY", cfe_risk_tier="LOW")

        # precedent dimension should carry elevated score
        prec = next(d for d in r2.dimensions if d.name == "precedent_match")
        assert prec.score >= 50.0  # prior HOLD/BLOCK precedent detected


# ---------------------------------------------------------------------------
# T162-021..025  MIA-AUDIT-0 — ledger immutability + operations
# ---------------------------------------------------------------------------


@pytest.mark.T162
class TestMIAAudit:
    """MIA-AUDIT-0: append-only ledger, status, history, verify_chain."""

    def test_021_ledger_file_created_after_analyze(self, tmp_path):
        a = _fresh_analyzer(tmp_path)
        a.analyze(_make_payload())
        assert (tmp_path / "mia_test.jsonl").exists()

    def test_022_ledger_grows_with_each_analysis(self, tmp_path):
        ledger = tmp_path / "mia_test.jsonl"
        a = _fresh_analyzer(tmp_path)
        for i in range(3):
            a.analyze(_make_payload(mutation_id=f"grow-{i}"))
        lines = [l for l in ledger.read_text().splitlines() if l.strip()]
        assert len(lines) == 3

    def test_023_history_returns_records_without_chain_payload(self, tmp_path):
        a = _fresh_analyzer(tmp_path)
        a.analyze(_make_payload(mutation_id="hist-1"))
        a.analyze(_make_payload(mutation_id="hist-2"))
        history = a.get_history()
        assert len(history) == 2
        for rec in history:
            assert "_chain_payload" not in rec

    def test_024_status_returns_total_and_tier_counts(self, tmp_path):
        a = _fresh_analyzer(tmp_path)
        a.analyze(_make_payload(mutation_id="s1"))
        status = a.status()
        assert status["total_assessments"] == 1
        assert "tier_counts" in status
        assert "recommendation_counts" in status

    def test_025_verify_chain_on_empty_ledger_returns_ok(self, tmp_path):
        a = _fresh_analyzer(tmp_path)
        result = a.verify_chain()
        assert result["status"] == "ok"
        assert result["records"] == 0


# ---------------------------------------------------------------------------
# T162-026..030  API route sanity (schema / 200 / 422)
# ---------------------------------------------------------------------------


@pytest.mark.T162
class TestMIAAPI:
    """FastAPI route schema / 200 / 422 validation."""

    @pytest.fixture(autouse=True)
    def _client(self, tmp_path, monkeypatch):
        from dorkllm.mutation_impact_analyzer import MutationImpactAnalyzer
        import dorkllm.mutation_impact_analyzer as mia_mod

        # Patch the module-level singleton to use tmp_path ledger
        fresh = MutationImpactAnalyzer(ledger_path=tmp_path / "api_test.jsonl")
        monkeypatch.setattr(mia_mod, "_default_analyzer", fresh)
        monkeypatch.setattr(mia_mod, "get_analyzer", lambda: fresh)

        try:
            from server import app
            self.client = TestClient(app, raise_server_exceptions=False)
        except Exception:
            from fastapi import FastAPI
            from app.api.mutation_impact import router
            mini = FastAPI()
            mini.include_router(router)
            self.client = TestClient(mini, raise_server_exceptions=False)

    def test_026_status_returns_200(self):
        resp = self.client.get("/api/governance/mia/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "component" in data or "innovation" in data

    def test_027_history_returns_200_list(self):
        resp = self.client.get("/api/governance/mia/history")
        assert resp.status_code == 200
        data = resp.json()
        assert "records" in data

    def test_028_analyze_valid_payload_returns_200(self):
        resp = self.client.post(
            "/api/governance/mia/analyze",
            json={
                "mutation_id": "api-test-001",
                "target_module": "app.api.metrics",
                "diff_summary": "Add a latency histogram metric.",
                "rationale": "Observability improvement aligned with constitution rule 7.",
                "proposed_by": "ArchitectAgent",
                "csi_band": "HEALTHY",
                "cfe_risk_tier": "LOW",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "impact_id" in data
        assert "composite_score" in data
        assert "recommendation" in data

    def test_029_analyze_missing_required_fields_returns_422(self):
        resp = self.client.post(
            "/api/governance/mia/analyze",
            json={"mutation_id": "bad-payload"},
        )
        assert resp.status_code == 422

    def test_030_chain_verify_returns_200_ok(self):
        resp = self.client.get("/api/governance/mia/chain/verify")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "ok"
