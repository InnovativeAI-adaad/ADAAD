# SPDX-License-Identifier: Apache-2.0
"""Phase 153 / INNOV-59 — Adaptive Mutation Throttle (AMT) acceptance suite.

30 tests covering all 5 Hard-class invariants:
  AMT-DETERM-0  : determinism  (AMT01–AMT06)
  AMT-LEDGER-0  : ledger-first (AMT07–AMT12)
  AMT-FLOOR-0   : floor clamp  (AMT13–AMT18)
  AMT-HUMAN0-0  : auth gate    (AMT19–AMT24)
  AMT-FEEDBACK-0: scope guard  (AMT25–AMT30)
"""

import pytest

from dorkllm.adaptive_throttle import (
    AMT_FLOOR,
    AMTAuthError,
    AMTConfig,
    AMTDeterminismError,
    AMTFloorError,
    AMTLedger,
    AMTLedgerError,
    AMTScopeError,
    ThrottleEngine,
    ThrottleRegime,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

LOW_PRESSURE = {d: 0.10 for d in ["SECURITY", "DETERMINISM", "REPLAY", "HUMAN0", "MUTATION", "LEDGER"]}
MED_PRESSURE = {d: 0.50 for d in ["SECURITY", "DETERMINISM", "REPLAY", "HUMAN0", "MUTATION", "LEDGER"]}
HIGH_PRESSURE = {d: 0.90 for d in ["SECURITY", "DETERMINISM", "REPLAY", "HUMAN0", "MUTATION", "LEDGER"]}


@pytest.fixture
def engine():
    return ThrottleEngine()


@pytest.fixture
def cfg_engine():
    cfg = AMTConfig.default()
    return ThrottleEngine(config=cfg, ledger=AMTLedger())


# ===========================================================================
# AMT-DETERM-0: determinism (AMT01–AMT06)
# ===========================================================================


@pytest.mark.phase153
def test_AMT01_identical_inputs_identical_output(engine):
    """AMT-DETERM-0: same domain_scores always yields same multiplier."""
    s1 = engine.compute(LOW_PRESSURE)
    engine2 = ThrottleEngine()
    s2 = engine2.compute(LOW_PRESSURE)
    assert s1.multiplier == s2.multiplier


@pytest.mark.phase153
def test_AMT02_determinism_med_pressure(engine):
    """AMT-DETERM-0: medium pressure deterministic across instances."""
    s1 = ThrottleEngine().compute(MED_PRESSURE)
    s2 = ThrottleEngine().compute(MED_PRESSURE)
    assert s1.multiplier == s2.multiplier
    assert s1.composite_pressure == s2.composite_pressure


@pytest.mark.phase153
def test_AMT03_determinism_high_pressure(engine):
    """AMT-DETERM-0: high pressure deterministic, clamps at floor."""
    s1 = ThrottleEngine().compute(HIGH_PRESSURE)
    s2 = ThrottleEngine().compute(HIGH_PRESSURE)
    assert s1.multiplier == s2.multiplier == AMT_FLOOR


@pytest.mark.phase153
def test_AMT04_domain_contributions_deterministic():
    """AMT-DETERM-0: domain_contributions dict identical for identical inputs."""
    s1 = ThrottleEngine().compute(MED_PRESSURE)
    s2 = ThrottleEngine().compute(MED_PRESSURE)
    assert s1.domain_contributions == s2.domain_contributions


@pytest.mark.phase153
def test_AMT05_zero_weight_raises_determinism_error():
    """AMT-DETERM-0: zero-weight config is non-deterministic — must raise."""
    cfg = AMTConfig(domain_weights={})
    eng = ThrottleEngine(config=cfg)
    with pytest.raises(AMTDeterminismError):
        eng.compute(LOW_PRESSURE)


@pytest.mark.phase153
def test_AMT06_multiplier_decreases_with_pressure():
    """AMT-DETERM-0: monotone — higher pressure → lower multiplier."""
    s_low = ThrottleEngine().compute(LOW_PRESSURE)
    s_med = ThrottleEngine().compute(MED_PRESSURE)
    s_hi = ThrottleEngine().compute(HIGH_PRESSURE)
    assert s_low.multiplier > s_med.multiplier >= s_hi.multiplier


# ===========================================================================
# AMT-LEDGER-0: ledger-first (AMT07–AMT12)
# ===========================================================================


@pytest.mark.phase153
def test_AMT07_compute_writes_throttle_event(engine):
    """AMT-LEDGER-0: compute() appends a THROTTLE_EVENT to ledger."""
    engine.compute(LOW_PRESSURE)
    events = [r for r in engine.ledger().records() if r["event_type"] == "THROTTLE_EVENT"]
    assert len(events) == 1


@pytest.mark.phase153
def test_AMT08_multiple_computes_write_multiple_events(engine):
    """AMT-LEDGER-0: n compute() calls → n THROTTLE_EVENT records."""
    for _ in range(5):
        engine.compute(LOW_PRESSURE)
    events = [r for r in engine.ledger().records() if r["event_type"] == "THROTTLE_EVENT"]
    assert len(events) == 5


@pytest.mark.phase153
def test_AMT09_ledger_chain_valid_after_computes(engine):
    """AMT-LEDGER-0: ledger chain integrity maintained across calls."""
    for p in [LOW_PRESSURE, MED_PRESSURE, HIGH_PRESSURE]:
        engine.compute(p)
    assert engine.verify_ledger() is True


@pytest.mark.phase153
def test_AMT10_snapshot_seq_increments(engine):
    """AMT-LEDGER-0: ledger_seq increases monotonically."""
    s1 = engine.compute(LOW_PRESSURE)
    s2 = engine.compute(MED_PRESSURE)
    assert s2.ledger_seq > s1.ledger_seq


@pytest.mark.phase153
def test_AMT11_snapshot_digest_non_empty(engine):
    """AMT-LEDGER-0: snapshot carries non-empty ledger_digest."""
    snap = engine.compute(LOW_PRESSURE)
    assert snap.ledger_digest and len(snap.ledger_digest) == 64


@pytest.mark.phase153
def test_AMT12_ledger_write_failure_raises_amt_ledger_error():
    """AMT-LEDGER-0: simulated I/O failure → AMTLedgerError propagates."""

    class FailingLedger(AMTLedger):
        def append(self, event_type: str, payload: dict):
            raise AMTLedgerError(
                "AMT-LEDGER-0 violated: simulated ledger write failure"
            )

    eng = ThrottleEngine(ledger=FailingLedger())
    with pytest.raises(AMTLedgerError):
        eng.compute(LOW_PRESSURE)


# ===========================================================================
# AMT-FLOOR-0: floor clamp (AMT13–AMT18)
# ===========================================================================


@pytest.mark.phase153
def test_AMT13_multiplier_never_below_floor():
    """AMT-FLOOR-0: normal operation never produces multiplier < AMT_FLOOR."""
    snap = ThrottleEngine().compute(HIGH_PRESSURE)
    assert snap.multiplier >= AMT_FLOOR


@pytest.mark.phase153
def test_AMT14_low_pressure_multiplier_near_one():
    """AMT-FLOOR-0: near-zero pressure → multiplier close to 1.0."""
    snap = ThrottleEngine().compute({d: 0.0 for d in LOW_PRESSURE})
    assert snap.multiplier >= 0.95


@pytest.mark.phase153
def test_AMT15_regime_open_at_low_pressure():
    """AMT-FLOOR-0: low pressure → OPEN regime."""
    snap = ThrottleEngine().compute(LOW_PRESSURE)
    assert snap.regime == ThrottleRegime.OPEN


@pytest.mark.phase153
def test_AMT16_regime_restrict_at_high_pressure():
    """AMT-FLOOR-0: high pressure → RESTRICT regime."""
    snap = ThrottleEngine().compute(HIGH_PRESSURE)
    assert snap.regime == ThrottleRegime.RESTRICT


@pytest.mark.phase153
def test_AMT17_emergency_override_sets_multiplier_zero():
    """AMT-FLOOR-0: HUMAN-0 override may set multiplier to 0.0."""
    eng = ThrottleEngine()
    eng.engage_emergency_override("Dustin L. Reid")
    snap = eng.compute(LOW_PRESSURE)
    assert snap.multiplier == 0.0
    assert snap.regime == ThrottleRegime.OVERRIDE


@pytest.mark.phase153
def test_AMT18_override_release_restores_normal_operation():
    """AMT-FLOOR-0: releasing override restores normal floor behaviour."""
    eng = ThrottleEngine()
    eng.engage_emergency_override("Dustin L. Reid")
    eng.release_emergency_override("Dustin L. Reid")
    snap = eng.compute(LOW_PRESSURE)
    assert snap.multiplier >= AMT_FLOOR
    assert snap.regime != ThrottleRegime.OVERRIDE


# ===========================================================================
# AMT-HUMAN0-0: auth gate (AMT19–AMT24)
# ===========================================================================


@pytest.mark.phase153
def test_AMT19_empty_operator_override_rejected(engine):
    """AMT-HUMAN0-0: empty string operator → AMTAuthError."""
    with pytest.raises(AMTAuthError):
        engine.engage_emergency_override("")


@pytest.mark.phase153
def test_AMT20_none_operator_override_rejected(engine):
    """AMT-HUMAN0-0: None operator → AMTAuthError."""
    with pytest.raises(AMTAuthError):
        engine.engage_emergency_override(None)


@pytest.mark.phase153
def test_AMT21_whitespace_operator_override_rejected(engine):
    """AMT-HUMAN0-0: whitespace-only operator → AMTAuthError."""
    with pytest.raises(AMTAuthError):
        engine.engage_emergency_override("   ")


@pytest.mark.phase153
def test_AMT22_empty_operator_reconfigure_rejected(engine):
    """AMT-HUMAN0-0: weight reconfig with empty operator → AMTAuthError."""
    with pytest.raises(AMTAuthError):
        engine.reconfigure_weights({"SECURITY": 1.0}, operator="")


@pytest.mark.phase153
def test_AMT23_valid_operator_override_accepted(engine):
    """AMT-HUMAN0-0: valid operator string is accepted."""
    seq, digest = engine.engage_emergency_override("Dustin L. Reid")
    assert seq >= 1
    assert digest


@pytest.mark.phase153
def test_AMT24_weight_reconfiguration_logged_to_ledger(engine):
    """AMT-HUMAN0-0: weight reconfig writes WEIGHT_CONFIG event."""
    engine.reconfigure_weights({"SECURITY": 0.5, "MUTATION": 0.5}, operator="Dustin L. Reid")
    events = [r for r in engine.ledger().records() if r["event_type"] == "WEIGHT_CONFIG"]
    assert len(events) == 1
    assert events[0]["operator"] == "Dustin L. Reid"


# ===========================================================================
# AMT-FEEDBACK-0: scope guard (AMT25–AMT30)
# ===========================================================================


@pytest.mark.phase153
def test_AMT25_allowed_throttle_event_passes_filter():
    """AMT-FEEDBACK-0: THROTTLE_EVENT is in allowed ingestion set."""
    ledger = AMTLedger()
    records = [{"event_type": "THROTTLE_EVENT", "multiplier": 0.9}]
    filtered = ledger.filter_allowed(records)
    assert len(filtered) == 1


@pytest.mark.phase153
def test_AMT26_allowed_pressure_snapshot_passes_filter():
    """AMT-FEEDBACK-0: PRESSURE_SNAPSHOT is in allowed ingestion set."""
    ledger = AMTLedger()
    records = [{"event_type": "PRESSURE_SNAPSHOT", "scores": {}}]
    filtered = ledger.filter_allowed(records)
    assert len(filtered) == 1


@pytest.mark.phase153
def test_AMT27_disallowed_cel_event_raises_scope_error():
    """AMT-FEEDBACK-0: CEL_STEP event is not in allowed set → AMTScopeError."""
    ledger = AMTLedger()
    with pytest.raises(AMTScopeError):
        ledger.filter_allowed([{"event_type": "CEL_STEP", "data": {}}])


@pytest.mark.phase153
def test_AMT28_disallowed_mutation_event_raises_scope_error():
    """AMT-FEEDBACK-0: MUTATION_APPLIED is not allowed → AMTScopeError."""
    ledger = AMTLedger()
    with pytest.raises(AMTScopeError):
        ledger.filter_allowed([{"event_type": "MUTATION_APPLIED", "data": {}}])


@pytest.mark.phase153
def test_AMT29_disallowed_gcb_event_raises_scope_error():
    """AMT-FEEDBACK-0: CIRCUIT_OPEN is not in AMT ingestion set."""
    ledger = AMTLedger()
    with pytest.raises(AMTScopeError):
        ledger.filter_allowed([{"event_type": "CIRCUIT_OPEN", "data": {}}])


@pytest.mark.phase153
def test_AMT30_innov_id_and_version_correct():
    """Integration: INNOV_ID and VERSION match canonical values."""
    from runtime.innovations30.adaptive_mutation_throttle import (
        INNOVATION_ID,
        PHASE,
        VERSION,
        HARD_CLASS_INVARIANTS,
    )
    assert INNOVATION_ID == "INNOV-59"
    assert PHASE == 153
    assert VERSION == "9.86.0"
    assert len(HARD_CLASS_INVARIANTS) == 5
    ids = [inv["id"] for inv in HARD_CLASS_INVARIANTS]
    assert ids == [
        "AMT-DETERM-0",
        "AMT-LEDGER-0",
        "AMT-FLOOR-0",
        "AMT-HUMAN0-0",
        "AMT-FEEDBACK-0",
    ]
