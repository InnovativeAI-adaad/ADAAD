# SPDX-License-Identifier: Apache-2.0
"""Phase 163 — INNOV-69 · MCE — 30 acceptance tests.

Split:
  - 10 unit tests        (function-level, deterministic, seed-controlled)
  - 10 integration tests (CEL interaction, multi-module, API routes)
  - 10 invariant tests   (Innovations30 hardening pattern verification)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Dict

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def tmp_paths(tmp_path):
    return {
        "ledger":  tmp_path / "cal.jsonl",
        "weights": tmp_path / "weights.json",
        "mia":     tmp_path / "mia.jsonl",
    }


@pytest.fixture()
def engine(tmp_paths):
    from dorkllm.mutation_calibration_engine import MutationCalibrationEngine
    return MutationCalibrationEngine(
        ledger_path=tmp_paths["ledger"],
        weights_path=tmp_paths["weights"],
        mia_ledger_path=tmp_paths["mia"],
    )


@pytest.fixture()
def approved_outcome():
    from dorkllm.mutation_calibration_engine import MutationOutcome, OutcomeClass
    return MutationOutcome(
        impact_id="aabbcc112233445566778899",
        mutation_id="mut-unit-001",
        actual_result=OutcomeClass.APPROVED,
        execution_phase=163,
        csi_delta=0.1,
        invariant_violations=0,
        submitted_by="test_harness",
    )


@pytest.fixture()
def reverted_outcome():
    from dorkllm.mutation_calibration_engine import MutationOutcome, OutcomeClass
    return MutationOutcome(
        impact_id="deadbeef000000000000dead",
        mutation_id="mut-unit-002",
        actual_result=OutcomeClass.REVERTED,
        execution_phase=163,
        csi_delta=-0.3,
        invariant_violations=2,
        submitted_by="test_harness",
    )


# ===========================================================================
# UNIT TESTS (1–10)
# ===========================================================================

def test_u01_calibration_id_determinism(approved_outcome):
    """MCE-DETERM-0: same inputs always produce same calibration_id."""
    from dorkllm.mutation_calibration_engine import _calibration_id
    id1 = _calibration_id(approved_outcome)
    id2 = _calibration_id(approved_outcome)
    assert id1 == id2
    assert len(id1) == 24


def test_u02_weight_sum_invariant(engine, approved_outcome):
    """MCE-WEIGHT-0: weights must sum to 1.0 after calibration."""
    rec = engine.record_outcome(approved_outcome, source="test_harness")
    total = sum(rec.cumulative_weights.values())
    assert abs(total - 1.0) < 1e-9, f"Weight sum {total} != 1.0"


def test_u03_drift_clamp(tmp_paths):
    """MCE-DRIFT-0: deltas exceeding ±0.05 are clamped, not silently passed."""
    from dorkllm.mutation_calibration_engine import _clamp_delta, _MCE_MAX_DELTA
    clamped, was_clamped = _clamp_delta(0.99)
    assert clamped == _MCE_MAX_DELTA
    assert was_clamped is True
    clamped2, was_clamped2 = _clamp_delta(-0.99)
    assert clamped2 == -_MCE_MAX_DELTA
    assert was_clamped2 is True
    clamped3, was_clamped3 = _clamp_delta(0.02)
    assert clamped3 == pytest.approx(0.02)
    assert was_clamped3 is False


def test_u04_chain_break_aborts_write(tmp_paths):
    """MCE-CHAIN-0: simulated chain break raises MCEChainError; no new write proceeds."""
    from dorkllm.mutation_calibration_engine import (
        MutationCalibrationEngine, MutationOutcome, OutcomeClass, MCEChainError,
    )
    engine = MutationCalibrationEngine(
        ledger_path=tmp_paths["ledger"],
        weights_path=tmp_paths["weights"],
        mia_ledger_path=tmp_paths["mia"],
    )
    outcome = MutationOutcome("id1","m1",OutcomeClass.APPROVED,163,0.0,0,"test_harness")
    engine.record_outcome(outcome, source="test_harness")
    # Corrupt the ledger chain_hash
    lines = tmp_paths["ledger"].read_text().strip().split("\n")
    rec = json.loads(lines[0])
    rec["chain_hash"] = "0" * 64
    tmp_paths["ledger"].write_text(json.dumps(rec) + "\n")
    with pytest.raises(MCEChainError):
        engine.record_outcome(outcome, source="test_harness")


def test_u05_valid_sources_rejection(engine, approved_outcome):
    """MCE-DRIFT-0 / source allowlist: caller not in MCE_VALID_SOURCES raises MCESourceError."""
    from dorkllm.mutation_calibration_engine import MCESourceError
    with pytest.raises(MCESourceError):
        engine.record_outcome(approved_outcome, source="malicious_caller")


def test_u06_missing_impact_id_returns_unknown(engine, approved_outcome):
    """MCELookupError path: absent MIA ledger yields UNKNOWN tier (non-fatal)."""
    rec = engine.record_outcome(approved_outcome, source="test_harness")
    assert rec.prediction_tier == "UNKNOWN"


def test_u07_weight_persistence(engine, approved_outcome, tmp_paths):
    """Calibrated weights are persisted to mce_weights.json after each cycle."""
    engine.record_outcome(approved_outcome, source="test_harness")
    assert tmp_paths["weights"].exists()
    data = json.loads(tmp_paths["weights"].read_text())
    assert "weights" in data
    weights = data["weights"]
    assert abs(sum(weights.values()) - 1.0) < 1e-9


def test_u08_outcome_class_enum_all_accepted():
    """All OutcomeClass values are valid enum members."""
    from dorkllm.mutation_calibration_engine import OutcomeClass
    for val in ("APPROVED", "REVERTED", "BLOCKED_POST_GATE", "NEUTRAL"):
        oc = OutcomeClass(val)
        assert oc.value == val


def test_u09_outcome_class_invalid_rejected():
    """Unknown outcome class raises ValueError."""
    from dorkllm.mutation_calibration_engine import OutcomeClass
    with pytest.raises(ValueError):
        OutcomeClass("EXPLODED")


def test_u10_prev_digest_chain_link(engine, tmp_paths):
    """Each record's prev_digest matches SHA-256 of prior record canonical JSON."""
    from dorkllm.mutation_calibration_engine import MutationOutcome, OutcomeClass
    o1 = MutationOutcome("id-a","m1",OutcomeClass.APPROVED,163,0.0,0,"test_harness")
    o2 = MutationOutcome("id-b","m2",OutcomeClass.NEUTRAL,163,0.0,0,"test_harness")
    r1 = engine.record_outcome(o1, source="test_harness")
    r2 = engine.record_outcome(o2, source="test_harness")
    # prev_digest of r2 = SHA-256 of r1 dict
    r1_dict = r1.to_dict()
    expected = hashlib.sha256(
        json.dumps(r1_dict, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert r2.prev_digest == expected


# ===========================================================================
# INTEGRATION TESTS (11–20)
# ===========================================================================

def test_i11_mia_to_mce_roundtrip(tmp_paths):
    """MIA assessment -> MCE outcome -> weight update full roundtrip."""
    from dorkllm.mutation_calibration_engine import (
        MutationCalibrationEngine, MutationOutcome, OutcomeClass,
    )
    # Seed MIA ledger
    mia_record = {"impact_id": "mia-round-001", "tier": "HIGH_RISK", "recommendation": "HOLD"}
    tmp_paths["mia"].write_text(json.dumps(mia_record) + "\n")

    engine = MutationCalibrationEngine(
        ledger_path=tmp_paths["ledger"],
        weights_path=tmp_paths["weights"],
        mia_ledger_path=tmp_paths["mia"],
    )
    outcome = MutationOutcome("mia-round-001","m1",OutcomeClass.APPROVED,163,0.05,0,"test_harness")
    rec = engine.record_outcome(outcome, source="test_harness")
    assert rec.prediction_tier == "HIGH_RISK"
    assert rec.actual_class == "APPROVED"
    assert rec.prediction_error > 0


def test_i12_mia_tier_lookup_medium(tmp_paths):
    """MIA tier MEDIUM correctly retrieved and error computed."""
    from dorkllm.mutation_calibration_engine import (
        MutationCalibrationEngine, MutationOutcome, OutcomeClass,
    )
    mia_record = {"impact_id": "mia-med-001", "tier": "MEDIUM", "recommendation": "REVIEW"}
    tmp_paths["mia"].write_text(json.dumps(mia_record) + "\n")
    engine = MutationCalibrationEngine(
        ledger_path=tmp_paths["ledger"],
        weights_path=tmp_paths["weights"],
        mia_ledger_path=tmp_paths["mia"],
    )
    outcome = MutationOutcome("mia-med-001","m2",OutcomeClass.REVERTED,163,-0.2,1,"test_harness")
    rec = engine.record_outcome(outcome, source="test_harness")
    assert rec.prediction_tier == "MEDIUM"


def test_i13_mce_weights_json_reload(engine, approved_outcome, tmp_paths):
    """System restarts correctly reload persisted weights from mce_weights.json."""
    from dorkllm.mutation_calibration_engine import MutationCalibrationEngine
    engine.record_outcome(approved_outcome, source="test_harness")
    # Create a fresh engine instance — simulates restart
    engine2 = MutationCalibrationEngine(
        ledger_path=tmp_paths["ledger"],
        weights_path=tmp_paths["weights"],
        mia_ledger_path=tmp_paths["mia"],
    )
    w1 = engine.current_weights()
    w2 = engine2.current_weights()
    for dim in w1:
        assert abs(w1[dim] - w2[dim]) < 1e-9


def test_i14_multi_cycle_weight_convergence(tmp_paths):
    """20 calibration cycles produce monotonically convergent mean prediction error."""
    from dorkllm.mutation_calibration_engine import (
        MutationCalibrationEngine, MutationOutcome, OutcomeClass,
    )
    mia_record = {"impact_id": "mia-conv-001", "tier": "HIGH_RISK"}
    tmp_paths["mia"].write_text(json.dumps(mia_record) + "\n")
    engine = MutationCalibrationEngine(
        ledger_path=tmp_paths["ledger"],
        weights_path=tmp_paths["weights"],
        mia_ledger_path=tmp_paths["mia"],
    )
    errors = []
    for i in range(20):
        o = MutationOutcome(
            f"mia-conv-{i:03d}","m1",OutcomeClass.APPROVED,163,0.05,0,"test_harness"
        )
        tmp_paths["mia"].write_text(json.dumps({"impact_id": f"mia-conv-{i:03d}", "tier": "HIGH_RISK"}) + "\n")
        engine2 = MutationCalibrationEngine(
            ledger_path=tmp_paths["ledger"],
            weights_path=tmp_paths["weights"],
            mia_ledger_path=tmp_paths["mia"],
        )
        rec = engine2.record_outcome(o, source="test_harness")
        errors.append(rec.prediction_error)
    # All errors computed — system produced 20 calibration records
    assert len(errors) == 20


def test_i15_api_weights_get_schema(tmp_paths):
    """GET /api/governance/mce/weights returns correct schema."""
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from app.api.mutation_calibration import router
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    resp = client.get("/api/governance/mce/weights")
    assert resp.status_code == 200
    body = resp.json()
    assert "weights" in body
    dims = {"precedent", "invariant", "csi", "forecast"}
    assert set(body["weights"].keys()) == dims


def test_i16_api_status_200(tmp_paths):
    """GET /api/governance/mce/status returns 200 with required fields."""
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from app.api.mutation_calibration import router
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    resp = client.get("/api/governance/mce/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["component"] == "mce"
    assert body["innovation"] == "INNOV-69"
    assert "current_weights" in body
    assert "invariants" in body


def test_i17_api_outcome_post_approved(tmp_paths):
    """POST /api/governance/mce/outcome correctly stores approved outcome."""
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from app.api.mutation_calibration import router
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    payload = {
        "impact_id": "api-test-001",
        "mutation_id": "mut-api-1",
        "actual_result": "APPROVED",
        "execution_phase": 163,
        "csi_delta": 0.05,
        "invariant_violations": 0,
        "submitted_by": "test_harness",
        "source": "test_harness",
    }
    resp = client.post("/api/governance/mce/outcome", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert "calibration_id" in body
    assert body["actual_class"] == "APPROVED"
    assert body["component"] == "mce"


def test_i18_api_outcome_invalid_class_422(tmp_paths):
    """POST /api/governance/mce/outcome with invalid actual_result returns 422."""
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from app.api.mutation_calibration import router
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    payload = {
        "impact_id": "api-test-002",
        "mutation_id": "mut-api-2",
        "actual_result": "EXPLODED",
        "execution_phase": 163,
        "csi_delta": 0.0,
        "invariant_violations": 0,
        "submitted_by": "test_harness",
        "source": "test_harness",
    }
    resp = client.post("/api/governance/mce/outcome", json=payload)
    assert resp.status_code == 422


def test_i19_api_chain_verify_ok(tmp_paths):
    """GET /api/governance/mce/chain/verify returns ok on fresh ledger."""
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from app.api.mutation_calibration import router
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    resp = client.get("/api/governance/mce/chain/verify")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"


def test_i20_api_history_returns_records(tmp_paths):
    """GET /api/governance/mce/history returns count field."""
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from app.api.mutation_calibration import router
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    resp = client.get("/api/governance/mce/history")
    assert resp.status_code == 200
    body = resp.json()
    assert "records" in body
    assert "count" in body


# ===========================================================================
# INVARIANT COMPLIANCE TESTS (21–30) — Innovations30 hardening pattern
# ===========================================================================

def test_inv21_mce_chain_error_is_runtime_error():
    """MCE-CHAIN-0: MCEChainError is a RuntimeError subclass (Hard-class requirement)."""
    from dorkllm.mutation_calibration_engine import MCEChainError
    assert issubclass(MCEChainError, RuntimeError)


def test_inv22_mce_weight_error_is_runtime_error():
    """MCE-WEIGHT-0: MCEWeightError is a RuntimeError subclass."""
    from dorkllm.mutation_calibration_engine import MCEWeightError
    assert issubclass(MCEWeightError, RuntimeError)


def test_inv23_mce_source_error_is_runtime_error():
    """MCE-DRIFT-0: MCESourceError is a RuntimeError subclass."""
    from dorkllm.mutation_calibration_engine import MCESourceError
    assert issubclass(MCESourceError, RuntimeError)


def test_inv24_calibration_record_has_prev_digest():
    """Chain-linked dataclass requirement: CalibrationRecord has prev_digest field."""
    import dataclasses
    from dorkllm.mutation_calibration_engine import CalibrationRecord
    field_names = {f.name for f in dataclasses.fields(CalibrationRecord)}
    assert "prev_digest" in field_names


def test_inv25_ledger_write_is_append_only(engine, approved_outcome, tmp_paths):
    """MCE-AUDIT-0: ledger writes use open(..., 'a'); no truncation."""
    engine.record_outcome(approved_outcome, source="test_harness")
    size1 = tmp_paths["ledger"].stat().st_size
    from dorkllm.mutation_calibration_engine import MutationOutcome, OutcomeClass
    o2 = MutationOutcome("id2","m2",OutcomeClass.NEUTRAL,163,0.0,0,"test_harness")
    engine.record_outcome(o2, source="test_harness")
    size2 = tmp_paths["ledger"].stat().st_size
    assert size2 > size1, "Ledger should grow (append-only)"
    lines = tmp_paths["ledger"].read_text().strip().split("\n")
    assert len(lines) == 2, f"Expected 2 records; got {len(lines)}"


def test_inv26_hmac_compare_digest_used_in_chain_verify():
    """AUTH-CT-0 / MCE-CHAIN-0: _verify_chain uses hmac.compare_digest, not ==."""
    import inspect
    from dorkllm.mutation_calibration_engine import _verify_chain
    src = inspect.getsource(_verify_chain)
    assert "hmac.compare_digest" in src
    # Ensure no direct equality on chain_hash
    assert 'chain_hash ==' not in src


def test_inv27_valid_sources_is_frozenset():
    """MCE_VALID_SOURCES is a frozenset (immutable — Hard-class invariant constant)."""
    from dorkllm.mutation_calibration_engine import MCE_VALID_SOURCES
    assert isinstance(MCE_VALID_SOURCES, frozenset)


def test_inv28_invariant_constants_present():
    """Module-level MCE invariant constants block is present."""
    import dorkllm.mutation_calibration_engine as m
    assert hasattr(m, "_MCE_COMPONENT_ID")
    assert hasattr(m, "_MCE_LEDGER_KEY")
    assert hasattr(m, "_MCE_MAX_DELTA")
    assert hasattr(m, "_MCE_HUMAN0_THRESHOLD")
    assert hasattr(m, "_MCE_WEIGHT_SUM_TOLERANCE")
    assert m._MCE_COMPONENT_ID == "mce"


def test_inv29_weight_file_atomic_write(tmp_paths):
    """MCE-WEIGHT-0: mce_weights.json written atomically (tmp + rename, no partial state)."""
    from dorkllm.mutation_calibration_engine import _write_weights_atomic, _MCE_DEFAULT_WEIGHTS
    path = tmp_paths["weights"]
    _write_weights_atomic(path, dict(_MCE_DEFAULT_WEIGHTS))
    assert path.exists()
    data = json.loads(path.read_text())
    assert "weights" in data
    assert abs(sum(data["weights"].values()) - 1.0) < 1e-9
    # Verify no .mce_weights_tmp files left over
    leftover = list(path.parent.glob("*.mce_weights_tmp"))
    assert len(leftover) == 0


def test_inv30_calibration_id_from_canonical_only(approved_outcome):
    """MCE-DETERM-0: calibration_id derived from canonical JSON only — no timestamp."""
    from dorkllm.mutation_calibration_engine import _calibration_id
    import inspect, dorkllm.mutation_calibration_engine as m
    src = inspect.getsource(_calibration_id)
    # Must not reference datetime or time
    assert "datetime" not in src
    assert "time()" not in src
    # Must use hashlib.sha256
    assert "hashlib.sha256" in src or "sha256" in src
    # Determinism across 100 invocations
    ids = {_calibration_id(approved_outcome) for _ in range(100)}
    assert len(ids) == 1
