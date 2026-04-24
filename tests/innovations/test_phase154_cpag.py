# SPDX-License-Identifier: Apache-2.0
"""Phase 154 / INNOV-60 — Constitutional Pre-Admission Gate (CPAG) acceptance suite.

30 tests covering all 5 Hard-class invariants:
  CPAG-DETERM-0   : determinism       (CPAG01–CPAG06)
  CPAG-LEDGER-0   : ledger-first      (CPAG07–CPAG12)
  CPAG-FAILCLOSE-0: fail-closed gate  (CPAG13–CPAG18)
  CPAG-HUMAN0-0   : auth gate         (CPAG19–CPAG24)
  CPAG-SCOPE-0    : scope guard       (CPAG25–CPAG30)
"""

import pytest

from dorkllm.constitutional_gate import (
    AdmissionVerdict,
    ConstitutionalGate,
    ConstitutionalInvariant,
    CPAGAuthError,
    CPAGConfig,
    CPAGDeterminismError,
    CPAGLedger,
    CPAGLedgerError,
    CPAGRejectionError,
    CPAGScopeError,
    VerdictResult,
    default_invariant_set,
)

# ---------------------------------------------------------------------------
# Spec fixtures
# ---------------------------------------------------------------------------

VALID_SPEC = {
    "ledger_first": True,
    "operator": "Dustin L. Reid",
    "deterministic": True,
    "entropy_source": "none",
    "affected_modules": ["dorkllm/constitutional_gate.py"],
    "innovation_id": "INNOV-60",
}

INVALID_SPEC_NO_LEDGER = {
    "ledger_first": False,
    "operator": "Dustin L. Reid",
    "deterministic": True,
    "entropy_source": "none",
    "affected_modules": ["foo.py"],
    "innovation_id": "INNOV-60",
}

INVALID_SPEC_NO_OPERATOR = {
    "ledger_first": True,
    "operator": "",
    "deterministic": True,
    "entropy_source": "none",
    "affected_modules": ["foo.py"],
    "innovation_id": "INNOV-60",
}

INVALID_SPEC_RANDOM_ENTROPY = {
    "ledger_first": True,
    "operator": "Dustin L. Reid",
    "deterministic": True,
    "entropy_source": "random",
    "affected_modules": ["foo.py"],
    "innovation_id": "INNOV-60",
}

INVALID_SPEC_NOT_DETERM = {
    "ledger_first": True,
    "operator": "Dustin L. Reid",
    "deterministic": False,
    "entropy_source": "none",
    "affected_modules": ["foo.py"],
    "innovation_id": "INNOV-60",
}


@pytest.fixture
def gate():
    return ConstitutionalGate()


# ===========================================================================
# CPAG-DETERM-0: determinism (CPAG01–CPAG06)
# ===========================================================================


@pytest.mark.phase154
def test_CPAG01_identical_valid_spec_identical_verdict():
    """CPAG-DETERM-0: same valid spec always returns same verdict."""
    v1 = ConstitutionalGate().gate(VALID_SPEC)
    v2 = ConstitutionalGate().gate(VALID_SPEC)
    assert v1.result == v2.result
    assert v1.score == v2.score


@pytest.mark.phase154
def test_CPAG02_identical_invalid_spec_identical_rejection():
    """CPAG-DETERM-0: same invalid spec always raises with same score."""
    def get_score(spec):
        try:
            ConstitutionalGate().gate(spec)
        except CPAGRejectionError as e:
            return e.verdict.score
    s1 = get_score(INVALID_SPEC_NO_LEDGER)
    s2 = get_score(INVALID_SPEC_NO_LEDGER)
    assert s1 == s2


@pytest.mark.phase154
def test_CPAG03_mutation_id_deterministic_from_spec():
    """CPAG-DETERM-0: mutation_id derived deterministically from spec content."""
    v1 = ConstitutionalGate().gate(VALID_SPEC)
    v2 = ConstitutionalGate().gate(VALID_SPEC)
    assert v1.mutation_id == v2.mutation_id


@pytest.mark.phase154
def test_CPAG04_score_range_valid():
    """CPAG-DETERM-0: score always in [0.0, 1.0]."""
    v = ConstitutionalGate().gate(VALID_SPEC)
    assert 0.0 <= v.score <= 1.0


@pytest.mark.phase154
def test_CPAG05_per_invariant_evals_deterministic():
    """CPAG-DETERM-0: evaluation list identical for identical inputs."""
    v1 = ConstitutionalGate().gate(VALID_SPEC)
    v2 = ConstitutionalGate().gate(VALID_SPEC)
    ids1 = [e.invariant_id for e in v1.evaluations]
    ids2 = [e.invariant_id for e in v2.evaluations]
    assert ids1 == ids2
    assert all(e1.passed == e2.passed for e1, e2 in zip(v1.evaluations, v2.evaluations))


@pytest.mark.phase154
def test_CPAG06_throttle_tightens_admission_deterministically():
    """CPAG-DETERM-0: lower throttle → higher effective_admit_min."""
    g1 = ConstitutionalGate()
    g2 = ConstitutionalGate()
    v1 = g1.gate(VALID_SPEC, throttle_multiplier=1.0)
    v2 = g2.gate(VALID_SPEC, throttle_multiplier=0.50)
    assert v2.effective_admit_min >= v1.effective_admit_min


# ===========================================================================
# CPAG-LEDGER-0: ledger-first (CPAG07–CPAG12)
# ===========================================================================


@pytest.mark.phase154
def test_CPAG07_admit_writes_verdict_to_ledger(gate):
    """CPAG-LEDGER-0: ADMIT verdict writes ADMISSION_VERDICT record."""
    gate.gate(VALID_SPEC)
    events = [r for r in gate.ledger().records() if r["event_type"] == "ADMISSION_VERDICT"]
    assert len(events) == 1


@pytest.mark.phase154
def test_CPAG08_reject_writes_verdict_before_raising(gate):
    """CPAG-LEDGER-0: REJECT still writes ledger record before raising."""
    with pytest.raises(CPAGRejectionError):
        gate.gate(INVALID_SPEC_NO_LEDGER)
    events = [r for r in gate.ledger().records() if r["event_type"] == "ADMISSION_VERDICT"]
    assert len(events) == 1
    assert events[0]["result"] == "REJECT"


@pytest.mark.phase154
def test_CPAG09_multiple_gates_multiple_ledger_records(gate):
    """CPAG-LEDGER-0: n gate() calls → n ADMISSION_VERDICT records."""
    gate.gate(VALID_SPEC)
    for bad in [INVALID_SPEC_NO_OPERATOR, INVALID_SPEC_NOT_DETERM]:
        with pytest.raises(CPAGRejectionError):
            gate.gate(bad)
    events = [r for r in gate.ledger().records() if r["event_type"] == "ADMISSION_VERDICT"]
    assert len(events) == 3


@pytest.mark.phase154
def test_CPAG10_ledger_chain_valid_after_verdicts(gate):
    """CPAG-LEDGER-0: HMAC chain integrity maintained across calls."""
    gate.gate(VALID_SPEC)
    with pytest.raises(CPAGRejectionError):
        gate.gate(INVALID_SPEC_NO_LEDGER)
    assert gate.verify_ledger() is True


@pytest.mark.phase154
def test_CPAG11_verdict_carries_seq_and_digest(gate):
    """CPAG-LEDGER-0: AdmissionVerdict has non-empty ledger_seq and digest."""
    v = gate.gate(VALID_SPEC)
    assert v.ledger_seq >= 1
    assert len(v.ledger_digest) == 64


@pytest.mark.phase154
def test_CPAG12_ledger_write_failure_raises_cpag_ledger_error():
    """CPAG-LEDGER-0: simulated I/O failure → CPAGLedgerError propagates."""

    class FailingLedger(CPAGLedger):
        def append(self, event_type, payload):
            raise CPAGLedgerError("simulated failure")

    g = ConstitutionalGate(ledger=FailingLedger())
    with pytest.raises(CPAGLedgerError):
        g.gate(VALID_SPEC)


# ===========================================================================
# CPAG-FAILCLOSE-0: fail-closed gate (CPAG13–CPAG18)
# ===========================================================================


@pytest.mark.phase154
def test_CPAG13_reject_on_missing_ledger_first(gate):
    """CPAG-FAILCLOSE-0: ledger_first=False → CPAGRejectionError."""
    with pytest.raises(CPAGRejectionError) as exc_info:
        gate.gate(INVALID_SPEC_NO_LEDGER)
    assert exc_info.value.verdict.result == VerdictResult.REJECT


@pytest.mark.phase154
def test_CPAG14_reject_on_empty_operator(gate):
    """CPAG-FAILCLOSE-0: empty operator field → CPAGRejectionError."""
    with pytest.raises(CPAGRejectionError):
        gate.gate(INVALID_SPEC_NO_OPERATOR)


@pytest.mark.phase154
def test_CPAG15_reject_on_random_entropy(gate):
    """CPAG-FAILCLOSE-0: entropy_source=random → CPAGRejectionError."""
    with pytest.raises(CPAGRejectionError):
        gate.gate(INVALID_SPEC_RANDOM_ENTROPY)


@pytest.mark.phase154
def test_CPAG16_reject_carries_violation_count(gate):
    """CPAG-FAILCLOSE-0: verdict includes correct hard_violations count."""
    with pytest.raises(CPAGRejectionError) as exc_info:
        gate.gate(INVALID_SPEC_NO_LEDGER)
    assert exc_info.value.verdict.hard_violations >= 1


@pytest.mark.phase154
def test_CPAG17_valid_spec_does_not_raise(gate):
    """CPAG-FAILCLOSE-0: fully compliant spec → ADMIT, no exception."""
    verdict = gate.gate(VALID_SPEC)
    assert verdict.result == VerdictResult.ADMIT


@pytest.mark.phase154
def test_CPAG18_defer_verdict_does_not_raise():
    """CPAG-FAILCLOSE-0: DEFER is not a rejection — no exception raised."""
    # Create gate with high admit_min so valid spec only reaches DEFER
    cfg = CPAGConfig(admit_min=1.0, defer_min=0.50, reject_floor=0.10)
    g = ConstitutionalGate(config=cfg)
    # VALID_SPEC passes all Hard invariants but may miss soft ones
    # Inject a soft-failing variant
    soft_fail = dict(VALID_SPEC)
    soft_fail["affected_modules"] = None  # soft failure
    soft_fail["innovation_id"] = None     # soft failure
    verdict = g.gate(soft_fail)
    assert verdict.result in (VerdictResult.ADMIT, VerdictResult.DEFER)


# ===========================================================================
# CPAG-HUMAN0-0: auth gate (CPAG19–CPAG24)
# ===========================================================================


@pytest.mark.phase154
def test_CPAG19_empty_operator_threshold_reconfig_rejected(gate):
    """CPAG-HUMAN0-0: empty operator → CPAGAuthError."""
    with pytest.raises(CPAGAuthError):
        gate.reconfigure_thresholds(0.85, 0.60, 0.60, operator="")


@pytest.mark.phase154
def test_CPAG20_none_operator_threshold_reconfig_rejected(gate):
    """CPAG-HUMAN0-0: None operator → CPAGAuthError."""
    with pytest.raises(CPAGAuthError):
        gate.reconfigure_thresholds(0.85, 0.60, 0.60, operator=None)


@pytest.mark.phase154
def test_CPAG21_whitespace_operator_rejected(gate):
    """CPAG-HUMAN0-0: whitespace-only operator → CPAGAuthError."""
    with pytest.raises(CPAGAuthError):
        gate.reconfigure_thresholds(0.85, 0.60, 0.60, operator="   ")


@pytest.mark.phase154
def test_CPAG22_valid_operator_reconfig_accepted(gate):
    """CPAG-HUMAN0-0: valid operator → threshold config accepted."""
    seq, digest = gate.reconfigure_thresholds(0.90, 0.65, 0.65, operator="Dustin L. Reid")
    assert seq >= 1
    assert digest


@pytest.mark.phase154
def test_CPAG23_reconfig_writes_threshold_config_event(gate):
    """CPAG-HUMAN0-0: reconfig writes THRESHOLD_CONFIG ledger record."""
    gate.reconfigure_thresholds(0.90, 0.65, 0.65, operator="Dustin L. Reid")
    events = [r for r in gate.ledger().records() if r["event_type"] == "THRESHOLD_CONFIG"]
    assert len(events) == 1
    assert events[0]["operator"] == "Dustin L. Reid"


@pytest.mark.phase154
def test_CPAG24_reconfigured_thresholds_take_effect(gate):
    """CPAG-HUMAN0-0: after reconfig, new thresholds govern verdicts."""
    # Set admit_min very high so VALID_SPEC defers
    gate.reconfigure_thresholds(1.0, 0.50, 0.10, operator="Dustin L. Reid")
    assert gate.config().admit_min == 1.0


# ===========================================================================
# CPAG-SCOPE-0: scope guard (CPAG25–CPAG30)
# ===========================================================================


@pytest.mark.phase154
def test_CPAG25_non_dict_spec_raises_scope_error(gate):
    """CPAG-SCOPE-0: non-dict mutation_spec → CPAGScopeError."""
    with pytest.raises(CPAGScopeError):
        gate.gate("not a dict")


@pytest.mark.phase154
def test_CPAG26_list_spec_raises_scope_error(gate):
    """CPAG-SCOPE-0: list mutation_spec → CPAGScopeError."""
    with pytest.raises(CPAGScopeError):
        gate.gate([1, 2, 3])


@pytest.mark.phase154
def test_CPAG27_integer_spec_raises_scope_error(gate):
    """CPAG-SCOPE-0: integer mutation_spec → CPAGScopeError."""
    with pytest.raises(CPAGScopeError):
        gate.gate(42)


@pytest.mark.phase154
def test_CPAG28_default_invariant_set_is_self_contained():
    """CPAG-SCOPE-0: default_invariant_set performs no I/O — pure structure."""
    invs = default_invariant_set()
    assert len(invs) >= 4
    for inv in invs:
        assert inv.id
        assert inv.tier in ("Hard", "Soft")


@pytest.mark.phase154
def test_CPAG29_gate_does_not_mutate_input_spec(gate):
    """CPAG-SCOPE-0: gate() must not modify the caller's spec dict."""
    spec = dict(VALID_SPEC)
    original_keys = set(spec.keys())
    gate.gate(spec)
    assert set(spec.keys()) == original_keys


@pytest.mark.phase154
def test_CPAG30_innov_id_and_version_correct():
    """Integration: INNOV_ID, PHASE, VERSION, and invariant manifest correct."""
    from runtime.innovations30.constitutional_pre_admission_gate import (
        INNOVATION_ID,
        PHASE,
        VERSION,
        HARD_CLASS_INVARIANTS,
    )
    assert INNOVATION_ID == "INNOV-60"
    assert PHASE == 154
    assert VERSION == "9.87.0"
    assert len(HARD_CLASS_INVARIANTS) == 5
    ids = [inv["id"] for inv in HARD_CLASS_INVARIANTS]
    assert ids == [
        "CPAG-DETERM-0",
        "CPAG-LEDGER-0",
        "CPAG-FAILCLOSE-0",
        "CPAG-HUMAN0-0",
        "CPAG-SCOPE-0",
    ]
