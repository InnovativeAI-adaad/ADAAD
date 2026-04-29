# SPDX-License-Identifier: Apache-2.0
"""Phase 161 · INNOV-67 · CFE — Constitutional Forecast Engine — acceptance tests.

Invariant coverage
==================
CFE-DETERM-0 : forecast_id determinism from canonical payload (T01–T05)
CFE-CHAIN-0  : HMAC chain integrity, append-only, chain-break detection (T06–T12)
CFE-WINDOW-0 : < 3 data-point rejection (T13–T16)
CFE-HUMAN0-0 : CGTH HUMAN0_AUTHORISATION for HIGH_RISK / CRITICAL (T17–T21)
Risk tier    : LOW / MEDIUM / HIGH_RISK / CRITICAL classification (T22–T26)
API surface  : four-route schema / 200 / 422 sanity (T27–T30)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
from pathlib import Path
from typing import List
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _fresh_engine(tmpdir: str, horizon: int = 5):
    from dorkllm.constitutional_forecast import ConstitutionalForecastEngine
    return ConstitutionalForecastEngine(
        ledger_path=Path(tmpdir) / "cfe_ledger.jsonl",
        horizon_epochs=horizon,
    )


def _mock_hub():
    m = MagicMock()
    m.emit.return_value = None
    return m


# ===========================================================================
# CFE-DETERM-0 — Determinism (T01–T05)
# ===========================================================================

class TestCFEDeterminism:
    def test_T01_same_window_same_id(self, tmp_path):
        """T01: identical windows produce identical forecast_id."""
        window = [0.2, 0.25, 0.3, 0.35]
        e1 = _fresh_engine(str(tmp_path / "e1"))
        e2 = _fresh_engine(str(tmp_path / "e2"))
        with patch("dorkllm.constitutional_forecast.get_hub", return_value=_mock_hub()):
            r1 = e1.forecast(window)
            r2 = e2.forecast(window)
        assert r1.forecast_id == r2.forecast_id, "T01: forecast_id must be deterministic"

    def test_T02_different_window_different_id(self, tmp_path):
        """T02: different windows produce different forecast_ids."""
        e = _fresh_engine(str(tmp_path))
        with patch("dorkllm.constitutional_forecast.get_hub", return_value=_mock_hub()):
            r1 = e.forecast([0.1, 0.2, 0.3])
            r2 = e.forecast([0.4, 0.5, 0.6])
        assert r1.forecast_id != r2.forecast_id

    def test_T03_forecast_id_is_sha256_hex(self, tmp_path):
        """T03: forecast_id is a 64-hex-char SHA-256 string."""
        e = _fresh_engine(str(tmp_path))
        with patch("dorkllm.constitutional_forecast.get_hub", return_value=_mock_hub()):
            r = e.forecast([0.1, 0.2, 0.3])
        assert len(r.forecast_id) == 64
        assert all(c in "0123456789abcdef" for c in r.forecast_id)

    def test_T04_metadata_excluded_from_id(self, tmp_path):
        """T04: metadata does not affect forecast_id (CFE-DETERM-0 canon)."""
        e1 = _fresh_engine(str(tmp_path / "m1"))
        e2 = _fresh_engine(str(tmp_path / "m2"))
        window = [0.3, 0.35, 0.4, 0.45]
        with patch("dorkllm.constitutional_forecast.get_hub", return_value=_mock_hub()):
            r1 = e1.forecast(window, metadata={"tag": "alpha"})
            r2 = e2.forecast(window, metadata={"tag": "omega"})
        assert r1.forecast_id == r2.forecast_id

    def test_T05_horizon_change_changes_id(self, tmp_path):
        """T05: different horizon_epochs yields different forecast_id."""
        window = [0.2, 0.3, 0.4]
        e1 = _fresh_engine(str(tmp_path / "h1"), horizon=3)
        e2 = _fresh_engine(str(tmp_path / "h2"), horizon=10)
        with patch("dorkllm.constitutional_forecast.get_hub", return_value=_mock_hub()):
            r1 = e1.forecast(window)
            r2 = e2.forecast(window)
        assert r1.forecast_id != r2.forecast_id


# ===========================================================================
# CFE-CHAIN-0 — HMAC chain integrity (T06–T12)
# ===========================================================================

class TestCFEChain:
    def test_T06_first_entry_prev_digest_is_chain_root(self, tmp_path):
        """T06: first ledger entry prev_digest == '0'*64."""
        e = _fresh_engine(str(tmp_path))
        with patch("dorkllm.constitutional_forecast.get_hub", return_value=_mock_hub()):
            r = e.forecast([0.1, 0.2, 0.3])
        assert r.prev_digest == "0" * 64

    def test_T07_chained_entries_link_correctly(self, tmp_path):
        """T07: second entry prev_digest == first entry digest."""
        e = _fresh_engine(str(tmp_path))
        with patch("dorkllm.constitutional_forecast.get_hub", return_value=_mock_hub()):
            r1 = e.forecast([0.1, 0.2, 0.3])
            r2 = e.forecast([0.15, 0.25, 0.35])
        assert r2.prev_digest == r1.digest

    def test_T08_verify_chain_clean_ledger(self, tmp_path):
        """T08: verify_chain returns True on a clean ledger."""
        e = _fresh_engine(str(tmp_path))
        with patch("dorkllm.constitutional_forecast.get_hub", return_value=_mock_hub()):
            e.forecast([0.1, 0.2, 0.3])
            e.forecast([0.2, 0.3, 0.4])
        assert e.verify_chain() is True

    def test_T09_tampered_digest_raises_chain_error(self, tmp_path):
        """T09: tampering the first entry's digest raises CFEChainError."""
        from dorkllm.constitutional_forecast import CFEChainError
        ledger = Path(tmp_path) / "cfe_ledger.jsonl"
        e = ConstitutionalForecastEngine(ledger_path=ledger)
        with patch("dorkllm.constitutional_forecast.get_hub", return_value=_mock_hub()):
            e.forecast([0.1, 0.2, 0.3])
        # tamper
        lines = ledger.read_text().strip().splitlines()
        rec = json.loads(lines[0])
        rec["digest"] = "deadbeef" * 8
        ledger.write_text(json.dumps(rec) + "\n")
        e2 = ConstitutionalForecastEngine(ledger_path=ledger)
        with pytest.raises(CFEChainError):
            e2.verify_chain()

    def test_T10_tampered_body_raises_chain_error(self, tmp_path):
        """T10: tampering entry body (not digest) raises CFEChainError."""
        from dorkllm.constitutional_forecast import CFEChainError, ConstitutionalForecastEngine
        ledger = Path(tmp_path) / "cfe_ledger.jsonl"
        e = ConstitutionalForecastEngine(ledger_path=ledger)
        with patch("dorkllm.constitutional_forecast.get_hub", return_value=_mock_hub()):
            e.forecast([0.1, 0.2, 0.3])
        lines = ledger.read_text().strip().splitlines()
        rec = json.loads(lines[0])
        rec["forecast_pressure"] = 0.9999  # tamper body
        ledger.write_text(json.dumps(rec) + "\n")
        e2 = ConstitutionalForecastEngine(ledger_path=ledger)
        with pytest.raises(CFEChainError):
            e2.verify_chain()

    def test_T11_chain_method_returns_all_entries(self, tmp_path):
        """T11: chain() returns all persisted entries."""
        e = _fresh_engine(str(tmp_path))
        with patch("dorkllm.constitutional_forecast.get_hub", return_value=_mock_hub()):
            for i in range(4):
                e.forecast([0.1 + i * 0.05, 0.2 + i * 0.05, 0.3 + i * 0.05])
        assert len(e.chain()) == 4

    def test_T12_hmac_compare_digest_used(self, tmp_path):
        """T12: verify_chain uses hmac.compare_digest (AUTH-CT-0 compliance)."""
        import dorkllm.constitutional_forecast as mod
        src = Path(mod.__file__).read_text()
        assert "hmac.compare_digest" in src, "AUTH-CT-0: must use hmac.compare_digest"


# ===========================================================================
# CFE-WINDOW-0 — Minimum window enforcement (T13–T16)
# ===========================================================================

class TestCFEWindow:
    def test_T13_zero_points_raises(self, tmp_path):
        """T13: empty window raises CFEWindowError."""
        from dorkllm.constitutional_forecast import CFEWindowError
        e = _fresh_engine(str(tmp_path))
        with pytest.raises(CFEWindowError):
            e.forecast([])

    def test_T14_one_point_raises(self, tmp_path):
        """T14: single-point window raises CFEWindowError."""
        from dorkllm.constitutional_forecast import CFEWindowError
        e = _fresh_engine(str(tmp_path))
        with pytest.raises(CFEWindowError):
            e.forecast([0.5])

    def test_T15_two_points_raises(self, tmp_path):
        """T15: two-point window raises CFEWindowError."""
        from dorkllm.constitutional_forecast import CFEWindowError
        e = _fresh_engine(str(tmp_path))
        with pytest.raises(CFEWindowError):
            e.forecast([0.3, 0.4])

    def test_T16_three_points_succeeds(self, tmp_path):
        """T16: exactly three points is the minimum that succeeds."""
        from dorkllm.constitutional_forecast import CFEWindowError
        e = _fresh_engine(str(tmp_path))
        with patch("dorkllm.constitutional_forecast.get_hub", return_value=_mock_hub()):
            r = e.forecast([0.2, 0.3, 0.4])
        assert r.window_size == 3


# ===========================================================================
# CFE-HUMAN0-0 — CGTH HUMAN0_AUTHORISATION (T17–T21)
# ===========================================================================

class TestCFEHuman0:
    def _high_risk_window(self) -> List[float]:
        return [0.6, 0.72, 0.80, 0.88]  # steep rise → HIGH_RISK/CRITICAL

    def test_T17_high_risk_emits_human0(self, tmp_path):
        """T17: HIGH_RISK/CRITICAL forecast emits HUMAN0_AUTHORISATION before write."""
        from dorkllm.telemetry_hub import CGTHEventType
        hub = _mock_hub()
        e = _fresh_engine(str(tmp_path))
        with patch("dorkllm.constitutional_forecast.get_hub", return_value=hub):
            e.forecast(self._high_risk_window())
        calls = [c for c in hub.emit.call_args_list
                 if c.kwargs.get("event_type") == CGTHEventType.HUMAN0_AUTHORISATION
                 or (c.args and CGTHEventType.HUMAN0_AUTHORISATION in c.args)]
        assert len(calls) >= 1, "T17: HUMAN0_AUTHORISATION must be emitted for HIGH_RISK"

    def test_T18_low_risk_no_human0(self, tmp_path):
        """T18: LOW risk forecast does not emit HUMAN0_AUTHORISATION."""
        from dorkllm.telemetry_hub import CGTHEventType
        hub = _mock_hub()
        e = _fresh_engine(str(tmp_path))
        low_window = [0.1, 0.12, 0.11]
        with patch("dorkllm.constitutional_forecast.get_hub", return_value=hub):
            e.forecast(low_window)
        calls = [c for c in hub.emit.call_args_list
                 if CGTHEventType.HUMAN0_AUTHORISATION in str(c)]
        assert len(calls) == 0, "T18: LOW risk must not emit HUMAN0_AUTHORISATION"

    def test_T19_human0_payload_contains_forecast_id(self, tmp_path):
        """T19: HUMAN0_AUTHORISATION payload includes forecast_id."""
        hub = _mock_hub()
        e = _fresh_engine(str(tmp_path))
        with patch("dorkllm.constitutional_forecast.get_hub", return_value=hub):
            r = e.forecast(self._high_risk_window())
        payload_str = str(hub.emit.call_args_list)
        assert r.forecast_id in payload_str, "T19: forecast_id must appear in HUMAN0 payload"

    def test_T20_critical_forecast_emits_human0(self, tmp_path):
        """T20: explicitly CRITICAL pressure emits HUMAN0_AUTHORISATION."""
        from dorkllm.telemetry_hub import CGTHEventType
        hub = _mock_hub()
        e = _fresh_engine(str(tmp_path))
        critical_window = [0.7, 0.82, 0.91, 0.96]
        with patch("dorkllm.constitutional_forecast.get_hub", return_value=hub):
            e.forecast(critical_window)
        calls = [c for c in hub.emit.call_args_list
                 if CGTHEventType.HUMAN0_AUTHORISATION in str(c)]
        assert len(calls) >= 1

    def test_T21_human0_gate_failure_raises(self, tmp_path):
        """T21: CGTH emit failure raises CFEHumanGateError."""
        from dorkllm.constitutional_forecast import CFEHumanGateError
        bad_hub = MagicMock()
        bad_hub.emit.side_effect = RuntimeError("CGTH down")
        e = _fresh_engine(str(tmp_path))
        with patch("dorkllm.constitutional_forecast.get_hub", return_value=bad_hub):
            with pytest.raises(CFEHumanGateError):
                e.forecast(self._high_risk_window())


# ===========================================================================
# Risk tier classification (T22–T26)
# ===========================================================================

class TestRiskTierClassification:
    def test_T22_low_risk_flat_low_window(self, tmp_path):
        """T22: flat low-pressure window → LOW tier."""
        e = _fresh_engine(str(tmp_path))
        with patch("dorkllm.constitutional_forecast.get_hub", return_value=_mock_hub()):
            r = e.forecast([0.10, 0.11, 0.10])
        assert r.risk_tier == "LOW"

    def test_T23_medium_risk_moderate_window(self, tmp_path):
        """T23: moderate-slope window projects to 0.50-0.74 → MEDIUM tier."""
        e = _fresh_engine(str(tmp_path))
        # slope=0.02, last=0.44 → projected=0.44+0.02*5=0.54 → MEDIUM
        with patch("dorkllm.constitutional_forecast.get_hub", return_value=_mock_hub()):
            r = e.forecast([0.40, 0.42, 0.44])
        assert r.risk_tier == "MEDIUM"

    def test_T24_high_risk_threshold_window(self, tmp_path):
        """T24: steeply rising window projects past 0.75 → HIGH_RISK."""
        e = _fresh_engine(str(tmp_path))
        with patch("dorkllm.constitutional_forecast.get_hub", return_value=_mock_hub()):
            r = e.forecast([0.55, 0.65, 0.72, 0.80])
        assert r.risk_tier in ("HIGH_RISK", "CRITICAL")

    def test_T25_critical_threshold_window(self, tmp_path):
        """T25: near-ceiling window → CRITICAL tier."""
        e = _fresh_engine(str(tmp_path))
        with patch("dorkllm.constitutional_forecast.get_hub", return_value=_mock_hub()):
            r = e.forecast([0.80, 0.88, 0.92, 0.96])
        assert r.risk_tier == "CRITICAL"

    def test_T26_forecast_pressure_clamped_0_1(self, tmp_path):
        """T26: forecast_pressure is always clamped to [0.0, 1.0]."""
        e = _fresh_engine(str(tmp_path))
        extreme_window = [0.95, 0.97, 0.99]
        with patch("dorkllm.constitutional_forecast.get_hub", return_value=_mock_hub()):
            r = e.forecast(extreme_window)
        assert 0.0 <= r.forecast_pressure <= 1.0


# ===========================================================================
# API surface — 4 routes schema / 200 / 422 (T27–T30)
# ===========================================================================

class TestCFEAPIRoutes:
    @pytest.fixture()
    def client(self, tmp_path, monkeypatch):
        import importlib
        monkeypatch.setenv("CFE_LEDGER_PATH", str(tmp_path / "cfe_test.jsonl"))
        import dorkllm.constitutional_forecast as mod_cfe
        importlib.reload(mod_cfe)
        import app.api.constitutional_forecast as mod_api
        importlib.reload(mod_api)
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(mod_api.router)
        return TestClient(app)

    def test_T27_status_route_200(self, client):
        """T27: GET /api/governance/cfe/status returns 200."""
        resp = client.get("/api/governance/cfe/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["component"] == "cfe"
        assert body["status"] == "operational"

    def test_T28_chain_route_200(self, client):
        """T28: GET /api/governance/cfe/chain returns 200 with list."""
        resp = client.get("/api/governance/cfe/chain")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_T29_forecast_route_200_valid(self, client):
        """T29: POST /api/governance/cfe/forecast returns 200 with valid body."""
        with patch("dorkllm.constitutional_forecast.get_hub", return_value=_mock_hub()):
            resp = client.post(
                "/api/governance/cfe/forecast",
                json={"pressure_window": [0.2, 0.3, 0.4], "horizon_epochs": 5},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert "forecast_id" in body
        assert "risk_tier" in body
        assert "digest" in body

    def test_T30_forecast_route_422_too_few_points(self, client):
        """T30: POST /api/governance/cfe/forecast with 2 points → 422."""
        resp = client.post(
            "/api/governance/cfe/forecast",
            json={"pressure_window": [0.3, 0.4], "horizon_epochs": 5},
        )
        assert resp.status_code == 422


# Re-export ConstitutionalForecastEngine for direct import in fixtures
from dorkllm.constitutional_forecast import ConstitutionalForecastEngine
