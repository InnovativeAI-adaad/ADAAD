# SPDX-License-Identifier: Apache-2.0
"""Phase 207 · INNOV-112 · CMWE — 30-test acceptance suite."""
import json
import time
import pytest
from pathlib import Path

from dorkllm.constitutional_mutation_window_executor import (
    ConstitutionalMutationWindowExecutor,
    CMWEAuthError,
    CMWEChainError,
    CMWEError,
    CMWEImmutError,
    CMWEPreCheckError,
    CMWEScopeError,
    CMWETimeoutError,
    ExecutionOutcome,
    WindowStage,
    GOVERNOR,
    INNOV_CODE,
    PHASE,
)

pytestmark = pytest.mark.cmwe_exec


@pytest.fixture
def eng(tmp_path):
    return ConstitutionalMutationWindowExecutor(
        ledger_path=tmp_path / "cmwe" / "ledger.jsonl",
        hmac_secret=b"test-cmwe-secret",
        min_fitness=0.5,
        max_duration_ms=5000,
    )


def _reg(eng, wid="w1", blast=2, scope=None, fitness=1.0):
    return eng.register(wid, f"prop-{wid}", blast, scope or ["mod_a"], fitness)


# T207-CMWE-01: register creates PENDING window
def test_01_register_creates_pending(eng):
    w = _reg(eng)
    assert w.stage == WindowStage.PENDING.value


# T207-CMWE-02: execute SUCCESS path
def test_02_execute_success(eng):
    _reg(eng)
    rec = eng.execute("w1", execution_fn=lambda w: True)
    assert rec.outcome == ExecutionOutcome.SUCCESS.value


# T207-CMWE-03: execute FAILED path
def test_03_execute_failed(eng):
    _reg(eng)
    rec = eng.execute("w1", execution_fn=lambda w: False)
    assert rec.outcome == ExecutionOutcome.FAILED.value


# T207-CMWE-04: CMWE-ATOMIC-0 — exception in fn → FAILED
def test_04_atomic_exception_is_failed(eng):
    _reg(eng)
    def boom(w): raise RuntimeError("boom")
    rec = eng.execute("w1", execution_fn=boom)
    assert rec.outcome == ExecutionOutcome.FAILED.value


# T207-CMWE-05: CMWE-HUMAN0-0 — TIER0 without identity raises
def test_05_tier0_requires_human0(eng):
    _reg(eng, blast=0)
    with pytest.raises(CMWEAuthError):
        eng.execute("w1", human0_identity=None)


# T207-CMWE-06: TIER0 with HUMAN-0 succeeds
def test_06_tier0_with_human0_succeeds(eng):
    _reg(eng, blast=0)
    rec = eng.execute("w1", human0_identity="DUSTIN L REID")
    assert rec.outcome == ExecutionOutcome.SUCCESS.value
    assert rec.human0_identity == "DUSTIN L REID"


# T207-CMWE-07: CMWE-PRECHECK-0 — low fitness rejected
def test_07_low_fitness_rejected(eng):
    _reg(eng, fitness=0.1)
    with pytest.raises(CMWEPreCheckError):
        eng.execute("w1")


# T207-CMWE-08: CMWE-SCOPE-0 — empty scope at execution time
def test_08_empty_scope_rejected(eng):
    eng.register("w1", "prop-w1", 2, [], 1.0)
    with pytest.raises(CMWEScopeError):
        eng.execute("w1")


# T207-CMWE-09: CMWE-IMMUT-0 — double execute raises
def test_09_double_execute_raises(eng):
    _reg(eng)
    eng.execute("w1")
    with pytest.raises(CMWEImmutError):
        eng.execute("w1")


# T207-CMWE-10: CMWE-CHAIN-0 — ledger verifies clean after success
def test_10_ledger_verifies_clean(eng):
    _reg(eng)
    eng.execute("w1")
    assert eng.verify_ledger() is True


# T207-CMWE-11: CMWE-CHAIN-0 — tampered ledger detected
def test_11_tampered_ledger_fails(eng):
    _reg(eng)
    eng.execute("w1")
    content = eng._ledger_path.read_text()
    lines = content.splitlines()
    r = json.loads(lines[0])
    r["outcome"] = "TAMPERED"
    lines[0] = json.dumps(r)
    eng._ledger_path.write_text("\n".join(lines) + "\n")
    assert eng.verify_ledger() is False


# T207-CMWE-12: CMWE-AUDIT-0 — success appended
def test_12_success_appended_to_ledger(eng):
    _reg(eng)
    eng.execute("w1")
    recs = eng.attestation_records()
    assert any(r["outcome"] == ExecutionOutcome.SUCCESS.value for r in recs)


# T207-CMWE-13: CMWE-AUDIT-0 — rejection appended
def test_13_rejection_appended_to_ledger(eng):
    _reg(eng, fitness=0.1)
    try:
        eng.execute("w1")
    except CMWEPreCheckError:
        pass
    recs = eng.attestation_records()
    assert any(r["outcome"] == ExecutionOutcome.REJECTED.value for r in recs)


# T207-CMWE-14: CMWE-FEEDBACK-0 — feedback emitted after success
def test_14_feedback_emitted_on_success(eng):
    _reg(eng)
    eng.execute("w1")
    fb = eng.get_feedback_log()
    assert len(fb) == 1
    assert fb[0].outcome == ExecutionOutcome.SUCCESS.value


# T207-CMWE-15: CMWE-FEEDBACK-0 — feedback emitted after failure
def test_15_feedback_emitted_on_failure(eng):
    _reg(eng)
    eng.execute("w1", execution_fn=lambda w: False)
    fb = eng.get_feedback_log()
    assert any(f.outcome == ExecutionOutcome.FAILED.value for f in fb)


# T207-CMWE-16: fitness_delta computed correctly
def test_16_fitness_delta_correct(eng):
    _reg(eng, fitness=0.8)
    rec = eng.execute("w1", post_fitness=0.9)
    assert abs(rec.fitness_delta - 0.1) < 0.001


# T207-CMWE-17: negative fitness_delta on regression
def test_17_negative_fitness_delta(eng):
    _reg(eng, fitness=0.9)
    rec = eng.execute("w1", post_fitness=0.7)
    assert rec.fitness_delta < 0


# T207-CMWE-18: CMWE-DETERM-0 — identical inputs → same record_id
def test_18_deterministic_record_id(tmp_path):
    def make_eng(sub):
        return ConstitutionalMutationWindowExecutor(
            ledger_path=tmp_path / sub / "l.jsonl",
            hmac_secret=b"det-secret",
            min_fitness=0.5,
        )
    e1, e2 = make_eng("e1"), make_eng("e2")
    e1.register("wx", "px", 2, ["mod"], 1.0)
    e2.register("wx", "px", 2, ["mod"], 1.0)
    r1 = e1.execute("wx")
    r2 = e2.execute("wx")
    # record_id depends on prev_hmac (both "0"*64) + window_id + outcome
    assert r1.record_id == r2.record_id


# T207-CMWE-19: governor field correct in all records
def test_19_governor_field_correct(eng):
    _reg(eng)
    eng.execute("w1")
    recs = eng.attestation_records()
    assert all(r["governor"] == GOVERNOR for r in recs)


# T207-CMWE-20: innov_code correct
def test_20_innov_code_correct(eng):
    _reg(eng)
    eng.execute("w1")
    recs = eng.attestation_records()
    assert all(r["innov_code"] == INNOV_CODE for r in recs)


# T207-CMWE-21: phase correct
def test_21_phase_correct(eng):
    _reg(eng)
    eng.execute("w1")
    recs = eng.attestation_records()
    assert all(r["phase"] == PHASE for r in recs)


# T207-CMWE-22: multiple windows tracked independently
def test_22_multiple_windows_independent(eng):
    for i in range(3):
        eng.register(f"w{i}", f"prop-{i}", 2, [f"mod_{i}"], 1.0)
        eng.execute(f"w{i}")
    assert len(eng.get_feedback_log()) == 3


# T207-CMWE-23: blast_tier preserved in attestation
def test_23_blast_tier_preserved(eng):
    _reg(eng, blast=1)
    rec = eng.execute("w1")
    assert rec.blast_tier == 1


# T207-CMWE-24: mutation_scope preserved sorted
def test_24_scope_sorted_in_record(eng):
    eng.register("w1", "p1", 2, ["z", "a", "m"], 1.0)
    rec = eng.execute("w1")
    assert rec.mutation_scope == sorted(["z", "a", "m"])


# T207-CMWE-25: ledger reload restores window state
def test_25_ledger_reload_restores(tmp_path):
    ledger = tmp_path / "reload" / "l.jsonl"
    e1 = ConstitutionalMutationWindowExecutor(ledger_path=ledger, hmac_secret=b"r")
    e1.register("wr", "pr", 2, ["mod_r"], 1.0)
    e1.execute("wr")
    e2 = ConstitutionalMutationWindowExecutor(ledger_path=ledger, hmac_secret=b"r")
    w = e2.get_window("wr")
    assert w is not None
    assert w.outcome == ExecutionOutcome.SUCCESS.value


# T207-CMWE-26: feedback_log reloaded from ledger
def test_26_feedback_reloaded(tmp_path):
    ledger = tmp_path / "fbr" / "l.jsonl"
    e1 = ConstitutionalMutationWindowExecutor(ledger_path=ledger, hmac_secret=b"fb")
    e1.register("wf", "pf", 2, ["mod_f"], 1.0)
    e1.execute("wf")
    e2 = ConstitutionalMutationWindowExecutor(ledger_path=ledger, hmac_secret=b"fb")
    assert len(e2.get_feedback_log()) >= 1


# T207-CMWE-27: TIER1 does not require human0
def test_27_tier1_no_human0_needed(eng):
    _reg(eng, blast=1)
    rec = eng.execute("w1", human0_identity=None)
    assert rec.outcome == ExecutionOutcome.SUCCESS.value


# T207-CMWE-28: no-fn execute defaults to SUCCESS
def test_28_no_fn_defaults_success(eng):
    _reg(eng)
    rec = eng.execute("w1", execution_fn=None)
    assert rec.outcome == ExecutionOutcome.SUCCESS.value


# T207-CMWE-29: unknown window_id raises CMWEError
def test_29_unknown_window_raises(eng):
    with pytest.raises(CMWEError):
        eng.execute("nonexistent")


# T207-CMWE-30: full governed lifecycle — register → execute → verify
def test_30_full_lifecycle(eng):
    w = _reg(eng, blast=1, fitness=0.9)
    assert w.stage == WindowStage.PENDING.value
    rec = eng.execute("w1", post_fitness=0.95)
    assert rec.outcome == ExecutionOutcome.SUCCESS.value
    assert rec.fitness_delta > 0
    assert eng.verify_ledger() is True
    fb = eng.get_feedback_log()
    assert fb[0].outcome == ExecutionOutcome.SUCCESS.value
