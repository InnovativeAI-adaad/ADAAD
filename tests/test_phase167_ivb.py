# SPDX-License-Identifier: Apache-2.0
"""Phase 167 · INNOV-73 · IVB — Invariant Velocity Benchmark — 30-test suite.

T167-IVB-01..30 — Grade-A · 30/30 target
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dorkllm.invariant_velocity_benchmark import (
    GOVERNOR, IVB_WINDOW_SIZE, V10_MIN_INVARIANTS,
    IVBChainError, IVBHuman0Flag, IVBRegressionError,
    InvariantVelocityBenchmark, VelocitySnapshot, get_benchmark,
)


def _bench(tmp_path: Path, target: int = V10_MIN_INVARIANTS) -> InvariantVelocityBenchmark:
    return InvariantVelocityBenchmark(
        ledger_path=tmp_path / "ivb.jsonl", target=target
    )


# T167-IVB-01
def test_t167_ivb_01_import():
    from dorkllm import invariant_velocity_benchmark  # noqa
    assert invariant_velocity_benchmark.GOVERNOR == "DUSTIN L REID"


# T167-IVB-02
def test_t167_ivb_02_governor():
    assert GOVERNOR == "DUSTIN L REID"


# T167-IVB-03
def test_t167_ivb_03_instantiation(tmp_path):
    b = _bench(tmp_path)
    assert b.history() == []
    assert b.velocity() == 0.0


# T167-IVB-04
def test_t167_ivb_04_first_record_no_delta(tmp_path):
    b = _bench(tmp_path)
    snap = b.record(166, 320)
    assert snap.delta == 0
    assert snap.invariant_count == 320


# T167-IVB-05
def test_t167_ivb_05_delta_computed(tmp_path):
    b = _bench(tmp_path)
    b.record(165, 310)
    snap = b.record(166, 320)
    assert snap.delta == 10


# T167-IVB-06
def test_t167_ivb_06_regression_raises(tmp_path):
    b = _bench(tmp_path)
    b.record(165, 320)
    with pytest.raises(IVBRegressionError):
        b.record(166, 310)


# T167-IVB-07
def test_t167_ivb_07_snapshot_is_frozen(tmp_path):
    b = _bench(tmp_path)
    snap = b.record(165, 310)
    with pytest.raises(Exception):
        snap.invariant_count = 999  # type: ignore


# T167-IVB-08
def test_t167_ivb_08_history_grows(tmp_path):
    b = _bench(tmp_path)
    b.record(165, 310)
    b.record(166, 320)
    assert len(b.history()) == 2


# T167-IVB-09
def test_t167_ivb_09_velocity_nonzero(tmp_path):
    b = _bench(tmp_path)
    b.record(165, 310)
    b.record(166, 320)
    assert b.velocity() > 0


# T167-IVB-10
def test_t167_ivb_10_velocity_zero_on_empty(tmp_path):
    b = _bench(tmp_path)
    assert b.velocity() == 0.0


# T167-IVB-11
def test_t167_ivb_11_forecast_returns_int_or_none(tmp_path):
    b = _bench(tmp_path)
    b.record(165, 310)
    b.record(166, 320)
    result = b.forecast(320)
    assert isinstance(result, int) or result is None


# T167-IVB-12
def test_t167_ivb_12_forecast_zero_when_target_met(tmp_path):
    b = _bench(tmp_path, target=300)
    b.record(165, 300)
    assert b.forecast(300) == 0


# T167-IVB-13
def test_t167_ivb_13_chain_root_on_first(tmp_path):
    b = _bench(tmp_path)
    snap = b.record(165, 310)
    assert snap.prev_digest == "0" * 64


# T167-IVB-14
def test_t167_ivb_14_chain_links(tmp_path):
    b = _bench(tmp_path)
    s1 = b.record(165, 310)
    s2 = b.record(166, 320)
    assert s2.prev_digest == s1.chain_digest


# T167-IVB-15
def test_t167_ivb_15_verify_chain_valid(tmp_path):
    b = _bench(tmp_path)
    b.record(165, 310)
    b.record(166, 320)
    assert b.verify_chain() is True


# T167-IVB-16
def test_t167_ivb_16_verify_chain_tampered(tmp_path):
    b = _bench(tmp_path)
    b.record(165, 310)
    ledger = tmp_path / "ivb.jsonl"
    # Tamper with snapshot_id which is part of the chain digest computation
    content = ledger.read_text()
    obj = json.loads(content.strip())
    obj["snapshot_id"] = "IVB-tampered000"
    ledger.write_text(json.dumps(obj) + "\n")
    with pytest.raises(IVBChainError):
        b.verify_chain()


# T167-IVB-17: two records with positive velocity, far from target → Human0Flag
def test_t167_ivb_17_human0_flag_far_from_target(tmp_path):
    b = _bench(tmp_path, target=500)
    b.record(100, 10)   # first: delta=0, no flag
    with pytest.raises(IVBHuman0Flag):
        b.record(101, 20)  # delta=10, vel=10, remaining=480, forecast=49 > 10


# T167-IVB-18
def test_t167_ivb_18_human0_not_raised_near_target(tmp_path):
    b = _bench(tmp_path, target=325)
    b.record(165, 310)
    # 15 remaining, velocity=0 on first → delta=0; second call with delta=10
    snap = b.record(166, 320)
    assert snap.target_reachable is True


# T167-IVB-19
def test_t167_ivb_19_ledger_valid_jsonl(tmp_path):
    b = _bench(tmp_path)
    b.record(165, 310)
    ledger = tmp_path / "ivb.jsonl"
    for line in ledger.read_text().strip().splitlines():
        obj = json.loads(line)
        assert "snapshot_id" in obj and "chain_digest" in obj


# T167-IVB-20
def test_t167_ivb_20_governor_in_snapshot(tmp_path):
    b = _bench(tmp_path)
    snap = b.record(165, 310)
    assert snap.governor == "DUSTIN L REID"


# T167-IVB-21
def test_t167_ivb_21_deterministic_snap_id(tmp_path):
    b1 = _bench(tmp_path / "a")
    b2 = _bench(tmp_path / "b")
    s1 = b1.record(165, 310)
    s2 = b2.record(165, 310)
    assert s1.snapshot_id == s2.snapshot_id


# T167-IVB-22
def test_t167_ivb_22_window_size_constant():
    assert IVB_WINDOW_SIZE == 5


# T167-IVB-23
def test_t167_ivb_23_rolling_velocity_type(tmp_path):
    b = _bench(tmp_path)
    b.record(165, 310)
    snap = b.record(166, 320)
    assert isinstance(snap.rolling_velocity, float)


# T167-IVB-24
def test_t167_ivb_24_target_reachable_true_when_velocity_positive(tmp_path):
    b = _bench(tmp_path)
    b.record(165, 310)
    snap = b.record(166, 320)
    assert snap.target_reachable is True


# T167-IVB-25
def test_t167_ivb_25_forecast_none_on_zero_velocity(tmp_path):
    b = _bench(tmp_path)
    result = b.forecast(310)
    assert result is None


# T167-IVB-26
def test_t167_ivb_26_ledger_created_on_record(tmp_path):
    ledger = tmp_path / "ivb.jsonl"
    b = InvariantVelocityBenchmark(ledger_path=ledger, target=350)
    assert not ledger.exists()
    b.record(165, 310)
    assert ledger.exists()


# T167-IVB-27
def test_t167_ivb_27_multiple_records_history_ordered(tmp_path):
    b = _bench(tmp_path, target=300)  # target already near counts → no Human0Flag
    b.record(163, 290)
    b.record(164, 295)
    b.record(165, 300)
    h = b.history()
    assert [r["phase"] for r in h] == [163, 164, 165]


# T167-IVB-28
def test_t167_ivb_28_get_benchmark_singleton():
    b1 = get_benchmark()
    b2 = get_benchmark()
    assert b1 is b2


# T167-IVB-29
def test_t167_ivb_29_same_count_twice_allowed(tmp_path):
    b = _bench(tmp_path)
    b.record(165, 310)
    snap = b.record(166, 310)
    assert snap.delta == 0


# T167-IVB-30
def test_t167_ivb_30_full_lifecycle(tmp_path):
    b = _bench(tmp_path, target=350)
    b.record(163, 300)
    b.record(164, 310)
    b.record(165, 320)
    assert b.verify_chain() is True
    assert b.velocity() > 0
    f = b.forecast(320)
    assert isinstance(f, int)
    assert len(b.history()) == 3
