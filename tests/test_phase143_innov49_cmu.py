# SPDX-License-Identifier: Apache-2.0
"""
tests/test_phase143_innov49_cmu.py
Phase 143 · INNOV-49 · Constitutional Model Upgrade (CMU)

30-test acceptance suite.
Constitutional invariants under test: CMU-CTX-0, CMU-TEMP-0, CMU-BENCH-0,
                                       CMU-DETERM-0, CMU-HUMAN0-0
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from dorkllm.model_validator import (
    CMU_MIN_CTX,
    CMU_MAX_TEMP,
    CMUCtxViolation,
    CMUTempViolation,
    CMUInvariantViolation,
    CMULedgerWriteError,
    ModelfileParams,
    parse_modelfile,
    assert_ctx,
    assert_temperature,
    validate_modelfile,
    append_cmu_ledger,
    run_benchmark,
    full_cmu_validation,
    GOVERNANCE_BENCHMARK,
)

pytestmark = pytest.mark.phase143


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _write_modelfile(tmp_path: Path, num_ctx: int = 32768, temperature: float = 0.07,
                     base: str = "phi4:14b-q4_K_M") -> Path:
    mf = tmp_path / "Modelfile"
    mf.write_text(
        f"FROM {base}\n"
        f"PARAMETER num_ctx {num_ctx}\n"
        f"PARAMETER temperature {temperature}\n"
        f"PARAMETER top_p 0.92\n"
        f"PARAMETER repeat_penalty 1.12\n"
        f'PARAMETER stop "<execute>"\n'
        f'SYSTEM """test system"""\n',
        encoding="utf-8",
    )
    return mf


# ── Group 1: Modelfile parser (tests 1–6) ────────────────────────────────────

class TestModelfileParser:
    def test_01_parse_base_model(self, tmp_path):
        """Modelfile parser extracts FROM directive correctly."""
        mf = _write_modelfile(tmp_path)
        params = parse_modelfile(mf)
        assert params.base_model == "phi4:14b-q4_K_M"

    def test_02_parse_num_ctx(self, tmp_path):
        """Modelfile parser extracts num_ctx as integer."""
        mf = _write_modelfile(tmp_path, num_ctx=32768)
        params = parse_modelfile(mf)
        assert params.num_ctx == 32768

    def test_03_parse_temperature(self, tmp_path):
        """Modelfile parser extracts temperature as float."""
        mf = _write_modelfile(tmp_path, temperature=0.07)
        params = parse_modelfile(mf)
        assert params.temperature == pytest.approx(0.07)

    def test_04_parse_comments_ignored(self, tmp_path):
        """Comment lines in Modelfile do not affect parsed values."""
        mf = tmp_path / "Modelfile"
        mf.write_text(
            "# This is a comment\nFROM llama3.2:latest\n"
            "PARAMETER num_ctx 16384\nPARAMETER temperature 0.07\n",
            encoding="utf-8",
        )
        params = parse_modelfile(mf)
        assert params.base_model == "llama3.2:latest"
        assert params.num_ctx == 16384

    def test_05_parse_missing_file_raises(self, tmp_path):
        """parse_modelfile raises FileNotFoundError for absent Modelfile."""
        with pytest.raises(FileNotFoundError):
            parse_modelfile(tmp_path / "nonexistent_Modelfile")

    def test_06_parse_raw_parameters_populated(self, tmp_path):
        """raw_parameters dict captures all PARAMETER directives."""
        mf = _write_modelfile(tmp_path)
        params = parse_modelfile(mf)
        assert "num_ctx" in params.raw_parameters
        assert "temperature" in params.raw_parameters
        assert "top_p" in params.raw_parameters


# ── Group 2: CMU-CTX-0 enforcement (tests 7–11) ──────────────────────────────

class TestCMUCtx0:
    def test_07_ctx_passes_at_minimum(self):
        """assert_ctx passes when num_ctx equals CMU_MIN_CTX (16384)."""
        params = ModelfileParams(num_ctx=CMU_MIN_CTX)
        assert_ctx(params)  # no exception

    def test_08_ctx_passes_above_minimum(self):
        """assert_ctx passes when num_ctx > CMU_MIN_CTX."""
        params = ModelfileParams(num_ctx=32768)
        assert_ctx(params)  # no exception

    def test_09_ctx_violation_below_minimum(self):
        """assert_ctx raises CMUCtxViolation when num_ctx < CMU_MIN_CTX."""
        params = ModelfileParams(num_ctx=8192)
        with pytest.raises(CMUCtxViolation) as exc_info:
            assert_ctx(params)
        assert "CMU-CTX-0" in str(exc_info.value)
        assert "8192" in str(exc_info.value)

    def test_10_ctx_violation_zero(self):
        """assert_ctx raises CMUCtxViolation for num_ctx=0 (unparsed Modelfile)."""
        params = ModelfileParams(num_ctx=0)
        with pytest.raises(CMUCtxViolation):
            assert_ctx(params)

    def test_11_ctx_violation_message_contains_minimum(self):
        """CMUCtxViolation message references the constitutional minimum."""
        params = ModelfileParams(num_ctx=4096)
        with pytest.raises(CMUCtxViolation) as exc_info:
            assert_ctx(params)
        assert str(CMU_MIN_CTX) in str(exc_info.value)


# ── Group 3: CMU-TEMP-0 enforcement (tests 12–16) ────────────────────────────

class TestCMUTemp0:
    def test_12_temp_passes_at_maximum(self):
        """assert_temperature passes when temperature equals CMU_MAX_TEMP (0.10)."""
        params = ModelfileParams(temperature=CMU_MAX_TEMP)
        assert_temperature(params)  # no exception

    def test_13_temp_passes_below_maximum(self):
        """assert_temperature passes when temperature < CMU_MAX_TEMP."""
        params = ModelfileParams(temperature=0.07)
        assert_temperature(params)  # no exception

    def test_14_temp_violation_above_maximum(self):
        """assert_temperature raises CMUTempViolation when temperature > 0.10."""
        params = ModelfileParams(temperature=0.5)
        with pytest.raises(CMUTempViolation) as exc_info:
            assert_temperature(params)
        assert "CMU-TEMP-0" in str(exc_info.value)

    def test_15_temp_violation_message_contains_max(self):
        """CMUTempViolation message references the constitutional maximum."""
        params = ModelfileParams(temperature=1.0)
        with pytest.raises(CMUTempViolation) as exc_info:
            assert_temperature(params)
        assert str(CMU_MAX_TEMP) in str(exc_info.value)

    def test_16_temp_zero_passes(self):
        """assert_temperature passes for temperature=0 (deterministic mode)."""
        params = ModelfileParams(temperature=0.0)
        assert_temperature(params)  # no exception


# ── Group 4: validate_modelfile integration (tests 17–19) ────────────────────

class TestValidateModelfile:
    def test_17_valid_modelfile_passes(self, tmp_path):
        """validate_modelfile returns params for a constitutional Modelfile."""
        mf = _write_modelfile(tmp_path)
        params = validate_modelfile(mf)
        assert params.num_ctx == 32768
        assert params.temperature == pytest.approx(0.07)

    def test_18_invalid_ctx_raises(self, tmp_path):
        """validate_modelfile raises CMUCtxViolation for small num_ctx."""
        mf = _write_modelfile(tmp_path, num_ctx=4096)
        with pytest.raises(CMUCtxViolation):
            validate_modelfile(mf)

    def test_19_invalid_temp_raises(self, tmp_path):
        """validate_modelfile raises CMUTempViolation for high temperature."""
        mf = _write_modelfile(tmp_path, temperature=0.8)
        with pytest.raises(CMUTempViolation):
            validate_modelfile(mf)


# ── Group 5: CMU-DETERM-0 ledger (tests 20–23) ───────────────────────────────

class TestCMULedger:
    def test_20_ledger_entry_written(self, tmp_path):
        """append_cmu_ledger writes an entry to the ledger file."""
        params = ModelfileParams(base_model="phi4:14b-q4_K_M", num_ctx=32768, temperature=0.07)
        ledger = tmp_path / "cmu_ledger.jsonl"
        mf = _write_modelfile(tmp_path)
        entry = append_cmu_ledger("test_event", params, ledger_path=ledger, modelfile_path=mf)
        assert ledger.exists()
        assert entry.entry_hash != ""

    def test_21_ledger_is_hash_chained(self, tmp_path):
        """Two consecutive ledger entries form a valid hash chain."""
        params = ModelfileParams(base_model="phi4:14b-q4_K_M", num_ctx=32768, temperature=0.07)
        ledger = tmp_path / "cmu_ledger.jsonl"
        mf = _write_modelfile(tmp_path)
        e1 = append_cmu_ledger("event_1", params, ledger_path=ledger, modelfile_path=mf)
        e2 = append_cmu_ledger("event_2", params, ledger_path=ledger, modelfile_path=mf)
        assert e2.prev_hash == e1.entry_hash

    def test_22_ledger_seq_increments(self, tmp_path):
        """Ledger seq numbers increment correctly across appends."""
        params = ModelfileParams(base_model="phi4:14b-q4_K_M", num_ctx=32768, temperature=0.07)
        ledger = tmp_path / "cmu_ledger.jsonl"
        mf = _write_modelfile(tmp_path)
        e1 = append_cmu_ledger("event_1", params, ledger_path=ledger, modelfile_path=mf)
        e2 = append_cmu_ledger("event_2", params, ledger_path=ledger, modelfile_path=mf)
        assert e1.seq == 0
        assert e2.seq == 1

    def test_23_ledger_entry_is_valid_json(self, tmp_path):
        """Each ledger line is valid JSON with all required fields."""
        params = ModelfileParams(base_model="phi4:14b-q4_K_M", num_ctx=32768, temperature=0.07)
        ledger = tmp_path / "cmu_ledger.jsonl"
        mf = _write_modelfile(tmp_path)
        append_cmu_ledger("test_event", params, ledger_path=ledger, modelfile_path=mf)
        lines = [l.strip() for l in ledger.read_text().splitlines() if l.strip()]
        assert len(lines) == 1
        entry = json.loads(lines[0])
        for field in ("seq", "event", "base_model", "num_ctx", "temperature",
                      "modelfile_digest", "timestamp", "ratified_by_human0",
                      "prev_hash", "entry_hash"):
            assert field in entry, f"Missing field: {field}"


# ── Group 6: CMU-BENCH-0 benchmark suite (tests 24–27) ───────────────────────

class TestCMUBench0:
    def _perfect_ask(self, query: str) -> str:
        """Returns a response containing all expected keywords for every benchmark item."""
        all_keywords = []
        for item in GOVERNANCE_BENCHMARK:
            all_keywords.extend(item["expected_keywords"])
        return " ".join(all_keywords)

    def _failing_ask(self, query: str) -> str:
        """Returns empty response — all benchmark items fail."""
        return ""

    def test_24_benchmark_has_30_questions(self):
        """GOVERNANCE_BENCHMARK contains exactly 30 questions (CMU-BENCH-0)."""
        assert len(GOVERNANCE_BENCHMARK) == 30

    def test_25_benchmark_passes_with_perfect_responses(self):
        """run_benchmark passes when ask_fn returns all expected keywords."""
        result = run_benchmark(self._perfect_ask)
        assert result["passed"] == 30
        assert result["passed_threshold"] is True

    def test_26_benchmark_fails_below_threshold(self):
        """run_benchmark raises CMUInvariantViolation when pass_rate < 0.85."""
        with pytest.raises(CMUInvariantViolation) as exc_info:
            run_benchmark(self._failing_ask)
        assert "CMU-BENCH-0" in str(exc_info.value)

    def test_27_benchmark_categories_present(self):
        """Benchmark covers required governance categories."""
        categories = {item["category"] for item in GOVERNANCE_BENCHMARK}
        required = {"identity", "invariants", "governance", "world-first", "model"}
        assert required <= categories


# ── Group 7: full_cmu_validation and CMU-HUMAN0-0 (tests 28–30) ──────────────

class TestFullCMUValidation:
    def test_28_full_validation_returns_ok(self, tmp_path):
        """full_cmu_validation returns ok=True for a constitutional Modelfile."""
        mf = _write_modelfile(tmp_path)
        ledger = tmp_path / "cmu_ledger.jsonl"
        result = full_cmu_validation(modelfile_path=mf, ledger_path=ledger)
        assert result["ok"] is True
        assert result["cmu_ctx_0"] == "pass"
        assert result["cmu_temp_0"] == "pass"

    def test_29_full_validation_records_ledger_entry(self, tmp_path):
        """full_cmu_validation writes a ledger entry (CMU-DETERM-0)."""
        mf = _write_modelfile(tmp_path)
        ledger = tmp_path / "cmu_ledger.jsonl"
        result = full_cmu_validation(modelfile_path=mf, ledger_path=ledger)
        assert ledger.exists()
        assert result["ledger_seq"] == 0
        assert result["ledger_entry_hash"] is not None

    def test_30_human0_ratification_field_in_ledger(self, tmp_path):
        """CMU-HUMAN0-0: ratified_by_human0 field exists and defaults to False in CMU ledger."""
        params = ModelfileParams(base_model="phi4:14b-q4_K_M", num_ctx=32768, temperature=0.07)
        ledger = tmp_path / "cmu_ledger.jsonl"
        mf = _write_modelfile(tmp_path)
        entry = append_cmu_ledger(
            "model_built", params,
            ratified_by_human0=False,
            ledger_path=ledger,
            modelfile_path=mf,
        )
        assert entry.ratified_by_human0 is False
        # Verify persisted
        raw = json.loads(ledger.read_text().strip())
        assert raw["ratified_by_human0"] is False
