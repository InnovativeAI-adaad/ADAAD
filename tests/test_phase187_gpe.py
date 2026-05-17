# SPDX-License-Identifier: Proprietary — All Rights Reserved
"""
Test suite — INNOV-92 · GPE — GA Promotion Engine
Phase 187 · v9.120.0 · InnovativeAI LLC
Governor: DUSTIN L REID

30 tests covering: assess determinism, V10 criteria evaluation, chain integrity,
alignment check, HUMAN-0 advisory emission, manifest persistence, REST endpoints,
invariant counts, promotion status, scope boundaries, and constitutional invariants.

T187-GPE-01 … T187-GPE-30
"""

import json
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dorkllm.ga_promotion_engine import (
    GAPromotionEngine,
    PromotionStatus,
    CriterionStatus,
    AlignmentCheck,
    GPEChainError,
    _INVARIANTS,
    _INVARIANT_COUNT,
    _V10_CRITERIA,
    invariants,
)
from app.api.ga_promotion_engine import router

pytestmark = pytest.mark.phase187_gpe

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _tmp_engine(tmp_path: Path, version: str = "9.120.0") -> GAPromotionEngine:
    tmp_path.mkdir(parents=True, exist_ok=True)
    manifest = tmp_path / "gpe_manifest.jsonl"
    version_file = tmp_path / "VERSION"
    version_file.write_text(version)
    return GAPromotionEngine(manifest_path=manifest, version_file=version_file)


def _all_met_snapshot() -> Dict[str, Any]:
    return {c: {"score": 1.0, "status": "MET", "note": "test"} for c in _V10_CRITERIA if c != "GA_ALIGNMENT"}


@pytest.fixture
def tmp_engine(tmp_path):
    return _tmp_engine(tmp_path)


@pytest.fixture
def app_client(tmp_path):
    import dorkllm.ga_promotion_engine as gpe_mod
    import app.api.ga_promotion_engine as router_mod
    engine = _tmp_engine(tmp_path)
    router_mod._engine = engine
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    yield client
    router_mod._engine = None


# ── T187-GPE-01: invariant count is exactly 12 ────────────────────────────────


def test_T187_GPE_01_invariant_count():
    assert _INVARIANT_COUNT == 12


# ── T187-GPE-02: all invariant names present ─────────────────────────────────


def test_T187_GPE_02_invariant_names():
    names = set(_INVARIANTS)
    for suffix in range(12):
        code = [n for n in names if n.endswith("-0") and n.startswith("GPE-")]
        assert len(code) == 12


# ── T187-GPE-03: module-level invariants() returns tuple ────────────────────


def test_T187_GPE_03_module_invariants_fn():
    result = invariants()
    assert isinstance(result, tuple)
    assert len(result) == 12


# ── T187-GPE-04: V10 criteria list has exactly 7 entries ────────────────────


def test_T187_GPE_04_v10_criteria_count():
    assert len(_V10_CRITERIA) == 7


# ── T187-GPE-05: GA_ALIGNMENT is in V10 criteria ────────────────────────────


def test_T187_GPE_05_ga_alignment_in_criteria():
    assert "GA_ALIGNMENT" in _V10_CRITERIA


# ── T187-GPE-06: assess() returns GAManifestEntry with expected fields ───────


def test_T187_GPE_06_assess_returns_entry(tmp_engine):
    entry = tmp_engine.assess()
    assert entry.phase == 187
    assert entry.version == "9.120.0"
    assert entry.entry_hmac != ""
    assert len(entry.v10_criteria) == 7


# ── T187-GPE-07: misaligned state when pypi_version is None ─────────────────


def test_T187_GPE_07_status_misaligned_no_pypi(tmp_engine):
    entry = tmp_engine.assess()
    assert entry.promotion_status == PromotionStatus.MISALIGNED.value


# ── T187-GPE-08: HUMAN0_REQUIRED when fully aligned ─────────────────────────


def test_T187_GPE_08_status_human0_required_when_aligned(tmp_engine):
    entry = tmp_engine.assess(
        v10_snapshot=_all_met_snapshot(),
        pypi_version="9.120.0",
    )
    assert entry.promotion_status == PromotionStatus.HUMAN0_REQUIRED.value


# ── T187-GPE-09: BLOCKED when at least one criterion is UNMET ───────────────


def test_T187_GPE_09_status_blocked_on_unmet_criterion(tmp_engine):
    snap = _all_met_snapshot()
    snap["INVARIANT_DENSITY"] = {"score": 0.3, "status": "UNMET", "note": "below threshold"}
    entry = tmp_engine.assess(v10_snapshot=snap, pypi_version="9.120.0")
    assert entry.promotion_status == PromotionStatus.BLOCKED.value


# ── T187-GPE-10: HUMAN-0 advisory emitted in HUMAN0_REQUIRED state ──────────


def test_T187_GPE_10_human0_advisory_present_on_ready(tmp_engine):
    entry = tmp_engine.assess(v10_snapshot=_all_met_snapshot(), pypi_version="9.120.0")
    assert "HUMAN-0 RATIFICATION REQUIRED" in entry.human0_advisory


# ── T187-GPE-11: HUMAN-0 advisory present in MISALIGNED state ───────────────


def test_T187_GPE_11_advisory_misaligned(tmp_engine):
    entry = tmp_engine.assess()
    assert "GPE ADVISORY" in entry.human0_advisory
    assert "GA_ALIGNMENT" in entry.human0_advisory or "PyPI" in entry.human0_advisory


# ── T187-GPE-12: assessment is deterministic (same inputs → same output) ─────


def test_T187_GPE_12_determinism(tmp_path):
    snap = _all_met_snapshot()
    engine1 = _tmp_engine(tmp_path / "e1")
    engine2 = _tmp_engine(tmp_path / "e2")
    e1 = engine1.assess(v10_snapshot=snap, pypi_version="9.120.0", entry_id="X")
    e2 = engine2.assess(v10_snapshot=snap, pypi_version="9.120.0", entry_id="X")
    assert e1.promotion_status == e2.promotion_status
    assert e1.overall_score == e2.overall_score
    assert e1.entry_id == e2.entry_id


# ── T187-GPE-13: overall_score is 1.0 when all criteria met and aligned ──────


def test_T187_GPE_13_overall_score_all_met(tmp_engine):
    entry = tmp_engine.assess(v10_snapshot=_all_met_snapshot(), pypi_version="9.120.0")
    assert entry.overall_score == pytest.approx(1.0)


# ── T187-GPE-14: overall_score < 1.0 when GA_ALIGNMENT unresolved ───────────


def test_T187_GPE_14_overall_score_with_misalignment(tmp_engine):
    entry = tmp_engine.assess()
    assert entry.overall_score < 1.0


# ── T187-GPE-15: each manifest entry is sealed with HMAC ─────────────────────


def test_T187_GPE_15_entry_hmac_non_empty(tmp_engine):
    entry = tmp_engine.assess()
    assert len(entry.entry_hmac) == 64  # SHA-256 hex digest


# ── T187-GPE-16: chain integrity verifies after single entry ─────────────────


def test_T187_GPE_16_verify_chain_single_entry(tmp_engine):
    tmp_engine.assess()
    result = tmp_engine.verify_chain()
    assert result["ok"] is True
    assert result["entries_verified"] == 1


# ── T187-GPE-17: chain verifies after multiple entries ───────────────────────


def test_T187_GPE_17_verify_chain_multiple(tmp_engine):
    for _ in range(5):
        tmp_engine.assess()
    result = tmp_engine.verify_chain()
    assert result["ok"] is True
    assert result["entries_verified"] == 5


# ── T187-GPE-18: chain breaks on tampered entry ──────────────────────────────


def test_T187_GPE_18_chain_broken_on_tamper(tmp_engine):
    tmp_engine.assess()
    tmp_engine.assess()
    tmp_engine._entries[0].entry_hmac = "0" * 64
    with pytest.raises(GPEChainError):
        tmp_engine.verify_chain()


# ── T187-GPE-19: manifest is append-only (entry count increases) ─────────────


def test_T187_GPE_19_manifest_append_only(tmp_engine):
    assert len(tmp_engine.manifest()) == 0
    tmp_engine.assess()
    assert len(tmp_engine.manifest()) == 1
    tmp_engine.assess()
    assert len(tmp_engine.manifest()) == 2


# ── T187-GPE-20: manifest persists across engine restart ─────────────────────


def test_T187_GPE_20_persistence(tmp_path):
    m = tmp_path / "gpe_manifest.jsonl"
    v = tmp_path / "VERSION"
    v.write_text("9.120.0")
    e1 = GAPromotionEngine(manifest_path=m, version_file=v)
    e1.assess()
    e1.assess()
    # Simulate restart
    e2 = GAPromotionEngine(manifest_path=m, version_file=v)
    assert len(e2.manifest()) == 2


# ── T187-GPE-21: status() returns engine metadata without assess ─────────────


def test_T187_GPE_21_status_without_assess(tmp_engine):
    s = tmp_engine.status()
    assert s["engine"] == "GPE"
    assert s["innovation"] == "INNOV-92"
    assert s["phase"] == 187
    assert s["manifest_entries"] == 0


# ── T187-GPE-22: status() reflects last promotion_status after assess ────────


def test_T187_GPE_22_status_after_assess(tmp_engine):
    tmp_engine.assess()
    s = tmp_engine.status()
    assert s["manifest_entries"] == 1
    assert s["last_status"] is not None


# ── T187-GPE-23: GA_ALIGNMENT criterion UNMET when pypi_version mismatch ─────


def test_T187_GPE_23_ga_alignment_unmet_on_mismatch(tmp_engine):
    entry = tmp_engine.assess(v10_snapshot=_all_met_snapshot(), pypi_version="9.999.0")
    ga = next(c for c in entry.v10_criteria if c["criterion"] == "GA_ALIGNMENT")
    assert ga["status"] == CriterionStatus.UNMET.value


# ── T187-GPE-24: GA_ALIGNMENT criterion MET when versions match ──────────────


def test_T187_GPE_24_ga_alignment_met_on_match(tmp_engine):
    entry = tmp_engine.assess(v10_snapshot=_all_met_snapshot(), pypi_version="9.120.0")
    ga = next(c for c in entry.v10_criteria if c["criterion"] == "GA_ALIGNMENT")
    assert ga["status"] == CriterionStatus.MET.value


# ── T187-GPE-25: prev_hmac chain links between entries ───────────────────────


def test_T187_GPE_25_prev_hmac_links(tmp_engine):
    e1 = tmp_engine.assess()
    e2 = tmp_engine.assess()
    assert e2.prev_hmac == e1.entry_hmac


# ── T187-GPE-26: first entry prev_hmac is GENESIS ───────────────────────────


def test_T187_GPE_26_first_entry_genesis(tmp_engine):
    entry = tmp_engine.assess()
    assert entry.prev_hmac == "GENESIS"


# ── T187-GPE-27: invariants() accessible on engine instance ──────────────────


def test_T187_GPE_27_instance_invariants(tmp_engine):
    inv = tmp_engine.invariants()
    assert isinstance(inv, tuple)
    assert "GPE-HUMAN0-0" in inv
    assert "GPE-ALIGN-0" in inv


# ── T187-GPE-28: REST /assess returns 200 with sealed entry ──────────────────


def test_T187_GPE_28_rest_assess_200(app_client):
    resp = app_client.post("/api/gpe/assess", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "entry" in data
    assert data["entry"]["phase"] == 187


# ── T187-GPE-29: REST /status returns engine metadata ────────────────────────


def test_T187_GPE_29_rest_status(app_client):
    resp = app_client.get("/api/gpe/status")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["status"]["engine"] == "GPE"


# ── T187-GPE-30: REST /verify returns chain ok after assess ──────────────────


def test_T187_GPE_30_rest_verify_chain(app_client):
    app_client.post("/api/gpe/assess", json={})
    resp = app_client.get("/api/gpe/verify")
    assert resp.status_code == 200
    assert resp.json()["verification"]["ok"] is True
