# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
import json
import pytest

from runtime.innovations30.mutation_calibration_engine import *


def mk(tmp_path):
    return MutationCalibrationEngine(tmp_path / "mutation_calibration.jsonl", tmp_path / "mce_weights.json")

def out(src="test_harness", impact="i1", res=OutcomeClass.APPROVED, phase=163, csi=0.1, inv=0):
    return MutationOutcome(impact, "m1", res, phase, csi, inv, src)

# unit 10
for i in range(1, 31):
    pass

def test_T01_calibration_id_deterministic(tmp_path):
    e1, e2 = mk(tmp_path/"a"), mk(tmp_path/"b")
    assert e1.calibrate(out()).calibration_id == e2.calibrate(out()).calibration_id

def test_T02_weight_sum_invariant(tmp_path):
    e=mk(tmp_path); assert abs(sum(e._load_weights().values())-1.0) < 1e-9

def test_T03_drift_clamp(tmp_path):
    e=mk(tmp_path); d=e._calc_delta(1.0); assert all(abs(v)<=0.05 for v in d.values())

def test_T04_chain_break_abort(tmp_path):
    e=mk(tmp_path); e.calibrate(out()); p=tmp_path/"mutation_calibration.jsonl"; r=json.loads(p.read_text().splitlines()[0]); r["chain_hash"]="0"*64; p.write_text(json.dumps(r)+"\n")
    with pytest.raises(MCEChainError): mk(tmp_path).verify_chain()

def test_T05_valid_sources_reject(tmp_path):
    with pytest.raises(MCESourceError): mk(tmp_path).calibrate(out(src="bad"))

def test_T06_missing_impact(tmp_path):
    with pytest.raises(MCELookupError): mk(tmp_path).calibrate(out(impact=""))

def test_T07_human0_gate(tmp_path, monkeypatch):
    import runtime.innovations30.mutation_calibration_engine as mod
    monkeypatch.setattr(mod, 'HUMAN0_SHIFT_GATE', 0.01)
    e=mk(tmp_path)
    with pytest.raises(MCEHuman0Gate): e.calibrate(out(csi=2.0, inv=5, res=OutcomeClass.REVERTED))

def test_T08_weight_persistence(tmp_path):
    e=mk(tmp_path); e.calibrate(out(csi=0.0)); w1=e._load_weights(); w2=mk(tmp_path)._load_weights(); assert w1==w2

def test_T09_outcome_enum(tmp_path):
    assert OutcomeClass.APPROVED.value == "APPROVED"

def test_T10_prev_digest_link(tmp_path):
    e=mk(tmp_path); a=e.calibrate(out()); b=e.calibrate(out(impact="i2")); assert b.prev_digest==a.chain_hash

# integration/invariant condensed

def test_T11_roundtrip(tmp_path): assert mk(tmp_path).calibrate(out()).impact_id=="i1"
def test_T12_verify_clean(tmp_path): e=mk(tmp_path); e.calibrate(out()); assert e.verify_chain() is True
def test_T13_reload_restart(tmp_path): e=mk(tmp_path); e.calibrate(out()); assert mk(tmp_path).verify_chain() is True
def test_T14_seq_increments(tmp_path): e=mk(tmp_path); assert e.calibrate(out()).ledger_seq==1 and e.calibrate(out(impact='i2')).ledger_seq==2
def test_T15_jsonl_append_only(tmp_path): e=mk(tmp_path); e.calibrate(out()); e.calibrate(out(impact='i2')); assert len((tmp_path/'mutation_calibration.jsonl').read_text().splitlines())==2
def test_T16_error_bounds(tmp_path): r=mk(tmp_path).calibrate(out(csi=0.0)); assert 0<=r.prediction_error<=1
def test_T17_classes_runtimeerror(): assert issubclass(MCEChainError, RuntimeError)
def test_T18_weight_runtimeerror(): assert issubclass(MCEWeightError, RuntimeError)
def test_T19_source_frozenset(): assert isinstance(VALID_SOURCES, frozenset)
def test_T20_constants_present(): assert MAX_DRIFT==0.05 and HUMAN0_SHIFT_GATE==0.10
def test_T21_weight_file_atomic(tmp_path): e=mk(tmp_path); e._save_weights(e._load_weights()); assert (tmp_path/'mce_weights.json').exists()
def test_T22_calibration_id_sha256(tmp_path): c=mk(tmp_path).calibrate(out()).calibration_id; assert len(c)==64
def test_T23_prev_digest_on_first(tmp_path): assert mk(tmp_path).calibrate(out()).prev_digest==CHAIN_ROOT
def test_T24_chain_hash_nonempty(tmp_path): assert len(mk(tmp_path).calibrate(out()).chain_hash)==64
def test_T25_hmac_compare_digest_used(): assert 'hmac.compare_digest' in Path('runtime/innovations30/mutation_calibration_engine.py').read_text()
def test_T26_weight_keys(): assert set(WEIGHT_KEYS)=={'precedent','invariant','csi','forecast'}
def test_T27_bad_weight_keys_raise(tmp_path):
    with pytest.raises(MCEWeightError): mk(tmp_path)._validate_weights({'a':1.0})
def test_T28_bad_weight_sum_raise(tmp_path):
    with pytest.raises(MCEWeightError): mk(tmp_path)._validate_weights({'precedent':0.25,'invariant':0.35,'csi':0.2,'forecast':0.3})
def test_T29_blocked_result_supported(tmp_path): assert mk(tmp_path).calibrate(out(res=OutcomeClass.BLOCKED_POST_GATE)).actual_class=='BLOCKED_POST_GATE'
def test_T30_neutral_result_supported(tmp_path): assert mk(tmp_path).calibrate(out(res=OutcomeClass.NEUTRAL)).actual_class=='NEUTRAL'
