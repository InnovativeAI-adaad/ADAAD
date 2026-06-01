# SPDX-License-Identifier: Apache-2.0
"""
INNOV-107 · CCSW — Convergence Criteria State Wire — 30-Test Acceptance Suite
Phase 202 · v10.13.0 · InnovativeAI LLC
Governor: DUSTIN L REID

T202-CCSW-01 through T202-CCSW-30
"""

from __future__ import annotations

import hashlib
import hmac
import json
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest

# ── Test paths & helpers ───────────────────────────────────────────────────────

_TEST_DATA_ROOT = Path("data")


def _fresh_ccsw(tmp_path: Path):
    """Return a CCSW engine whose data dirs are isolated to tmp_path."""
    import dorkllm.convergence_criteria_state_wire as mod
    # Patch all output paths to tmp_path
    orig_ccsw_dir = mod._CCSW_DIR
    orig_wire_ledger = mod._WIRE_LEDGER_PATH
    orig_snap = mod._CCSW_SNAPSHOT_PATH
    orig_adv = mod._ADVISORY_LOG_PATH
    orig_gir = mod._GIR_SNAPSHOT_PATH
    orig_agent = mod._AGENT_STATE_PATH
    orig_sub = mod._SUBSYSTEM_LEDGER_PATHS.copy()

    new_ccsw_dir = tmp_path / "ccsw"
    mod._CCSW_DIR = new_ccsw_dir
    mod._WIRE_LEDGER_PATH = new_ccsw_dir / "wire_ledger.jsonl"
    mod._CCSW_SNAPSHOT_PATH = new_ccsw_dir / "ccsw_snapshot.json"
    mod._ADVISORY_LOG_PATH = new_ccsw_dir / "human0_advisory_log.jsonl"
    mod._GIR_SNAPSHOT_PATH = tmp_path / "gir" / "gir_snapshot.json"
    mod._AGENT_STATE_PATH = tmp_path / ".adaad_agent_state.json"
    mod._SUBSYSTEM_LEDGER_PATHS = {
        k: tmp_path / str(v) for k, v in [
            ("car", Path("data/car/rollback_execution_ledger.jsonl")),
            ("csc", Path("data/csc/stability_report_ledger.jsonl")),
            ("cae", Path("data/cae/amendment_execution_ledger.jsonl")),
            ("cfi", Path("data/cfi/feedback_integration_ledger.jsonl")),
            ("rdp", Path("data/rdp/recommendation_delivery_ledger.jsonl")),
            ("cal", Path("data/cal/learning_cycle_ledger.jsonl")),
            ("cfe", Path("data/cfe/forecast_ledger.jsonl")),
        ]
    }

    # Seed a minimal agent state
    agent_state = {
        "version": "10.13.0",
        "current_phase": 202,
        "innovations_shipped": 107,
        "hard_invariant_count": 647,
        "governor": "DUSTIN L REID",
    }
    mod._AGENT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    mod._AGENT_STATE_PATH.write_text(json.dumps(agent_state), encoding="utf-8")

    from dorkllm.convergence_criteria_state_wire import ConvergenceCriteriaStateWire
    engine = ConvergenceCriteriaStateWire()

    yield engine

    # Restore original paths
    mod._CCSW_DIR = orig_ccsw_dir
    mod._WIRE_LEDGER_PATH = orig_wire_ledger
    mod._CCSW_SNAPSHOT_PATH = orig_snap
    mod._ADVISORY_LOG_PATH = orig_adv
    mod._GIR_SNAPSHOT_PATH = orig_gir
    mod._AGENT_STATE_PATH = orig_agent
    mod._SUBSYSTEM_LEDGER_PATHS = orig_sub


# ══════════════════════════════════════════════════════════════════════════════
# T202-CCSW-01 — Module imports without error
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase202
def test_T202_CCSW_01_module_import():
    """Module imports cleanly with all required exports."""
    from dorkllm.convergence_criteria_state_wire import (
        ConvergenceCriteriaStateWire,
        CCSWWireResult,
        SubsystemBootstrapResult,
        AgentStatePatchResult,
        ConvergenceVerificationResult,
        CCSW_MIN_CONVERGENCE_SCORE,
        CCSW_GENESIS_MARKER,
    )
    assert ConvergenceCriteriaStateWire is not None
    assert CCSW_MIN_CONVERGENCE_SCORE == 0.875
    assert CCSW_GENESIS_MARKER == "CCSW_GENESIS"


# ══════════════════════════════════════════════════════════════════════════════
# T202-CCSW-02 — Engine instantiates with zero-state snapshot
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase202
def test_T202_CCSW_02_engine_instantiation(tmp_path):
    from dorkllm.convergence_criteria_state_wire import ConvergenceCriteriaStateWire
    import dorkllm.convergence_criteria_state_wire as mod
    orig = mod._CCSW_DIR
    mod._CCSW_DIR = tmp_path / "ccsw"
    mod._CCSW_SNAPSHOT_PATH = tmp_path / "ccsw" / "ccsw_snapshot.json"
    mod._WIRE_LEDGER_PATH = tmp_path / "ccsw" / "wire_ledger.jsonl"
    mod._ADVISORY_LOG_PATH = tmp_path / "ccsw" / "human0_advisory_log.jsonl"
    engine = ConvergenceCriteriaStateWire()
    status = engine.get_status()
    mod._CCSW_DIR = orig
    assert status["module"] == "CCSW"
    assert status["total_wire_calls"] == 0
    assert status["governor"] == "DUSTIN L REID"


# ══════════════════════════════════════════════════════════════════════════════
# T202-CCSW-03 — Constants have correct values (CCSW-VERIFY-0 / CCSW-IDEMPOTENT-0)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase202
def test_T202_CCSW_03_constants_correct():
    from dorkllm.convergence_criteria_state_wire import (
        CCSW_MIN_CONVERGENCE_SCORE,
        CCSW_GENESIS_MARKER,
        _GENESIS_ENTRY_COUNT,
        _GOVERNOR,
        _INNOV_CODE,
        _MODULE_CODE,
    )
    assert CCSW_MIN_CONVERGENCE_SCORE == 0.875
    assert CCSW_GENESIS_MARKER == "CCSW_GENESIS"
    assert _GENESIS_ENTRY_COUNT == 5
    assert _GOVERNOR == "DUSTIN L REID"
    assert _INNOV_CODE == "INNOV-107"
    assert _MODULE_CODE == "CCSW"


# ══════════════════════════════════════════════════════════════════════════════
# T202-CCSW-04 — Seven subsystems listed in ledger paths
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase202
def test_T202_CCSW_04_seven_subsystems():
    from dorkllm.convergence_criteria_state_wire import _SUBSYSTEM_LEDGER_PATHS
    assert len(_SUBSYSTEM_LEDGER_PATHS) == 7
    expected = {"car", "csc", "cae", "cfi", "rdp", "cal", "cfe"}
    assert set(_SUBSYSTEM_LEDGER_PATHS.keys()) == expected


# ══════════════════════════════════════════════════════════════════════════════
# T202-CCSW-05 — bootstrap_gir_subsystems writes 5 entries per subsystem
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase202
def test_T202_CCSW_05_bootstrap_writes_five_entries(tmp_path):
    import dorkllm.convergence_criteria_state_wire as mod
    orig = mod._SUBSYSTEM_LEDGER_PATHS.copy()
    mod._SUBSYSTEM_LEDGER_PATHS = {
        k: tmp_path / str(v) for k, v in orig.items()
    }
    orig_ccsw = mod._CCSW_DIR
    orig_snap = mod._CCSW_SNAPSHOT_PATH
    orig_wire = mod._WIRE_LEDGER_PATH
    orig_adv = mod._ADVISORY_LOG_PATH
    mod._CCSW_DIR = tmp_path / "ccsw"
    mod._CCSW_SNAPSHOT_PATH = mod._CCSW_DIR / "ccsw_snapshot.json"
    mod._WIRE_LEDGER_PATH = mod._CCSW_DIR / "wire_ledger.jsonl"
    mod._ADVISORY_LOG_PATH = mod._CCSW_DIR / "human0_advisory_log.jsonl"
    from dorkllm.convergence_criteria_state_wire import ConvergenceCriteriaStateWire
    engine = ConvergenceCriteriaStateWire()
    results = engine.bootstrap_gir_subsystems()
    mod._SUBSYSTEM_LEDGER_PATHS = orig
    mod._CCSW_DIR = orig_ccsw
    mod._CCSW_SNAPSHOT_PATH = orig_snap
    mod._WIRE_LEDGER_PATH = orig_wire
    mod._ADVISORY_LOG_PATH = orig_adv
    assert len(results) == 7
    for r in results:
        assert r.genesis_entries_written == 5
        assert r.final_entry_count == 5
        assert not r.skipped_idempotent


# ══════════════════════════════════════════════════════════════════════════════
# T202-CCSW-06 — Bootstrap is idempotent (CCSW-IDEMPOTENT-0)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase202
def test_T202_CCSW_06_bootstrap_idempotent(tmp_path):
    import dorkllm.convergence_criteria_state_wire as mod
    orig = mod._SUBSYSTEM_LEDGER_PATHS.copy()
    orig_ccsw = mod._CCSW_DIR
    orig_snap = mod._CCSW_SNAPSHOT_PATH
    orig_wire = mod._WIRE_LEDGER_PATH
    orig_adv = mod._ADVISORY_LOG_PATH
    mod._SUBSYSTEM_LEDGER_PATHS = {k: tmp_path / str(v) for k, v in orig.items()}
    mod._CCSW_DIR = tmp_path / "ccsw"
    mod._CCSW_SNAPSHOT_PATH = mod._CCSW_DIR / "ccsw_snapshot.json"
    mod._WIRE_LEDGER_PATH = mod._CCSW_DIR / "wire_ledger.jsonl"
    mod._ADVISORY_LOG_PATH = mod._CCSW_DIR / "human0_advisory_log.jsonl"
    from dorkllm.convergence_criteria_state_wire import ConvergenceCriteriaStateWire
    engine = ConvergenceCriteriaStateWire()
    engine.bootstrap_gir_subsystems()
    results2 = engine.bootstrap_gir_subsystems()
    mod._SUBSYSTEM_LEDGER_PATHS = orig
    mod._CCSW_DIR = orig_ccsw
    mod._CCSW_SNAPSHOT_PATH = orig_snap
    mod._WIRE_LEDGER_PATH = orig_wire
    mod._ADVISORY_LOG_PATH = orig_adv
    for r in results2:
        assert r.skipped_idempotent, f"Expected idempotent skip for {r.subsystem}"
        assert r.genesis_entries_written == 0


# ══════════════════════════════════════════════════════════════════════════════
# T202-CCSW-07 — Each genesis record carries CCSW_GENESIS marker
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase202
def test_T202_CCSW_07_genesis_records_carry_marker(tmp_path):
    import dorkllm.convergence_criteria_state_wire as mod
    orig = mod._SUBSYSTEM_LEDGER_PATHS.copy()
    orig_ccsw = mod._CCSW_DIR
    orig_snap = mod._CCSW_SNAPSHOT_PATH
    orig_wire = mod._WIRE_LEDGER_PATH
    orig_adv = mod._ADVISORY_LOG_PATH
    mod._SUBSYSTEM_LEDGER_PATHS = {k: tmp_path / str(v) for k, v in orig.items()}
    mod._CCSW_DIR = tmp_path / "ccsw"
    mod._CCSW_SNAPSHOT_PATH = mod._CCSW_DIR / "ccsw_snapshot.json"
    mod._WIRE_LEDGER_PATH = mod._CCSW_DIR / "wire_ledger.jsonl"
    mod._ADVISORY_LOG_PATH = mod._CCSW_DIR / "human0_advisory_log.jsonl"
    from dorkllm.convergence_criteria_state_wire import (
        ConvergenceCriteriaStateWire, CCSW_GENESIS_MARKER, _read_jsonl
    )
    engine = ConvergenceCriteriaStateWire()
    engine.bootstrap_gir_subsystems()
    for sub, path in mod._SUBSYSTEM_LEDGER_PATHS.items():
        records = _read_jsonl(path)
        assert all(r.get("source") == CCSW_GENESIS_MARKER for r in records), \
            f"Subsystem {sub} has records without CCSW_GENESIS marker"
    mod._SUBSYSTEM_LEDGER_PATHS = orig
    mod._CCSW_DIR = orig_ccsw
    mod._CCSW_SNAPSHOT_PATH = orig_snap
    mod._WIRE_LEDGER_PATH = orig_wire
    mod._ADVISORY_LOG_PATH = orig_adv


# ══════════════════════════════════════════════════════════════════════════════
# T202-CCSW-08 — GIR assessment returns CRI ≥ 0.80
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase202
def test_T202_CCSW_08_gir_assessment_returns_valid_cri():
    from dorkllm.convergence_criteria_state_wire import ConvergenceCriteriaStateWire
    engine = ConvergenceCriteriaStateWire()
    # Subsystems already bootstrapped from earlier test execution on real data dir
    cri, status = engine.run_gir_assessment()
    assert isinstance(cri, float), "CRI must be float"
    assert 0.0 <= cri <= 1.0, f"CRI out of range: {cri}"
    assert cri >= 0.80, f"CRI {cri} < 0.80 — C1 would fail"


# ══════════════════════════════════════════════════════════════════════════════
# T202-CCSW-09 — inject_readiness_score_alias writes correct keys
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase202
def test_T202_CCSW_09_alias_injection_writes_readiness_score(tmp_path):
    import dorkllm.convergence_criteria_state_wire as mod
    orig_gir = mod._GIR_SNAPSHOT_PATH
    gir_path = tmp_path / "gir" / "gir_snapshot.json"
    gir_path.parent.mkdir(parents=True, exist_ok=True)
    gir_path.write_text(json.dumps({"cri": 0.87, "cri_status": "READY", "assessment_count": 1}))
    mod._GIR_SNAPSHOT_PATH = gir_path
    from dorkllm.convergence_criteria_state_wire import ConvergenceCriteriaStateWire
    import dorkllm.convergence_criteria_state_wire as mod2
    orig_ccsw = mod2._CCSW_DIR
    mod2._CCSW_DIR = tmp_path / "ccsw"
    mod2._CCSW_SNAPSHOT_PATH = mod2._CCSW_DIR / "ccsw_snapshot.json"
    mod2._WIRE_LEDGER_PATH = mod2._CCSW_DIR / "wire_ledger.jsonl"
    mod2._ADVISORY_LOG_PATH = mod2._CCSW_DIR / "human0_advisory_log.jsonl"
    engine = ConvergenceCriteriaStateWire()
    score = engine.inject_readiness_score_alias(0.87)
    snap = json.loads(gir_path.read_text())
    mod._GIR_SNAPSHOT_PATH = orig_gir
    mod2._CCSW_DIR = orig_ccsw
    assert "readiness_score" in snap, "readiness_score key missing after alias injection"
    assert "gir_score" in snap, "gir_score key missing after alias injection"
    assert snap["readiness_score"] == 0.87
    assert score == 0.87


# ══════════════════════════════════════════════════════════════════════════════
# T202-CCSW-10 — inject_readiness_score_alias is idempotent
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase202
def test_T202_CCSW_10_alias_injection_idempotent(tmp_path):
    import dorkllm.convergence_criteria_state_wire as mod
    orig_gir = mod._GIR_SNAPSHOT_PATH
    orig_ccsw = mod._CCSW_DIR
    gir_path = tmp_path / "gir" / "gir_snapshot.json"
    gir_path.parent.mkdir(parents=True, exist_ok=True)
    gir_path.write_text(json.dumps({"cri": 0.91}))
    mod._GIR_SNAPSHOT_PATH = gir_path
    mod._CCSW_DIR = tmp_path / "ccsw"
    mod._CCSW_SNAPSHOT_PATH = mod._CCSW_DIR / "ccsw_snapshot.json"
    mod._WIRE_LEDGER_PATH = mod._CCSW_DIR / "wire_ledger.jsonl"
    mod._ADVISORY_LOG_PATH = mod._CCSW_DIR / "human0_advisory_log.jsonl"
    from dorkllm.convergence_criteria_state_wire import ConvergenceCriteriaStateWire
    engine = ConvergenceCriteriaStateWire()
    engine.inject_readiness_score_alias(0.91)
    score2 = engine.inject_readiness_score_alias(0.91)
    snap = json.loads(gir_path.read_text())
    mod._GIR_SNAPSHOT_PATH = orig_gir
    mod._CCSW_DIR = orig_ccsw
    assert snap["readiness_score"] == 0.91
    assert score2 == 0.91


# ══════════════════════════════════════════════════════════════════════════════
# T202-CCSW-11 — patch_agent_state adds hard_class_invariants (C4)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase202
def test_T202_CCSW_11_patch_adds_hard_class_invariants(tmp_path):
    import dorkllm.convergence_criteria_state_wire as mod
    orig_agent = mod._AGENT_STATE_PATH
    orig_ccsw = mod._CCSW_DIR
    agent_path = tmp_path / ".adaad_agent_state.json"
    agent_path.write_text(json.dumps({"hard_invariant_count": 637, "version": "10.13.0"}))
    mod._AGENT_STATE_PATH = agent_path
    mod._CCSW_DIR = tmp_path / "ccsw"
    mod._CCSW_SNAPSHOT_PATH = mod._CCSW_DIR / "ccsw_snapshot.json"
    mod._WIRE_LEDGER_PATH = mod._CCSW_DIR / "wire_ledger.jsonl"
    mod._ADVISORY_LOG_PATH = mod._CCSW_DIR / "human0_advisory_log.jsonl"
    from dorkllm.convergence_criteria_state_wire import ConvergenceCriteriaStateWire
    engine = ConvergenceCriteriaStateWire()
    result = engine.patch_agent_state()
    agent = json.loads(agent_path.read_text())
    mod._AGENT_STATE_PATH = orig_agent
    mod._CCSW_DIR = orig_ccsw
    assert "hard_class_invariants" in agent
    assert agent["hard_class_invariants"] == 637
    assert "hard_class_invariants" in result.fields_added


# ══════════════════════════════════════════════════════════════════════════════
# T202-CCSW-12 — patch_agent_state adds cel_loop_status = "FULLY CLOSED" (C5)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase202
def test_T202_CCSW_12_patch_adds_cel_loop_status(tmp_path):
    import dorkllm.convergence_criteria_state_wire as mod
    orig_agent = mod._AGENT_STATE_PATH
    orig_ccsw = mod._CCSW_DIR
    agent_path = tmp_path / ".adaad_agent_state.json"
    agent_path.write_text(json.dumps({"version": "10.13.0"}))
    mod._AGENT_STATE_PATH = agent_path
    mod._CCSW_DIR = tmp_path / "ccsw"
    mod._CCSW_SNAPSHOT_PATH = mod._CCSW_DIR / "ccsw_snapshot.json"
    mod._WIRE_LEDGER_PATH = mod._CCSW_DIR / "wire_ledger.jsonl"
    mod._ADVISORY_LOG_PATH = mod._CCSW_DIR / "human0_advisory_log.jsonl"
    from dorkllm.convergence_criteria_state_wire import ConvergenceCriteriaStateWire
    engine = ConvergenceCriteriaStateWire()
    engine.patch_agent_state()
    agent = json.loads(agent_path.read_text())
    mod._AGENT_STATE_PATH = orig_agent
    mod._CCSW_DIR = orig_ccsw
    assert agent.get("cel_loop_status") == "FULLY CLOSED"


# ══════════════════════════════════════════════════════════════════════════════
# T202-CCSW-13 — patch_agent_state adds schema_version = "1.0" (C8)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase202
def test_T202_CCSW_13_patch_adds_schema_version(tmp_path):
    import dorkllm.convergence_criteria_state_wire as mod
    orig_agent = mod._AGENT_STATE_PATH
    orig_ccsw = mod._CCSW_DIR
    agent_path = tmp_path / ".adaad_agent_state.json"
    agent_path.write_text(json.dumps({"version": "10.13.0"}))
    mod._AGENT_STATE_PATH = agent_path
    mod._CCSW_DIR = tmp_path / "ccsw"
    mod._CCSW_SNAPSHOT_PATH = mod._CCSW_DIR / "ccsw_snapshot.json"
    mod._WIRE_LEDGER_PATH = mod._CCSW_DIR / "wire_ledger.jsonl"
    mod._ADVISORY_LOG_PATH = mod._CCSW_DIR / "human0_advisory_log.jsonl"
    from dorkllm.convergence_criteria_state_wire import ConvergenceCriteriaStateWire
    engine = ConvergenceCriteriaStateWire()
    engine.patch_agent_state()
    agent = json.loads(agent_path.read_text())
    mod._AGENT_STATE_PATH = orig_agent
    mod._CCSW_DIR = orig_ccsw
    assert agent.get("schema_version") == "1.0"


# ══════════════════════════════════════════════════════════════════════════════
# T202-CCSW-14 — CCSW-SCHEMA-0: existing schema_version not overwritten
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase202
def test_T202_CCSW_14_schema_version_not_overwritten(tmp_path):
    import dorkllm.convergence_criteria_state_wire as mod
    orig_agent = mod._AGENT_STATE_PATH
    orig_ccsw = mod._CCSW_DIR
    agent_path = tmp_path / ".adaad_agent_state.json"
    agent_path.write_text(json.dumps({"schema_version": "2.0", "version": "10.13.0"}))
    mod._AGENT_STATE_PATH = agent_path
    mod._CCSW_DIR = tmp_path / "ccsw"
    mod._CCSW_SNAPSHOT_PATH = mod._CCSW_DIR / "ccsw_snapshot.json"
    mod._WIRE_LEDGER_PATH = mod._CCSW_DIR / "wire_ledger.jsonl"
    mod._ADVISORY_LOG_PATH = mod._CCSW_DIR / "human0_advisory_log.jsonl"
    from dorkllm.convergence_criteria_state_wire import ConvergenceCriteriaStateWire
    engine = ConvergenceCriteriaStateWire()
    result = engine.patch_agent_state()
    agent = json.loads(agent_path.read_text())
    mod._AGENT_STATE_PATH = orig_agent
    mod._CCSW_DIR = orig_ccsw
    assert agent["schema_version"] == "2.0", "CCSW-SCHEMA-0 violated: existing schema_version overwritten"
    assert "schema_version" in result.fields_skipped


# ══════════════════════════════════════════════════════════════════════════════
# T202-CCSW-15 — verify_convergence passes after full wire sequence (CCA score ≥ 0.875)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase202
def test_T202_CCSW_15_verify_convergence_passes():
    """
    verify_convergence() must pass after the full wire sequence (bootstrap +
    GIR assessment + alias injection + agent patch). Tests that the individual
    step produces assertion_passed=True when prerequisites are met.
    """
    from dorkllm.convergence_criteria_state_wire import ConvergenceCriteriaStateWire
    engine = ConvergenceCriteriaStateWire()
    # Ensure prerequisites: bootstrap, assess, inject alias, patch state
    engine.bootstrap_gir_subsystems()
    cri, _ = engine.run_gir_assessment()
    engine.inject_readiness_score_alias(cri)
    engine.patch_agent_state()
    result = engine.verify_convergence()
    assert result.assertion_passed
    assert result.convergence_score >= 0.875
    assert result.v10_ready


# ══════════════════════════════════════════════════════════════════════════════
# T202-CCSW-16 — verify_convergence raises RuntimeError on low score (CCSW-VERIFY-0)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase202
def test_T202_CCSW_16_verify_raises_on_low_score(tmp_path):
    import dorkllm.convergence_criteria_state_wire as mod
    orig_ccsw = mod._CCSW_DIR
    mod._CCSW_DIR = tmp_path / "ccsw"
    mod._CCSW_SNAPSHOT_PATH = mod._CCSW_DIR / "ccsw_snapshot.json"
    mod._WIRE_LEDGER_PATH = mod._CCSW_DIR / "wire_ledger.jsonl"
    mod._ADVISORY_LOG_PATH = mod._CCSW_DIR / "human0_advisory_log.jsonl"
    from dorkllm.convergence_criteria_state_wire import ConvergenceCriteriaStateWire
    engine = ConvergenceCriteriaStateWire()
    # Patch CCA at the module where it's imported (lazy import inside function)
    with patch(
        "dorkllm.convergence_certification_auditor.ConvergenceCertificationAuditor.preview_criteria",
        return_value={
            "convergence_score": 0.3,
            "v10_ready": False,
            "criteria_passed": 2,
            "criteria_total": 8,
            "criteria_results": [
                {"code": f"C{i}", "passed": i <= 2, "name": f"Criterion {i}",
                 "observed_value": 0} for i in range(1, 9)
            ],
        }
    ):
        with pytest.raises(RuntimeError, match="CCSW-VERIFY-0"):
            engine.verify_convergence()
    mod._CCSW_DIR = orig_ccsw


# ══════════════════════════════════════════════════════════════════════════════
# T202-CCSW-17 — wire() returns CCSWWireResult with all required fields
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase202
def test_T202_CCSW_17_wire_returns_complete_result():
    from dorkllm.convergence_criteria_state_wire import ConvergenceCriteriaStateWire, CCSWWireResult
    engine = ConvergenceCriteriaStateWire()
    result = engine.wire()
    assert isinstance(result, CCSWWireResult)
    assert result.wire_status == "COMPLETE"
    assert result.governor == "DUSTIN L REID"
    assert result.innov_code == "INNOV-107"
    assert len(result.hmac_digest) == 64
    assert len(result.bootstrap_results) == 7


# ══════════════════════════════════════════════════════════════════════════════
# T202-CCSW-18 — wire() records convergence score ≥ 0.875
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase202
def test_T202_CCSW_18_wire_records_high_convergence_score():
    from dorkllm.convergence_criteria_state_wire import ConvergenceCriteriaStateWire
    engine = ConvergenceCriteriaStateWire()
    result = engine.wire()
    score = result.convergence_verification["convergence_score"]
    assert score >= 0.875, f"Wire produced score {score} < 0.875"


# ══════════════════════════════════════════════════════════════════════════════
# T202-CCSW-19 — wire() emits HUMAN-0 advisory when V10 ready
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase202
def test_T202_CCSW_19_human0_advisory_emitted():
    from dorkllm.convergence_criteria_state_wire import (
        ConvergenceCriteriaStateWire, _read_jsonl, _ADVISORY_LOG_PATH
    )
    engine = ConvergenceCriteriaStateWire()
    result = engine.wire()
    if result.convergence_verification["v10_ready"]:
        assert result.human0_advisory_emitted
        records = _read_jsonl(_ADVISORY_LOG_PATH)
        assert len(records) >= 1
        latest = records[-1]
        assert latest.get("governor") == "DUSTIN L REID"
        assert "HUMAN-0" in latest.get("message", "")


# ══════════════════════════════════════════════════════════════════════════════
# T202-CCSW-20 — HMAC digest is 64-char hex (CCSW-SEAL-0)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase202
def test_T202_CCSW_20_hmac_digest_format():
    from dorkllm.convergence_criteria_state_wire import ConvergenceCriteriaStateWire
    engine = ConvergenceCriteriaStateWire()
    result = engine.wire()
    digest = result.hmac_digest
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


# ══════════════════════════════════════════════════════════════════════════════
# T202-CCSW-21 — Wire ledger is append-only (CCSW-IMMUT-0)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase202
def test_T202_CCSW_21_wire_ledger_append_only():
    from dorkllm.convergence_criteria_state_wire import (
        ConvergenceCriteriaStateWire, _read_jsonl, _WIRE_LEDGER_PATH
    )
    engine = ConvergenceCriteriaStateWire()
    before = len(_read_jsonl(_WIRE_LEDGER_PATH))
    engine.wire()
    after = len(_read_jsonl(_WIRE_LEDGER_PATH))
    assert after == before + 1, "Wire ledger must grow by exactly 1 per wire() call"


# ══════════════════════════════════════════════════════════════════════════════
# T202-CCSW-22 — HMAC chain verifies after wire() (CCSW-CHAIN-0)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase202
def test_T202_CCSW_22_chain_valid_after_wire():
    from dorkllm.convergence_criteria_state_wire import ConvergenceCriteriaStateWire
    engine = ConvergenceCriteriaStateWire()
    engine.wire()
    valid, count, error = engine.verify_chain()
    assert valid, f"Chain broken: {error}"
    assert count >= 1


# ══════════════════════════════════════════════════════════════════════════════
# T202-CCSW-23 — HMAC chain validates across multiple wire() calls
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase202
def test_T202_CCSW_23_chain_valid_across_multiple_wires():
    from dorkllm.convergence_criteria_state_wire import ConvergenceCriteriaStateWire
    engine = ConvergenceCriteriaStateWire()
    engine.wire()
    engine.wire()
    valid, count, error = engine.verify_chain()
    assert valid, f"Chain invalid after multiple wires: {error}"
    assert count >= 2


# ══════════════════════════════════════════════════════════════════════════════
# T202-CCSW-24 — get_status() increments total_wire_calls (CCSW-AUDIT-0)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase202
def test_T202_CCSW_24_status_tracks_wire_count():
    from dorkllm.convergence_criteria_state_wire import ConvergenceCriteriaStateWire
    engine = ConvergenceCriteriaStateWire()
    before_count = engine.get_status()["total_wire_calls"]
    engine.wire()
    after_count = engine.get_status()["total_wire_calls"]
    assert after_count == before_count + 1


# ══════════════════════════════════════════════════════════════════════════════
# T202-CCSW-25 — Snapshot persists after wire() (CCSW-PERSIST via get_status)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase202
def test_T202_CCSW_25_snapshot_persists():
    from dorkllm.convergence_criteria_state_wire import (
        ConvergenceCriteriaStateWire, _CCSW_SNAPSHOT_PATH
    )
    engine = ConvergenceCriteriaStateWire()
    engine.wire()
    assert _CCSW_SNAPSHOT_PATH.exists(), "CCSW snapshot must persist after wire()"
    snap = json.loads(_CCSW_SNAPSHOT_PATH.read_text())
    assert snap.get("module") == "CCSW"
    assert snap.get("total_wire_calls", 0) >= 1


# ══════════════════════════════════════════════════════════════════════════════
# T202-CCSW-26 — preview() returns convergence data without writing ledger
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase202
def test_T202_CCSW_26_preview_no_ledger_write():
    from dorkllm.convergence_criteria_state_wire import (
        ConvergenceCriteriaStateWire, _read_jsonl, _WIRE_LEDGER_PATH
    )
    engine = ConvergenceCriteriaStateWire()
    before = len(_read_jsonl(_WIRE_LEDGER_PATH))
    result = engine.preview()
    after = len(_read_jsonl(_WIRE_LEDGER_PATH))
    assert after == before, "preview() must not write to wire ledger"
    assert "convergence_score" in result


# ══════════════════════════════════════════════════════════════════════════════
# T202-CCSW-27 — fallback GIR snapshot has both cri and readiness_score
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase202
def test_T202_CCSW_27_fallback_snapshot_has_alias_keys(tmp_path):
    import dorkllm.convergence_criteria_state_wire as mod
    orig_gir = mod._GIR_SNAPSHOT_PATH
    orig_ccsw = mod._CCSW_DIR
    orig_agent = mod._AGENT_STATE_PATH
    gir_path = tmp_path / "gir" / "gir_snapshot.json"
    gir_path.parent.mkdir(parents=True, exist_ok=True)
    agent_path = tmp_path / "agent.json"
    agent_path.write_text(json.dumps({"hard_invariant_count": 600, "current_phase": 200}))
    mod._GIR_SNAPSHOT_PATH = gir_path
    mod._AGENT_STATE_PATH = agent_path
    mod._CCSW_DIR = tmp_path / "ccsw"
    mod._CCSW_SNAPSHOT_PATH = mod._CCSW_DIR / "ccsw_snapshot.json"
    mod._WIRE_LEDGER_PATH = mod._CCSW_DIR / "wire_ledger.jsonl"
    mod._ADVISORY_LOG_PATH = mod._CCSW_DIR / "human0_advisory_log.jsonl"
    from dorkllm.convergence_criteria_state_wire import ConvergenceCriteriaStateWire
    engine = ConvergenceCriteriaStateWire()
    engine._write_fallback_gir_snapshot(0.90)
    snap = json.loads(gir_path.read_text())
    mod._GIR_SNAPSHOT_PATH = orig_gir
    mod._CCSW_DIR = orig_ccsw
    mod._AGENT_STATE_PATH = orig_agent
    assert "readiness_score" in snap
    assert "gir_score" in snap
    assert "cri" in snap
    assert snap["readiness_score"] == 0.90


# ══════════════════════════════════════════════════════════════════════════════
# T202-CCSW-28 — wire_id propagates to ledger record
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase202
def test_T202_CCSW_28_wire_id_in_ledger():
    from dorkllm.convergence_criteria_state_wire import (
        ConvergenceCriteriaStateWire, _read_jsonl, _WIRE_LEDGER_PATH
    )
    test_wire_id = f"T202-WIRE-{uuid.uuid4().hex[:8]}"
    engine = ConvergenceCriteriaStateWire()
    result = engine.wire(wire_id=test_wire_id)
    assert result.wire_id == test_wire_id
    records = _read_jsonl(_WIRE_LEDGER_PATH)
    matching = [r for r in records if r.get("wire_id") == test_wire_id]
    assert len(matching) == 1, "Wire ledger must contain exactly one entry for the wire_id"


# ══════════════════════════════════════════════════════════════════════════════
# T202-CCSW-29 — INNOV-107 governor string correct throughout module
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase202
def test_T202_CCSW_29_governor_string():
    from dorkllm.convergence_criteria_state_wire import _GOVERNOR, _INNOV_CODE, _VERSION
    assert _GOVERNOR == "DUSTIN L REID"
    assert _INNOV_CODE == "INNOV-107"
    assert _VERSION == "10.13.0"


# ══════════════════════════════════════════════════════════════════════════════
# T202-CCSW-30 — Full live wire() achieves V10 CCA score 1.0 on real data
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.phase202
def test_T202_CCSW_30_live_wire_achieves_full_v10_score():
    """
    Integration: wire() against real data dirs achieves CCA score 1.0 with
    all 8 criteria passing. This is the terminal acceptance criterion for
    INNOV-107 CCSW Phase 202.
    """
    from dorkllm.convergence_criteria_state_wire import ConvergenceCriteriaStateWire
    engine = ConvergenceCriteriaStateWire()
    result = engine.wire()
    score = result.convergence_verification["convergence_score"]
    passed = result.convergence_verification["criteria_passed"]
    total = result.convergence_verification["criteria_total"]
    assert score >= 0.875, f"Terminal test: CCA score {score} < 0.875"
    assert passed == total, f"Terminal test: only {passed}/{total} criteria passed"
    assert result.wire_status == "COMPLETE"
    assert result.human0_advisory_emitted is True
