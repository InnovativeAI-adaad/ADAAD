# SPDX-License-Identifier: Apache-2.0
"""Phase 152 / INNOV-58 — Constitutional Pressure Index (CPI) — acceptance suite.

30 tests · 100 % pass required before merge.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

os.environ.setdefault("ADAAD_CPI_HMAC_KEY", "test-cpi-key-phase152")


def _make_ledger_path(tmp_path: Path) -> Path:
    return tmp_path / "cpi_test_ledger.jsonl"


def _scorer(tmp_path: Path, **kwargs):
    from dorkllm.constitutional_pressure import CPIConfig, CPIScorer
    cfg = CPIConfig(**kwargs) if kwargs else CPIConfig()
    return CPIScorer(config=cfg, ledger_path=_make_ledger_path(tmp_path))


def _mutation_record(rtype: str = "MUTATION", entry_id: str = "e001") -> Dict[str, Any]:
    return {"id": entry_id, "type": rtype}


def _violation_record(ns: str = "SEC", entry_id: str = "v001") -> Dict[str, Any]:
    return {"id": entry_id, "type": "VIOLATION", "namespace": ns}


def _load_ledger(tmp_path: Path) -> List[Dict[str, Any]]:
    p = tmp_path / "cpi_test_ledger.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# T01 – T05: Registry metadata
# ---------------------------------------------------------------------------


def test_t01_registry_innov_id():
    from runtime.innovations30.constitutional_pressure import INNOV_ID
    assert INNOV_ID == "INNOV-58"


def test_t02_registry_phase():
    from runtime.innovations30.constitutional_pressure import INNOV_PHASE
    assert INNOV_PHASE == 152


def test_t03_registry_invariants_count():
    from runtime.innovations30.constitutional_pressure import HARD_CLASS_INVARIANTS
    assert len(HARD_CLASS_INVARIANTS) == 5


def test_t04_registry_invariant_ids():
    from runtime.innovations30.constitutional_pressure import HARD_CLASS_INVARIANTS
    expected = {"CPI-DETERM-0", "CPI-LEDGER-0", "CPI-ALERT-0", "CPI-SCOPE-0", "CPI-HUMAN0-0"}
    assert set(HARD_CLASS_INVARIANTS) == expected


def test_t05_registry_metadata_keys():
    from runtime.innovations30.constitutional_pressure import get_metadata
    meta = get_metadata()
    for key in ("innov_id", "name", "phase", "version", "hard_class_invariants", "description", "module"):
        assert key in meta


# ---------------------------------------------------------------------------
# T06 – T08: CPIScorer instantiation
# ---------------------------------------------------------------------------


def test_t06_scorer_instantiates(tmp_path):
    from dorkllm.constitutional_pressure import CPIScorer
    scorer = CPIScorer(ledger_path=_make_ledger_path(tmp_path))
    assert scorer is not None


def test_t07_scorer_default_threshold(tmp_path):
    from dorkllm.constitutional_pressure import CPIScorer, DEFAULT_ALERT_THRESHOLD
    scorer = CPIScorer(ledger_path=_make_ledger_path(tmp_path))
    assert scorer._config.alert_threshold == DEFAULT_ALERT_THRESHOLD


def test_t08_scorer_custom_threshold(tmp_path):
    from dorkllm.constitutional_pressure import CPIConfig, CPIScorer
    scorer = CPIScorer(config=CPIConfig(alert_threshold=0.5), ledger_path=_make_ledger_path(tmp_path))
    assert scorer._config.alert_threshold == 0.5


# ---------------------------------------------------------------------------
# T09 – T11: CPI-LEDGER-0 — snapshot written before return
# ---------------------------------------------------------------------------


def test_t09_ledger_snapshot_written_on_score(tmp_path):
    scorer = _scorer(tmp_path)
    records = [_mutation_record()]
    scorer.score(records)
    entries = _load_ledger(tmp_path)
    assert any(e["type"] == "PRESSURE_SNAPSHOT" for e in entries)


def test_t10_ledger_entry_has_hmac(tmp_path):
    scorer = _scorer(tmp_path)
    scorer.score([_mutation_record()])
    entries = _load_ledger(tmp_path)
    snapshots = [e for e in entries if e["type"] == "PRESSURE_SNAPSHOT"]
    assert snapshots[0].get("hmac")


def test_t11_ledger_entry_id_returned_in_snapshot(tmp_path):
    scorer = _scorer(tmp_path)
    snap = scorer.score([_mutation_record()])
    entries = _load_ledger(tmp_path)
    ids = {e["id"] for e in entries}
    assert snap.ledger_entry_id in ids


# ---------------------------------------------------------------------------
# T12 – T14: CPI-ALERT-0 — alert emitted at threshold
# ---------------------------------------------------------------------------


def test_t12_alert_emitted_when_threshold_met(tmp_path):
    from dorkllm.constitutional_pressure import CPIConfig, CPIScorer
    # 1 violation out of 1 record → rate=1.0 → above 0.70
    scorer = CPIScorer(config=CPIConfig(alert_threshold=0.70), ledger_path=_make_ledger_path(tmp_path))
    scorer.score([_violation_record()])
    entries = _load_ledger(tmp_path)
    assert any(e["type"] == "PRESSURE_ALERT" for e in entries)


def test_t13_alert_not_emitted_below_threshold(tmp_path):
    from dorkllm.constitutional_pressure import CPIConfig, CPIScorer
    # 1 violation out of 100 records → rate=0.01 → below 0.70
    records = [_violation_record()] + [_mutation_record("ACCEPT", f"a{i}") for i in range(99)]
    scorer = CPIScorer(config=CPIConfig(alert_threshold=0.70), ledger_path=_make_ledger_path(tmp_path))
    scorer.score(records)
    entries = _load_ledger(tmp_path)
    assert not any(e["type"] == "PRESSURE_ALERT" for e in entries)


def test_t14_alert_domain_in_snapshot(tmp_path):
    scorer = _scorer(tmp_path)
    snap = scorer.score([_violation_record()])
    # SECURITY domain gets the violation; with 1/1 records score=1.0 > 0.70
    assert len(snap.alert_domains) > 0


# ---------------------------------------------------------------------------
# T15 – T17: CPI-DETERM-0 — determinism
# ---------------------------------------------------------------------------


def test_t15_identical_inputs_identical_scores(tmp_path):
    records = [_violation_record("SEC", f"v{i}") for i in range(5)] + \
              [_mutation_record("MUTATION", f"m{i}") for i in range(10)]
    s1 = _scorer(tmp_path / "a")
    s2 = _scorer(tmp_path / "b")
    snap1 = s1.score(records)
    snap2 = s2.score(records)
    for domain in snap1.scores:
        assert snap1.scores[domain].score == snap2.scores[domain].score


def test_t16_different_inputs_different_scores(tmp_path):
    s1 = _scorer(tmp_path / "a")
    s2 = _scorer(tmp_path / "b")
    snap1 = s1.score([_violation_record()])
    snap2 = s2.score([_mutation_record("ACCEPT")])
    scores1 = {k: v.score for k, v in snap1.scores.items()}
    scores2 = {k: v.score for k, v in snap2.scores.items()}
    assert scores1 != scores2


def test_t17_score_excludes_timestamps(tmp_path):
    """Scoring formula must be invariant to the time the scorer is created."""
    import time as _time
    records = [_violation_record("SEC", f"v{i}") for i in range(3)]
    s1 = _scorer(tmp_path / "a")
    snap1 = s1.score(records)
    _time.sleep(0.01)
    s2 = _scorer(tmp_path / "b")
    snap2 = s2.score(records)
    assert snap1.scores["SECURITY"].score == snap2.scores["SECURITY"].score


# ---------------------------------------------------------------------------
# T18 – T20: CPI-SCOPE-0 — only ingestible record types consumed
# ---------------------------------------------------------------------------


def test_t18_scope_filters_unknown_types(tmp_path):
    records = [
        {"id": "u1", "type": "UNKNOWN_ALIEN_EVENT"},
        {"id": "u2", "type": "INTERNAL_PROCESS_STATE"},
    ]
    scorer = _scorer(tmp_path)
    snap = scorer.score(records)
    # Unknown types filtered out → record_count = 0
    assert snap.record_count == 0


def test_t19_scope_accepts_known_types(tmp_path):
    records = [
        {"id": "r1", "type": "MUTATION"},
        {"id": "r2", "type": "VIOLATION"},
        {"id": "r3", "type": "ACCEPT"},
    ]
    scorer = _scorer(tmp_path)
    snap = scorer.score(records)
    assert snap.record_count == 3


def test_t20_scope_mixed_records_only_known_counted(tmp_path):
    records = [
        {"id": "r1", "type": "MUTATION"},
        {"id": "bad", "type": "ALIEN"},
        {"id": "r2", "type": "REJECT"},
    ]
    scorer = _scorer(tmp_path)
    snap = scorer.score(records)
    assert snap.record_count == 2


# ---------------------------------------------------------------------------
# T21 – T23: CPI-HUMAN0-0 — config change auth
# ---------------------------------------------------------------------------


def test_t21_update_config_requires_operator(tmp_path):
    from dorkllm.constitutional_pressure import CPIAuthError
    scorer = _scorer(tmp_path)
    with pytest.raises(CPIAuthError):
        scorer.update_config(operator="")


def test_t22_update_config_none_operator_raises(tmp_path):
    from dorkllm.constitutional_pressure import CPIAuthError
    scorer = _scorer(tmp_path)
    with pytest.raises(CPIAuthError):
        scorer.update_config(operator=None)


def test_t23_update_config_valid_operator_succeeds(tmp_path):
    scorer = _scorer(tmp_path)
    scorer.update_config(operator="HUMAN-0 Dustin L. Reid", alert_threshold=0.5)
    assert scorer._config.alert_threshold == 0.5


# ---------------------------------------------------------------------------
# T24 – T26: Domain classification
# ---------------------------------------------------------------------------


def test_t24_gcb_trip_scores_security_and_mutation(tmp_path):
    records = [{"id": "g1", "type": "GCB_TRIP"}]
    scorer = _scorer(tmp_path)
    snap = scorer.score(records)
    assert snap.scores["SECURITY"].violation_count >= 1
    assert snap.scores["MUTATION"].violation_count >= 1


def test_t25_rollback_scores_mutation_and_replay(tmp_path):
    records = [{"id": "rb1", "type": "ROLLBACK_EVENT"}]
    scorer = _scorer(tmp_path)
    snap = scorer.score(records)
    assert snap.scores["MUTATION"].violation_count >= 1
    assert snap.scores["REPLAY"].violation_count >= 1


def test_t26_human0_keyword_in_namespace_scores_human0_domain(tmp_path):
    records = [{"id": "h1", "type": "VIOLATION", "namespace": "GRB-HUMAN0-0"}]
    scorer = _scorer(tmp_path)
    snap = scorer.score(records)
    assert snap.scores["HUMAN0"].violation_count >= 1


# ---------------------------------------------------------------------------
# T27: Window config
# ---------------------------------------------------------------------------


def test_t27_window_limits_records_consumed(tmp_path):
    from dorkllm.constitutional_pressure import CPIConfig, CPIScorer
    records = [_violation_record("SEC", f"v{i}") for i in range(20)]
    scorer = CPIScorer(config=CPIConfig(window=5), ledger_path=_make_ledger_path(tmp_path))
    snap = scorer.score(records)
    assert snap.record_count == 5


# ---------------------------------------------------------------------------
# T28: CPISnapshot structure
# ---------------------------------------------------------------------------


def test_t28_snapshot_has_all_domains(tmp_path):
    from dorkllm.constitutional_pressure import ALL_DOMAINS
    scorer = _scorer(tmp_path)
    snap = scorer.score([])
    for domain in ALL_DOMAINS:
        assert domain.value in snap.scores


# ---------------------------------------------------------------------------
# T29: summarise output
# ---------------------------------------------------------------------------


def test_t29_summarise_allclear(tmp_path):
    scorer = _scorer(tmp_path)
    # Empty records → all scores 0 → no alert
    snap = scorer.score([])
    summary = scorer.summarise(snap)
    assert "CPI:" in summary
    assert "threshold" in summary


def test_t30_summarise_alert_contains_domain(tmp_path):
    scorer = _scorer(tmp_path)
    snap = scorer.score([_violation_record()])
    summary = scorer.summarise(snap)
    if snap.alert_domains:
        assert "ALERT" in summary
    else:
        assert "CPI:" in summary
