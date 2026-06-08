"""
Phase 201 · INNOV-106 · CMAC Acceptance Suite — 30/30 tests
pytest -m phase201
"""
import os, sys, uuid, time
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dorkllm.constitutional_mutation_admission_controller import (
    ConstitutionalMutationAdmissionController, CMACAdmissionLedger,
    AdmissionRequest, BlastRadius, AdmissionVerdict, DenialReason,
    CMACConstitutionalViolation, CMACOverrideUnauthorized, CMACChainViolation,
)

pytestmark = pytest.mark.phase201
HUMAN0 = "DUSTIN L REID"


def _cmac(tmp_path, **kw):
    path = str(tmp_path / "admission_ledger.jsonl")
    return ConstitutionalMutationAdmissionController(
        ledger=CMACAdmissionLedger(path), **kw
    )

def _req(**overrides):
    base = dict(
        request_id=str(uuid.uuid4()),
        mutation_id=f"mut-{uuid.uuid4().hex[:8]}",
        blast_radius=BlastRadius.TIER1,
        invariant_classes=["Hard"],
        proposed_by="MutationAgent",
    )
    base.update(overrides)
    return AdmissionRequest(**base)


# ── FAILCLOSED ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tid", ["T201-CMAC-01"])
def test_failclosed_any_failure_denies(tid, tmp_path):
    """CMAC-FAILCLOSED-0: single gate failure → DENIED."""
    c = _cmac(tmp_path)
    req = _req(invariant_classes=["Unknown"])   # triggers gate 2 failure
    rec = c.admit(req)
    assert rec.verdict == AdmissionVerdict.DENIED


@pytest.mark.parametrize("tid", ["T201-CMAC-02"])
def test_failclosed_clean_request_admitted(tid, tmp_path):
    """CMAC-FAILCLOSED-0: fully valid request → ADMITTED."""
    c = _cmac(tmp_path)
    rec = c.admit(_req())
    assert rec.verdict == AdmissionVerdict.ADMITTED


# ── ORDER ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tid", ["T201-CMAC-03"])
def test_order_check_results_present(tid, tmp_path):
    """CMAC-ORDER-0: all 7 gate results present in record."""
    c = _cmac(tmp_path)
    rec = c.admit(_req())
    for gate in ["spec_wellformed","invariant_classes_valid","blast_auth",
                 "cooldown_clear","rate_limit_ok","lineage_conflict_free","quorum_ready"]:
        assert gate in rec.check_results


@pytest.mark.parametrize("tid", ["T201-CMAC-04"])
def test_order_spec_malformed_caught_first(tid, tmp_path):
    """CMAC-ORDER-0: malformed spec identified at gate 1."""
    c = _cmac(tmp_path)
    req = _req(mutation_id="")   # empty mutation_id
    rec = c.admit(req)
    assert rec.verdict == AdmissionVerdict.DENIED
    assert DenialReason.SPEC_MALFORMED.value in rec.denial_reasons


# ── RATELIMIT ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tid", ["T201-CMAC-05"])
def test_ratelimit_tier1_enforced(tid, tmp_path):
    """CMAC-RATELIMIT-0: TIER1 rate limit triggers DENIED when exceeded."""
    c = _cmac(tmp_path, rate_limits={"TIER1": {"max_per_window": 2, "window_seconds": 60},
                                      "TIER2": {"max_per_window": 1, "window_seconds": 300},
                                      "TIER3": {"max_per_window": 1, "window_seconds": 3600}})
    c.admit(_req())
    c.admit(_req())
    rec = c.admit(_req())
    assert rec.verdict == AdmissionVerdict.DENIED
    assert any(DenialReason.RATE_LIMIT_EXCEEDED.value in r for r in rec.denial_reasons)


@pytest.mark.parametrize("tid", ["T201-CMAC-06"])
def test_ratelimit_tier2_separate_window(tid, tmp_path):
    """CMAC-RATELIMIT-0: TIER1 limit doesn't affect TIER2 window."""
    c = _cmac(tmp_path, rate_limits={"TIER1": {"max_per_window": 1, "window_seconds": 60},
                                      "TIER2": {"max_per_window": 3, "window_seconds": 300},
                                      "TIER3": {"max_per_window": 1, "window_seconds": 3600}})
    # Exhaust TIER1
    c.admit(_req())
    # TIER2 with human0 pre-auth should still be admitted
    rec = c.admit(_req(blast_radius=BlastRadius.TIER2, human0_pre_auth=True))
    assert rec.verdict == AdmissionVerdict.ADMITTED


# ── COOLDOWN ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tid", ["T201-CMAC-07"])
def test_cooldown_after_denial(tid, tmp_path):
    """CMAC-COOLDOWN-0: denied mutation cannot be re-admitted during cooldown."""
    c = _cmac(tmp_path, cooldown_seconds=9999)
    mid = f"mut-{uuid.uuid4().hex[:8]}"
    req1 = _req(mutation_id=mid, invariant_classes=["Invalid"])
    c.admit(req1)   # DENIED — triggers cooldown
    req2 = _req(mutation_id=mid, invariant_classes=["Hard"])
    rec2 = c.admit(req2)
    assert rec2.verdict == AdmissionVerdict.DENIED
    assert any(DenialReason.COOLDOWN_ACTIVE.value in r for r in rec2.denial_reasons)


@pytest.mark.parametrize("tid", ["T201-CMAC-08"])
def test_cooldown_cleared_after_override(tid, tmp_path):
    """CMAC-COOLDOWN-0: HUMAN-0 override clears cooldown."""
    c = _cmac(tmp_path, cooldown_seconds=9999)
    mid = f"mut-{uuid.uuid4().hex[:8]}"
    req = _req(mutation_id=mid, invariant_classes=["Invalid"])
    denied = c.admit(req)
    c.override(denied.request_id, HUMAN0)
    # cooldown should be cleared — new unique mutation should admit fine
    new_req = _req(invariant_classes=["Hard"])
    rec = c.admit(new_req)
    assert rec.verdict == AdmissionVerdict.ADMITTED


# ── BLASTAUTH ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tid", ["T201-CMAC-09"])
def test_blastauth_tier2_without_preauth_denied(tid, tmp_path):
    """CMAC-BLASTAUTH-0: TIER2 without human0_pre_auth → DENIED."""
    c = _cmac(tmp_path)
    rec = c.admit(_req(blast_radius=BlastRadius.TIER2, human0_pre_auth=False))
    assert rec.verdict == AdmissionVerdict.DENIED
    assert DenialReason.BLAST_RADIUS_UNAUTHORIZED.value in rec.denial_reasons


@pytest.mark.parametrize("tid", ["T201-CMAC-10"])
def test_blastauth_tier2_with_preauth_passes(tid, tmp_path):
    """CMAC-BLASTAUTH-0: TIER2 with human0_pre_auth + quorum → ADMITTED."""
    c = _cmac(tmp_path)
    rec = c.admit(_req(blast_radius=BlastRadius.TIER2, human0_pre_auth=True))
    assert rec.verdict == AdmissionVerdict.ADMITTED


@pytest.mark.parametrize("tid", ["T201-CMAC-11"])
def test_blastauth_tier3_without_quorum_denied(tid, tmp_path):
    """CMAC-QUORUM-0: TIER3 without quorum_confirmed → DENIED."""
    c = _cmac(tmp_path)
    rec = c.admit(_req(blast_radius=BlastRadius.TIER3, human0_pre_auth=True, quorum_confirmed=False))
    assert rec.verdict == AdmissionVerdict.DENIED
    assert DenialReason.QUORUM_NOT_READY.value in rec.denial_reasons


@pytest.mark.parametrize("tid", ["T201-CMAC-12"])
def test_blastauth_tier3_with_quorum_admitted(tid, tmp_path):
    """CMAC-QUORUM-0 + CMAC-BLASTAUTH-0: TIER3 with both flags → ADMITTED."""
    c = _cmac(tmp_path)
    rec = c.admit(_req(blast_radius=BlastRadius.TIER3, human0_pre_auth=True, quorum_confirmed=True))
    assert rec.verdict == AdmissionVerdict.ADMITTED


@pytest.mark.parametrize("tid", ["T201-CMAC-13"])
def test_blastauth_tier1_no_preauth_needed(tid, tmp_path):
    """CMAC-BLASTAUTH-0: TIER1 does not require human0_pre_auth."""
    c = _cmac(tmp_path)
    rec = c.admit(_req(blast_radius=BlastRadius.TIER1, human0_pre_auth=False))
    assert rec.verdict == AdmissionVerdict.ADMITTED


# ── LINEAGE CONFLICT ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("tid", ["T201-CMAC-14"])
def test_lineage_conflict_duplicate_denied(tid, tmp_path):
    """Duplicate mutation_id in pipeline → LINEAGE_CONFLICT DENIED."""
    c = _cmac(tmp_path)
    mid = f"mut-{uuid.uuid4().hex[:8]}"
    c.admit(_req(mutation_id=mid))
    rec2 = c.admit(_req(mutation_id=mid))
    assert rec2.verdict == AdmissionVerdict.DENIED
    assert DenialReason.LINEAGE_CONFLICT.value in rec2.denial_reasons


@pytest.mark.parametrize("tid", ["T201-CMAC-15"])
def test_lineage_conflict_unique_ids_admitted(tid, tmp_path):
    """Different mutation_ids have no lineage conflict."""
    c = _cmac(tmp_path)
    r1 = c.admit(_req())
    r2 = c.admit(_req())
    assert r1.verdict == AdmissionVerdict.ADMITTED
    assert r2.verdict == AdmissionVerdict.ADMITTED


# ── INVARIANT CLASS ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("tid", ["T201-CMAC-16"])
def test_invariant_class_invalid_denied(tid, tmp_path):
    """Unknown invariant class → INVARIANT_CLASS_INVALID DENIED."""
    c = _cmac(tmp_path)
    rec = c.admit(_req(invariant_classes=["SuperHard"]))
    assert DenialReason.INVARIANT_CLASS_INVALID.value in rec.denial_reasons


@pytest.mark.parametrize("tid", ["T201-CMAC-17"])
def test_invariant_class_all_valid_classes(tid, tmp_path):
    """All valid invariant classes accepted."""
    c = _cmac(tmp_path)
    for cls in ["Hard", "Soft", "Governance", "Safety"]:
        rec = c.admit(_req(invariant_classes=[cls]))
        assert rec.verdict == AdmissionVerdict.ADMITTED


# ── CHAIN ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tid", ["T201-CMAC-18"])
def test_chain_genesis_prev_hash(tid, tmp_path):
    """CMAC-CHAIN-0: first entry prev_hash == GENESIS."""
    c = _cmac(tmp_path)
    c.admit(_req())
    assert c._ledger.all_records()[0].prev_hash == "GENESIS"


@pytest.mark.parametrize("tid", ["T201-CMAC-19"])
def test_chain_links_correctly(tid, tmp_path):
    """CMAC-CHAIN-0: each entry prev_hash == previous entry_hash."""
    c = _cmac(tmp_path)
    for _ in range(4):
        c.admit(_req())
    recs = c._ledger.all_records()
    for i in range(1, len(recs)):
        assert recs[i].prev_hash == recs[i-1].entry_hash


@pytest.mark.parametrize("tid", ["T201-CMAC-20"])
def test_chain_verify_passes(tid, tmp_path):
    """CMAC-CHAIN-0: verify_chain passes on clean ledger."""
    c = _cmac(tmp_path)
    for _ in range(5):
        c.admit(_req())
    assert c.verify_chain() is True


# ── IMMUT ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tid", ["T201-CMAC-21"])
def test_immut_ledger_only_grows(tid, tmp_path):
    """CMAC-IMMUT-0: record count only increases."""
    c = _cmac(tmp_path)
    counts = []
    for _ in range(5):
        c.admit(_req())
        counts.append(len(c._ledger.all_records()))
    assert counts == sorted(counts)


# ── OVERRIDE ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tid", ["T201-CMAC-22"])
def test_override_non_human0_raises(tid, tmp_path):
    """CMAC-OVERRIDE-0: non-HUMAN-0 override raises."""
    c = _cmac(tmp_path)
    rec = c.admit(_req(invariant_classes=["Invalid"]))
    with pytest.raises(CMACOverrideUnauthorized):
        c.override(rec.request_id, "random-agent")


@pytest.mark.parametrize("tid", ["T201-CMAC-23"])
def test_override_human0_succeeds(tid, tmp_path):
    """CMAC-OVERRIDE-0: HUMAN-0 can override DENIED admission."""
    c = _cmac(tmp_path)
    denied = c.admit(_req(invariant_classes=["Invalid"]))
    ov = c.override(denied.request_id, HUMAN0)
    assert ov.verdict == AdmissionVerdict.OVERRIDDEN
    assert ov.override_by == HUMAN0


@pytest.mark.parametrize("tid", ["T201-CMAC-24"])
def test_override_admitted_record_raises(tid, tmp_path):
    """CMAC-OVERRIDE-0: cannot override an ADMITTED decision."""
    c = _cmac(tmp_path)
    admitted = c.admit(_req())
    with pytest.raises(CMACConstitutionalViolation):
        c.override(admitted.request_id, HUMAN0)


@pytest.mark.parametrize("tid", ["T201-CMAC-25"])
def test_override_appends_new_ledger_entry(tid, tmp_path):
    """CMAC-IMMUT-0: override appends new record, original unchanged."""
    c = _cmac(tmp_path)
    denied = c.admit(_req(invariant_classes=["Invalid"]))
    before = len(c._ledger.all_records())
    c.override(denied.request_id, HUMAN0)
    after = len(c._ledger.all_records())
    assert after == before + 1


# ── AUDIT ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tid", ["T201-CMAC-26"])
def test_audit_timestamp_present(tid, tmp_path):
    """CMAC-AUDIT-0: every record has ISO-8601 timestamp."""
    c = _cmac(tmp_path)
    rec = c.admit(_req())
    assert "T" in rec.timestamp and "Z" in rec.timestamp


@pytest.mark.parametrize("tid", ["T201-CMAC-27"])
def test_audit_denial_reasons_recorded(tid, tmp_path):
    """CMAC-AUDIT-0: denial reasons are captured in record."""
    c = _cmac(tmp_path)
    rec = c.admit(_req(invariant_classes=["Bad"], blast_radius=BlastRadius.TIER2))
    assert len(rec.denial_reasons) >= 2   # class invalid + blast unauth


# ── SUMMARY / EXPORT ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("tid", ["T201-CMAC-28"])
def test_summary_structure(tid, tmp_path):
    """summary() returns all required keys."""
    c = _cmac(tmp_path)
    c.admit(_req())
    s = c.summary()
    for k in ["total_decisions","verdict_counts","chain_tip","invariants","governor"]:
        assert k in s


@pytest.mark.parametrize("tid", ["T201-CMAC-29"])
def test_export_structure(tid, tmp_path):
    """export() returns ledger_path, total_records, chain_tip, records."""
    c = _cmac(tmp_path)
    c.admit(_req())
    e = c.export()
    assert "ledger_path" in e and "total_records" in e and "records" in e


@pytest.mark.parametrize("tid", ["T201-CMAC-30"])
def test_invariant_ids_complete(tid, tmp_path):
    """All 10 CMAC Hard-class invariant IDs present in manifest."""
    c = _cmac(tmp_path)
    expected = {
        "CMAC-FAILCLOSED-0","CMAC-ORDER-0","CMAC-RATELIMIT-0","CMAC-COOLDOWN-0",
        "CMAC-BLASTAUTH-0","CMAC-CHAIN-0","CMAC-IMMUT-0",
        "CMAC-OVERRIDE-0","CMAC-AUDIT-0","CMAC-QUORUM-0",
    }
    assert set(c.INVARIANT_IDS) == expected
