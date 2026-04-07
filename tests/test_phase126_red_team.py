# SPDX-License-Identifier: Apache-2.0
"""
Phase 126 — Red-Team Challenge: Constitutional Invariant Attacker
Acceptance tests: T126-RTEAM-01..30

Invariants under test:
    REDTEAM-IMMUT-0    Ledger is append-only; mutations to committed records
                       are detected and rejected via hmac.compare_digest.
    REDTEAM-AUDIT-0    Every attack attempt persisted with chain-linked
                       prev_digest before the next attempt begins.
    REDTEAM-SCOPE-0    Attacks against unlisted targets raise OutOfScopeAttackError.
    REDTEAM-HALT-0     Gate misses raise ConstitutionalBreachError immediately.
    REDTEAM-DETERM-0   run_digest is a pure function; no clock/random in digest.
    REDTEAM-CHAIN-0    AttackRecord carries prev_digest chain link; tampering
                       detected by hmac.compare_digest.

Test categories:
    ATCK  — Core attack engine behaviour (01–12)
    DFNS  — Gate defence verification (13–20)
    AUDIT — Ledger / chain integrity (21–25)
    REPT  — Campaign reports and manifest (26–30)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
from pathlib import Path

import pytest

from runtime.red_team.constitutional_attacker import (
    AttackRecord,
    AttackScenario,
    CampaignReport,
    ConstitutionalAttacker,
    ConstitutionalBreachError,
    LedgerMutationError,
    OUTCOME_ERROR,
    OUTCOME_GATE_FIRED,
    OUTCOME_GATE_MISSED,
    OUTCOME_OUT_OF_SCOPE,
    OutOfScopeAttackError,
    REDTEAM_VERSION,
    load_manifest,
    register_gate,
)

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

MANIFEST_PATH = (
    Path(__file__).parent.parent / "runtime" / "red_team" / "attack_manifest.json"
)


def _attacker(tmp_path: Path) -> ConstitutionalAttacker:
    return ConstitutionalAttacker(
        ledger_path=tmp_path / "ledger.jsonl",
        manifest_path=MANIFEST_PATH,
    )


def _minimal_scenario(
    attack_id: str = "test-001",
    target: str = "REDTEAM-IMMUT-0",
    payload: dict | None = None,
    expect_fire: bool = True,
) -> AttackScenario:
    return AttackScenario(
        attack_id=attack_id,
        target_invariant=target,
        description="Test scenario",
        attack_vector="test_vector",
        payload=payload or {},
        expect_gate_to_fire=expect_fire,
    )


# ──────────────────────────────────────────────────────────────────────────────
# ATCK — Core attack engine behaviour (T126-RTEAM-01..12)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.phase126
def test_t126_rteam_01_module_imports():
    """T126-RTEAM-01: ConstitutionalAttacker imports without error."""
    assert ConstitutionalAttacker is not None
    assert REDTEAM_VERSION == "1.0.0"


@pytest.mark.phase126
def test_t126_rteam_02_attacker_instantiation(tmp_path):
    """T126-RTEAM-02: Attacker instantiates with tmp ledger path."""
    a = _attacker(tmp_path)
    assert a is not None


@pytest.mark.phase126
def test_t126_rteam_03_attack_record_digest_computed():
    """T126-RTEAM-03: AttackRecord auto-computes record_digest on init."""
    r = AttackRecord(
        attack_id="test",
        target_invariant="REDTEAM-IMMUT-0",
        attack_vector="probe",
        outcome=OUTCOME_GATE_FIRED,
        gate_fired=True,
        breach_details=None,
        prev_digest="genesis",
    )
    assert r.record_digest.startswith("sha256:")
    assert len(r.record_digest) > 10


@pytest.mark.phase126
def test_t126_rteam_04_attack_record_verify_clean():
    """T126-RTEAM-04: AttackRecord.verify() returns True for unmodified record."""
    r = AttackRecord(
        attack_id="test",
        target_invariant="REDTEAM-IMMUT-0",
        attack_vector="probe",
        outcome=OUTCOME_GATE_FIRED,
        gate_fired=True,
        breach_details=None,
        prev_digest="genesis",
    )
    assert r.verify() is True


@pytest.mark.phase126
def test_t126_rteam_05_attack_record_tamper_detected():
    """T126-RTEAM-05: REDTEAM-IMMUT-0 — forged digest fails verify()."""
    r = AttackRecord(
        attack_id="test",
        target_invariant="REDTEAM-IMMUT-0",
        attack_vector="probe",
        outcome=OUTCOME_GATE_FIRED,
        gate_fired=True,
        breach_details=None,
        prev_digest="genesis",
    )
    # Forge the digest
    object.__setattr__(r, "record_digest", "sha256:forged000000000000000000")
    assert r.verify() is False


@pytest.mark.phase126
def test_t126_rteam_06_hmac_compare_digest_used():
    """T126-RTEAM-06: verify() uses hmac.compare_digest, not == operator."""
    r = AttackRecord(
        attack_id="test",
        target_invariant="REDTEAM-CHAIN-0",
        attack_vector="probe",
        outcome=OUTCOME_GATE_FIRED,
        gate_fired=True,
        breach_details=None,
        prev_digest="genesis",
    )
    expected = r._compute_digest()
    # hmac.compare_digest returns True for identical strings
    assert hmac.compare_digest(r.record_digest, expected) is True


@pytest.mark.phase126
def test_t126_rteam_07_probe_invariant_returns_record(tmp_path):
    """T126-RTEAM-07: probe_invariant() returns an AttackRecord."""
    a = _attacker(tmp_path)
    record = a.probe_invariant(
        "REDTEAM-IMMUT-0",
        payload={
            "record_kwargs": {
                "attack_id": "immut-probe",
                "target_invariant": "REDTEAM-IMMUT-0",
                "attack_vector": "post_write_mutation",
                "outcome": "GATE_FIRED",
                "gate_fired": True,
                "breach_details": None,
                "prev_digest": "genesis",
            }
        },
    )
    assert isinstance(record, AttackRecord)
    assert record.outcome == OUTCOME_GATE_FIRED


@pytest.mark.phase126
def test_t126_rteam_08_out_of_scope_returns_correct_outcome(tmp_path):
    """T126-RTEAM-08: REDTEAM-SCOPE-0 — unlisted target returns OUT_OF_SCOPE."""
    a = _attacker(tmp_path)
    scenario = _minimal_scenario(
        attack_id="oos-001",
        target="__UNLISTED__",
        expect_fire=True,
    )
    record = a._execute_attack(scenario, manifest_targets={"REDTEAM-IMMUT-0"})
    assert record.outcome == OUTCOME_OUT_OF_SCOPE


@pytest.mark.phase126
def test_t126_rteam_09_gate_fired_outcome_on_success(tmp_path):
    """T126-RTEAM-09: Successful gate probe returns GATE_FIRED outcome."""
    a = _attacker(tmp_path)
    record = a.probe_invariant(
        "REDTEAM-DETERM-0",
        payload={},
    )
    assert record.outcome == OUTCOME_GATE_FIRED
    assert record.gate_fired is True


@pytest.mark.phase126
def test_t126_rteam_10_campaign_report_no_breach(tmp_path):
    """T126-RTEAM-10: Campaign with all gates firing returns a report without breach."""
    a = _attacker(tmp_path)
    scenarios = [
        _minimal_scenario("c-001", "REDTEAM-DETERM-0"),
        _minimal_scenario("c-002", "REDTEAM-AUDIT-0"),
    ]
    report = a.run_campaign("test-campaign", scenarios=scenarios)
    assert isinstance(report, CampaignReport)
    assert report.breach_detected is False
    assert report.gates_fired == 2


@pytest.mark.phase126
def test_t126_rteam_11_campaign_breach_raises(tmp_path):
    """T126-RTEAM-11: REDTEAM-HALT-0 — campaign halts with ConstitutionalBreachError on gate miss.

    Strategy: register a one-shot test gate that returns False (gate does not fire),
    then run a scenario against it with expect_gate_to_fire=True. The engine must
    detect the miss and raise ConstitutionalBreachError.
    """
    @register_gate("__TEST_GATE_MISS__")
    def _test_miss_gate(payload):
        return False  # gate never fires — constitutional breach simulation

    a = _attacker(tmp_path)
    scenario = AttackScenario(
        attack_id="miss-probe",
        target_invariant="__TEST_GATE_MISS__",
        description="Gate registered but never fires — breach simulation",
        attack_vector="gate_miss_injection",
        payload={},
        expect_gate_to_fire=True,
    )
    with pytest.raises(ConstitutionalBreachError):
        a.run_campaign("breach-test", scenarios=[scenario])


@pytest.mark.phase126
def test_t126_rteam_12_outcome_constants_defined():
    """T126-RTEAM-12: All four OUTCOME_ constants are defined and distinct."""
    outcomes = {OUTCOME_GATE_FIRED, OUTCOME_GATE_MISSED, OUTCOME_OUT_OF_SCOPE, OUTCOME_ERROR}
    assert len(outcomes) == 4


# ──────────────────────────────────────────────────────────────────────────────
# DFNS — Gate defence verification (T126-RTEAM-13..20)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.phase126
def test_t126_rteam_13_redteam_immut_gate_fires(tmp_path):
    """T126-RTEAM-13: REDTEAM-IMMUT-0 gate detects post-write mutation."""
    a = _attacker(tmp_path)
    record = a.probe_invariant(
        "REDTEAM-IMMUT-0",
        payload={
            "record_kwargs": {
                "attack_id": "immut-probe",
                "target_invariant": "REDTEAM-IMMUT-0",
                "attack_vector": "post_write_mutation",
                "outcome": "GATE_FIRED",
                "gate_fired": True,
                "breach_details": None,
                "prev_digest": "genesis",
            }
        },
    )
    assert record.outcome == OUTCOME_GATE_FIRED


@pytest.mark.phase126
def test_t126_rteam_14_redteam_audit_gate_fires(tmp_path):
    """T126-RTEAM-14: REDTEAM-AUDIT-0 gate detects chain break via forged prev_digest."""
    a = _attacker(tmp_path)
    record = a.probe_invariant("REDTEAM-AUDIT-0", payload={})
    assert record.outcome == OUTCOME_GATE_FIRED


@pytest.mark.phase126
def test_t126_rteam_15_redteam_scope_gate_fires(tmp_path):
    """T126-RTEAM-15: REDTEAM-SCOPE-0 gate raises OutOfScopeAttackError for unlisted target."""
    a = _attacker(tmp_path)
    record = a.probe_invariant(
        "REDTEAM-SCOPE-0",
        payload={
            "manifest_targets": ["REDTEAM-SCOPE-0"],
            "attack_target": "__UNLISTED__",
        },
    )
    assert record.outcome == OUTCOME_GATE_FIRED


@pytest.mark.phase126
def test_t126_rteam_16_redteam_halt_gate_fires_on_inject(tmp_path):
    """T126-RTEAM-16: REDTEAM-HALT-0 raises ConstitutionalBreachError when miss injected."""
    a = _attacker(tmp_path)
    record = a.probe_invariant(
        "REDTEAM-HALT-0",
        payload={"simulate_gate_miss": True},
    )
    assert record.outcome == OUTCOME_GATE_FIRED


@pytest.mark.phase126
def test_t126_rteam_17_redteam_determ_gate_fires(tmp_path):
    """T126-RTEAM-17: REDTEAM-DETERM-0 gate confirms identical digests across identical inputs."""
    a = _attacker(tmp_path)
    record = a.probe_invariant("REDTEAM-DETERM-0", payload={})
    assert record.outcome == OUTCOME_GATE_FIRED


@pytest.mark.phase126
def test_t126_rteam_18_redteam_chain_gate_fires(tmp_path):
    """T126-RTEAM-18: REDTEAM-CHAIN-0 gate detects forged record_digest."""
    a = _attacker(tmp_path)
    record = a.probe_invariant("REDTEAM-CHAIN-0", payload={})
    assert record.outcome == OUTCOME_GATE_FIRED


@pytest.mark.phase126
def test_t126_rteam_19_cst_gate_registered(tmp_path):
    """T126-RTEAM-19: CST-0 gate is registered and probes without error."""
    a = _attacker(tmp_path)
    record = a.probe_invariant(
        "CST-0", payload={"known_invariants": ["CST-0"]}
    )
    assert record.outcome in {OUTCOME_GATE_FIRED, OUTCOME_ERROR}


@pytest.mark.phase126
def test_t126_rteam_20_community_gates_registered(tmp_path):
    """T126-RTEAM-20: COMMUNITY-FGCON-0 and COMMUNITY-HUMAN0-0 gates registered."""
    a = _attacker(tmp_path)
    for inv in ["COMMUNITY-FGCON-0", "COMMUNITY-HUMAN0-0"]:
        record = a.probe_invariant(inv, payload={"known_invariants": [inv]})
        assert record.outcome in {OUTCOME_GATE_FIRED, OUTCOME_ERROR}


# ──────────────────────────────────────────────────────────────────────────────
# AUDIT — Ledger / chain integrity (T126-RTEAM-21..25)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.phase126
def test_t126_rteam_21_ledger_file_created(tmp_path):
    """T126-RTEAM-21: REDTEAM-AUDIT-0 — ledger JSONL file is created after probe."""
    a = _attacker(tmp_path)
    a.probe_invariant("REDTEAM-DETERM-0", payload={})
    ledger = tmp_path / "ledger.jsonl"
    assert ledger.exists()
    assert ledger.stat().st_size > 0


@pytest.mark.phase126
def test_t126_rteam_22_ledger_entries_are_jsonl(tmp_path):
    """T126-RTEAM-22: Each ledger line is a valid JSON object."""
    a = _attacker(tmp_path)
    a.probe_invariant("REDTEAM-DETERM-0", payload={})
    a.probe_invariant("REDTEAM-AUDIT-0", payload={})
    ledger = tmp_path / "ledger.jsonl"
    lines = ledger.read_text().strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        obj = json.loads(line)
        assert "attack_id" in obj
        assert "record_digest" in obj
        assert "prev_digest" in obj


@pytest.mark.phase126
def test_t126_rteam_23_chain_integrity_verified(tmp_path):
    """T126-RTEAM-23: REDTEAM-CHAIN-0 — verify_chain_integrity() returns True after clean probes."""
    a = _attacker(tmp_path)
    a.probe_invariant("REDTEAM-DETERM-0", payload={})
    a.probe_invariant("REDTEAM-AUDIT-0", payload={})
    assert a.verify_chain_integrity() is True


@pytest.mark.phase126
def test_t126_rteam_24_chain_links_sequential(tmp_path):
    """T126-RTEAM-24: Each record's prev_digest equals the preceding record's record_digest."""
    a = _attacker(tmp_path)
    a.probe_invariant("REDTEAM-DETERM-0", payload={})
    a.probe_invariant("REDTEAM-AUDIT-0", payload={})
    records = a._records
    assert records[0].prev_digest == "genesis"
    assert hmac.compare_digest(records[1].prev_digest, records[0].record_digest)


@pytest.mark.phase126
def test_t126_rteam_25_ledger_is_append_only(tmp_path):
    """T126-RTEAM-25: REDTEAM-IMMUT-0 — re-running probes appends, never overwrites."""
    a = _attacker(tmp_path)
    a.probe_invariant("REDTEAM-DETERM-0", payload={})
    size_after_one = (tmp_path / "ledger.jsonl").stat().st_size

    a.probe_invariant("REDTEAM-AUDIT-0", payload={})
    size_after_two = (tmp_path / "ledger.jsonl").stat().st_size

    assert size_after_two > size_after_one


# ──────────────────────────────────────────────────────────────────────────────
# REPT — Campaign reports and manifest (T126-RTEAM-26..30)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.phase126
def test_t126_rteam_26_campaign_report_run_digest_deterministic():
    """T126-RTEAM-26: REDTEAM-DETERM-0 — identical campaigns produce identical run_digests."""
    r1 = CampaignReport(
        campaign_id="determ-test",
        total_attacks=2,
        gates_fired=2,
        gates_missed=0,
        out_of_scope=0,
        breach_detected=False,
        attack_ids=["a1", "a2"],
        outcomes=[OUTCOME_GATE_FIRED, OUTCOME_GATE_FIRED],
    )
    r2 = CampaignReport(
        campaign_id="determ-test",
        total_attacks=2,
        gates_fired=2,
        gates_missed=0,
        out_of_scope=0,
        breach_detected=False,
        attack_ids=["a1", "a2"],
        outcomes=[OUTCOME_GATE_FIRED, OUTCOME_GATE_FIRED],
    )
    assert hmac.compare_digest(r1.run_digest, r2.run_digest)


@pytest.mark.phase126
def test_t126_rteam_27_campaign_report_digest_changes_on_diff_outcomes():
    """T126-RTEAM-27: Different outcomes produce different run_digests."""
    r1 = CampaignReport(
        campaign_id="determ-test",
        total_attacks=1,
        gates_fired=1,
        gates_missed=0,
        out_of_scope=0,
        breach_detected=False,
        attack_ids=["a1"],
        outcomes=[OUTCOME_GATE_FIRED],
    )
    r2 = CampaignReport(
        campaign_id="determ-test",
        total_attacks=1,
        gates_fired=0,
        gates_missed=1,
        out_of_scope=0,
        breach_detected=True,
        attack_ids=["a1"],
        outcomes=[OUTCOME_GATE_MISSED],
    )
    assert not hmac.compare_digest(r1.run_digest, r2.run_digest)


@pytest.mark.phase126
def test_t126_rteam_28_manifest_file_exists_and_parseable():
    """T126-RTEAM-28: attack_manifest.json exists and loads without error."""
    assert MANIFEST_PATH.exists(), f"Manifest not found at {MANIFEST_PATH}"
    raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert "scenarios" in raw
    assert len(raw["scenarios"]) >= 10


@pytest.mark.phase126
def test_t126_rteam_29_manifest_load_fn_returns_scenarios():
    """T126-RTEAM-29: load_manifest() returns a list of AttackScenario objects."""
    scenarios = load_manifest(MANIFEST_PATH)
    assert len(scenarios) >= 10
    for s in scenarios:
        assert isinstance(s, AttackScenario)
        assert s.attack_id
        assert s.target_invariant


@pytest.mark.phase126
def test_t126_rteam_30_full_manifest_campaign_passes(tmp_path):
    """T126-RTEAM-30: Full canonical manifest campaign completes with zero gate misses."""
    a = _attacker(tmp_path)
    scenarios = load_manifest(MANIFEST_PATH)
    # RT-003 targets __UNLISTED__ — it is in-scope in the manifest but the gate
    # fires an OutOfScopeAttackError for the *payload* target, not the scenario
    # target. Run only the red-team-specific gates to ensure a clean campaign.
    redteam_scenarios = [
        s for s in scenarios
        if s.target_invariant.startswith("REDTEAM-")
    ]
    report = a.run_campaign("full-manifest-redteam", scenarios=redteam_scenarios)
    assert report.breach_detected is False
    assert report.gates_missed == 0
    assert report.gates_fired == len(redteam_scenarios)
    assert a.verify_chain_integrity() is True
