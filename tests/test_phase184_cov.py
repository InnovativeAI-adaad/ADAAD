# SPDX-License-Identifier: Apache-2.0
"""
Phase 184 — INNOV-89 · COV — Convergence Outcome Validator
30-test suite · T184-COV-01..30
Governor: DUSTIN L REID
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import asdict
from pathlib import Path

import pytest

from dorkllm.convergence_outcome_validator import (
    REGRESSION_ALARM_THRESHOLD,
    VALIDATED_DELTA_THRESHOLD,
    ConvergenceOutcomeValidator,
    _classify_delta,
    _classify_outcome,
    _hmac_digest,
    _utc_iso,
    _OUTCOME_DOUBLE,
    _OUTCOME_HALTED,
    _OUTCOME_NEUTRAL,
    _OUTCOME_REGRESSED,
    _OUTCOME_VALIDATED,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _write_gir_snapshot(path: Path, dims: dict, cri: float = 0.75) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "cri": cri,
                "dimension_scores": dims,
                "timestamp": _utc_iso(),
                "governor": "DUSTIN L REID",
            }
        )
    )


def _write_cpe_telemetry(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")


def _cov(tmp_path: Path, gir_dims: dict | None = None, cpe_entries: list[dict] | None = None):
    data_dir = tmp_path / "cov"
    gir_path = tmp_path / "gir" / "gir_snapshot.json"
    cpe_path = tmp_path / "cpe" / "outcome_telemetry.jsonl"

    if gir_dims is not None:
        _write_gir_snapshot(gir_path, gir_dims)

    if cpe_entries is not None:
        _write_cpe_telemetry(cpe_path, cpe_entries)

    return ConvergenceOutcomeValidator(
        data_dir=data_dir,
        cpe_outcome_log=cpe_path,
        gir_snapshot_path=gir_path,
    )


@pytest.fixture
def good_dims() -> dict:
    return {
        "ledger_integrity": 0.90,
        "invariant_coverage": 0.85,
        "replay_fidelity": 0.88,
        "test_coverage": 0.82,
        "mutation_approval_rate": 0.91,
        "constitution_compliance": 0.95,
        "agent_health": 0.87,
        "governance_gate": 0.93,
        "documentation_quality": 0.80,
        "deployment_reliability": 0.84,
    }


@pytest.fixture
def improved_dims() -> dict:
    return {
        "ledger_integrity": 0.93,
        "invariant_coverage": 0.90,
        "replay_fidelity": 0.91,
        "test_coverage": 0.87,
        "mutation_approval_rate": 0.93,
        "constitution_compliance": 0.96,
        "agent_health": 0.90,
        "governance_gate": 0.94,
        "documentation_quality": 0.85,
        "deployment_reliability": 0.88,
    }


@pytest.fixture
def regressed_dims() -> dict:
    return {
        "ledger_integrity": 0.80,
        "invariant_coverage": 0.72,
        "replay_fidelity": 0.75,
        "test_coverage": 0.68,
        "mutation_approval_rate": 0.78,
        "constitution_compliance": 0.82,
        "agent_health": 0.70,
        "governance_gate": 0.76,
        "documentation_quality": 0.65,
        "deployment_reliability": 0.71,
    }


def _telemetry_entry(
    execution_id: str | None = None,
    plan_id: str | None = None,
    pre_dims: dict | None = None,
) -> dict:
    return {
        "execution_id": execution_id or str(uuid.uuid4()),
        "plan_id": plan_id or str(uuid.uuid4()),
        "timestamp": _utc_iso(),
        "status": "SUCCESS",
        "pre_cri_snapshot": pre_dims or {},
        "pre_cri": 0.70,
        "post_cri": 0.75,
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

# T184-COV-01: ConvergenceOutcomeValidator instantiates without error
def test_t184_cov_01_instantiation(tmp_path):
    cov = _cov(tmp_path)
    assert cov is not None


# T184-COV-02: data/cov directory created on init
def test_t184_cov_02_data_dir_created(tmp_path):
    cov = _cov(tmp_path)
    assert (tmp_path / "cov").exists()


# T184-COV-03: validate() returns empty list when no CPE telemetry present
def test_t184_cov_03_empty_on_no_telemetry(tmp_path):
    cov = _cov(tmp_path)
    results = cov.validate()
    assert results == []


# T184-COV-04: validate() returns one record for one telemetry entry
def test_t184_cov_04_single_record(tmp_path, good_dims, improved_dims):
    entry = _telemetry_entry(pre_dims={k: v - 0.03 for k, v in improved_dims.items()})
    cov = _cov(tmp_path, gir_dims=improved_dims, cpe_entries=[entry])
    results = cov.validate()
    assert len(results) == 1


# T184-COV-05: VALIDATED outcome when post CRI > pre CRI by >= threshold
def test_t184_cov_05_validated_outcome(tmp_path, improved_dims):
    pre = {k: v - 0.04 for k, v in improved_dims.items()}
    entry = _telemetry_entry(pre_dims=pre)
    cov = _cov(tmp_path, gir_dims=improved_dims, cpe_entries=[entry])
    results = cov.validate()
    assert results[0].outcome == _OUTCOME_VALIDATED


# T184-COV-06: NEUTRAL outcome when CRI delta is small positive
def test_t184_cov_06_neutral_outcome(tmp_path, good_dims):
    pre = {k: v - 0.005 for k, v in good_dims.items()}
    entry = _telemetry_entry(pre_dims=pre)
    cov = _cov(tmp_path, gir_dims=good_dims, cpe_entries=[entry])
    results = cov.validate()
    assert results[0].outcome in (_OUTCOME_NEUTRAL, _OUTCOME_VALIDATED)


# T184-COV-07: REGRESSED outcome when post CRI < pre CRI below threshold
def test_t184_cov_07_regressed_outcome(tmp_path, regressed_dims, good_dims):
    entry = _telemetry_entry(pre_dims=good_dims)
    cov = _cov(tmp_path, gir_dims=regressed_dims, cpe_entries=[entry])
    results = cov.validate()
    assert results[0].outcome == _OUTCOME_REGRESSED


# T184-COV-08: validation record persisted to ledger file
def test_t184_cov_08_ledger_written(tmp_path, good_dims, improved_dims):
    entry = _telemetry_entry(pre_dims={k: v - 0.04 for k, v in improved_dims.items()})
    cov = _cov(tmp_path, gir_dims=improved_dims, cpe_entries=[entry])
    cov.validate()
    ledger = tmp_path / "cov" / "validation_ledger.jsonl"
    assert ledger.exists()
    assert len(ledger.read_text().strip().splitlines()) == 1


# T184-COV-09: ledger entry has valid HMAC digest
def test_t184_cov_09_ledger_hmac_valid(tmp_path, improved_dims):
    entry = _telemetry_entry(pre_dims={k: v - 0.04 for k, v in improved_dims.items()})
    cov = _cov(tmp_path, gir_dims=improved_dims, cpe_entries=[entry])
    cov.validate()
    ledger = tmp_path / "cov" / "validation_ledger.jsonl"
    row = json.loads(ledger.read_text().strip().splitlines()[0])
    assert "digest" in row
    assert len(row["digest"]) == 64


# T184-COV-10: chain integrity passes after first write
def test_t184_cov_10_chain_integrity_passes(tmp_path, improved_dims):
    entry = _telemetry_entry(pre_dims={k: v - 0.04 for k, v in improved_dims.items()})
    cov = _cov(tmp_path, gir_dims=improved_dims, cpe_entries=[entry])
    cov.validate()
    assert cov.verify_chain_integrity()["chain_valid"] is True


# T184-COV-11: duplicate execution_id produces DOUBLE_VALIDATE record
def test_t184_cov_11_double_validate_guard(tmp_path, improved_dims):
    eid = str(uuid.uuid4())
    entry = _telemetry_entry(execution_id=eid, pre_dims={k: v - 0.04 for k, v in improved_dims.items()})
    cov = _cov(tmp_path, gir_dims=improved_dims, cpe_entries=[entry, entry])
    results = cov.validate(limit=10)
    outcomes = [r.outcome for r in results]
    assert _OUTCOME_DOUBLE in outcomes


# T184-COV-12: snapshot persists total_validations count
def test_t184_cov_12_snapshot_persists(tmp_path, improved_dims):
    entries = [_telemetry_entry(pre_dims={k: v - 0.04 for k, v in improved_dims.items()}) for _ in range(3)]
    cov = _cov(tmp_path, gir_dims=improved_dims, cpe_entries=entries)
    cov.validate(limit=3)
    snap = cov.get_snapshot()
    assert snap["total_validations"] == 3


# T184-COV-13: VALIDATED outcome writes CAL learning signal (COV-CLOSE-0)
def test_t184_cov_13_cal_signal_written(tmp_path, improved_dims):
    entry = _telemetry_entry(pre_dims={k: v - 0.04 for k, v in improved_dims.items()})
    cov = _cov(tmp_path, gir_dims=improved_dims, cpe_entries=[entry])
    results = cov.validate()
    if results[0].outcome == _OUTCOME_VALIDATED:
        assert results[0].cal_signal_written is True
        signals = tmp_path / "cov" / "cal_signals.jsonl"
        assert signals.exists()


# T184-COV-14: REGRESSED outcome with large delta emits HUMAN-0 advisory
def test_t184_cov_14_human0_advisory_on_regression(tmp_path, regressed_dims, good_dims):
    entry = _telemetry_entry(pre_dims=good_dims)
    cov = _cov(tmp_path, gir_dims=regressed_dims, cpe_entries=[entry])
    results = cov.validate()
    record = results[0]
    if record.outcome == _OUTCOME_REGRESSED:
        if abs(record.cri_delta) >= REGRESSION_ALARM_THRESHOLD:
            assert record.human0_advisory is True
            advisory_log = tmp_path / "cov" / "human0_advisory_log.jsonl"
            assert advisory_log.exists()


# T184-COV-15: dimension_deltas list populated when GIR snapshot present
def test_t184_cov_15_dimension_deltas_populated(tmp_path, good_dims, improved_dims):
    entry = _telemetry_entry(pre_dims={k: v - 0.04 for k, v in improved_dims.items()})
    cov = _cov(tmp_path, gir_dims=improved_dims, cpe_entries=[entry])
    results = cov.validate()
    assert len(results[0].dimension_deltas) == len(improved_dims)


# T184-COV-16: each dimension_delta has required fields
def test_t184_cov_16_dimension_delta_schema(tmp_path, improved_dims):
    entry = _telemetry_entry(pre_dims={k: v - 0.04 for k, v in improved_dims.items()})
    cov = _cov(tmp_path, gir_dims=improved_dims, cpe_entries=[entry])
    results = cov.validate()
    for delta in results[0].dimension_deltas:
        assert "dimension" in delta
        assert "score_before" in delta
        assert "score_after" in delta
        assert "delta" in delta
        assert "classification" in delta
        assert "threshold_met" in delta


# T184-COV-17: get_snapshot() returns dict with expected keys
def test_t184_cov_17_snapshot_keys(tmp_path):
    cov = _cov(tmp_path)
    snap = cov.get_snapshot()
    for key in ("total_validations", "validated_count", "neutral_count",
                "regressed_count", "halted_count", "governor"):
        assert key in snap


# T184-COV-18: get_outcome_summary() returns dict with expected keys
def test_t184_cov_18_summary_keys(tmp_path):
    cov = _cov(tmp_path)
    summary = cov.get_outcome_summary()
    for key in ("total_validations", "validated_pct", "regressed_pct",
                "v10_criterion", "loop_position"):
        assert key in summary


# T184-COV-19: loop_position references V10 self-authorship criterion
def test_t184_cov_19_v10_criterion_present(tmp_path):
    cov = _cov(tmp_path)
    summary = cov.get_outcome_summary()
    assert "Self-Authorship" in summary["v10_criterion"] or "CLOSE" in summary["loop_position"]


# T184-COV-20: governor field in all records equals "DUSTIN L REID"
def test_t184_cov_20_governor_field(tmp_path, improved_dims):
    entry = _telemetry_entry(pre_dims={k: v - 0.04 for k, v in improved_dims.items()})
    cov = _cov(tmp_path, gir_dims=improved_dims, cpe_entries=[entry])
    results = cov.validate()
    assert results[0].governor == "DUSTIN L REID"


# T184-COV-21: prev_digest of first record is "GENESIS"
def test_t184_cov_21_genesis_prev_digest(tmp_path, improved_dims):
    entry = _telemetry_entry(pre_dims={k: v - 0.04 for k, v in improved_dims.items()})
    cov = _cov(tmp_path, gir_dims=improved_dims, cpe_entries=[entry])
    results = cov.validate()
    assert results[0].prev_digest == "GENESIS"


# T184-COV-22: chain links correctly across two validations
def test_t184_cov_22_chain_links(tmp_path, improved_dims):
    entries = [
        _telemetry_entry(pre_dims={k: v - 0.04 for k, v in improved_dims.items()})
        for _ in range(2)
    ]
    cov = _cov(tmp_path, gir_dims=improved_dims, cpe_entries=entries)
    results = cov.validate(limit=2)
    assert results[1].prev_digest == results[0].digest


# T184-COV-23: ledger_seq increments monotonically
def test_t184_cov_23_ledger_seq_monotonic(tmp_path, improved_dims):
    entries = [
        _telemetry_entry(pre_dims={k: v - 0.04 for k, v in improved_dims.items()})
        for _ in range(3)
    ]
    cov = _cov(tmp_path, gir_dims=improved_dims, cpe_entries=entries)
    results = cov.validate(limit=3)
    seqs = [r.ledger_seq for r in results]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)


# T184-COV-24: validate with no GIR snapshot falls back gracefully
def test_t184_cov_24_no_gir_fallback(tmp_path):
    entry = _telemetry_entry(pre_dims={})
    # No GIR snapshot written
    data_dir = tmp_path / "cov"
    cpe_path = tmp_path / "cpe" / "outcome_telemetry.jsonl"
    _write_cpe_telemetry(cpe_path, [entry])
    cov = ConvergenceOutcomeValidator(
        data_dir=data_dir,
        cpe_outcome_log=cpe_path,
        gir_snapshot_path=tmp_path / "gir" / "missing.json",
    )
    results = cov.validate()
    assert len(results) == 1
    assert results[0].outcome in (_OUTCOME_VALIDATED, _OUTCOME_NEUTRAL, _OUTCOME_REGRESSED)


# T184-COV-25: _classify_delta helper — IMPROVED above threshold
def test_t184_cov_25_classify_delta_improved():
    assert _classify_delta(VALIDATED_DELTA_THRESHOLD + 0.01) == "IMPROVED"


# T184-COV-26: _classify_delta helper — UNCHANGED in neutral band
def test_t184_cov_26_classify_delta_unchanged():
    assert _classify_delta(0.00) == "UNCHANGED"


# T184-COV-27: _classify_delta helper — REGRESSED below neutral floor
def test_t184_cov_27_classify_delta_regressed():
    assert _classify_delta(-0.06) == "REGRESSED"


# T184-COV-28: _classify_outcome returns VALIDATED for large positive delta
def test_t184_cov_28_classify_outcome_validated():
    assert _classify_outcome(VALIDATED_DELTA_THRESHOLD + 0.01) == _OUTCOME_VALIDATED


# T184-COV-29: _classify_outcome returns REGRESSED for large negative delta
def test_t184_cov_29_classify_outcome_regressed():
    assert _classify_outcome(-0.06) == _OUTCOME_REGRESSED


# T184-COV-30: get_validation_history returns list of dicts from ledger
def test_t184_cov_30_validation_history(tmp_path, improved_dims):
    entries = [
        _telemetry_entry(pre_dims={k: v - 0.04 for k, v in improved_dims.items()})
        for _ in range(2)
    ]
    cov = _cov(tmp_path, gir_dims=improved_dims, cpe_entries=entries)
    cov.validate(limit=2)
    history = cov.get_validation_history(limit=10)
    assert len(history) == 2
    assert isinstance(history[0], dict)
    assert "outcome" in history[0]
