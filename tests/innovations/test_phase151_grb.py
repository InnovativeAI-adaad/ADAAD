# SPDX-License-Identifier: Apache-2.0
"""Phase 151 · INNOV-57 · Governed Rollback (GRB) — 30-test acceptance suite.

Covers:
  T151-GRB-01..05   Happy-path rollback execution
  T151-GRB-06..10   GRB-PREFLIGHT-0 invariant enforcement
  T151-GRB-11..15   GRB-HUMAN0-0 operator identity enforcement
  T151-GRB-16..18   GRB-TARGET-SANITY checks
  T151-GRB-19..22   GRB-LEDGER-0 / GRB-ATOMIC-0 ledger behaviour
  T151-GRB-23..25   GRB-DETERM-0 determinism
  T151-GRB-26..28   Chain integrity (verify_chain)
  T151-GRB-29..30   Registry wrapper / metadata
"""
from __future__ import annotations

import pytest

from dorkllm.governed_rollback import (
    GRB_ATOMIC_RULE,
    GRB_DETERM_RULE,
    GRB_EVENT_TYPE,
    GRB_HUMAN0_RULE,
    GRB_LEDGER_RULE,
    GRB_PREFLIGHT_RULE,
    GRB_VERSION,
    INVARIANT_IDS,
    GovernedRollbackEngine,
    InvariantCheckResult,
    PhaseStateSnapshot,
    RollbackResult,
    RollbackStatus,
    _compute_entry_digest,
    _compute_state_delta,
    build_rollback_engine,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CURRENT = PhaseStateSnapshot(
    phase=150,
    version="9.83.0",
    hard_class_count=268,
    innovations_shipped=56,
    invariant_ids=frozenset(["GCB-CHAIN-0", "GRB-PREFLIGHT-0"]),
)

TARGET_VALID = PhaseStateSnapshot(
    phase=144,
    version="9.75.0",
    hard_class_count=231,
    innovations_shipped=48,
    invariant_ids=frozenset(["CSS-DETERM-0"]),
)


def _engine(
    invariant_registry: dict | None = None,
    ledger: list | None = None,
) -> GovernedRollbackEngine:
    return GovernedRollbackEngine(
        current_snapshot=CURRENT,
        ledger_entries=ledger if ledger is not None else [],
        invariant_registry=invariant_registry or {},
    )


# ---------------------------------------------------------------------------
# T151-GRB-01..05  Happy-path rollback execution
# ---------------------------------------------------------------------------

def test_T151_GRB_01_success_status() -> None:
    """Valid rollback → RollbackStatus.SUCCESS."""
    engine = _engine()
    result = engine.execute(TARGET_VALID, operator="HUMAN-0/Dustin")
    assert result.status == RollbackStatus.SUCCESS


def test_T151_GRB_02_ledger_entry_written() -> None:
    """Successful rollback writes exactly one ledger entry."""
    ledger: list = []
    engine = _engine(ledger=ledger)
    engine.execute(TARGET_VALID, operator="HUMAN-0/Dustin")
    assert len(ledger) == 1


def test_T151_GRB_03_ledger_entry_fields() -> None:
    """Ledger entry records source/target phase, operator, event_type."""
    ledger: list = []
    engine = _engine(ledger=ledger)
    engine.execute(TARGET_VALID, operator="HUMAN-0/Dustin")
    entry = ledger[0]
    assert entry["event_type"] == GRB_EVENT_TYPE
    assert entry["source_phase"] == CURRENT.phase
    assert entry["target_phase"] == TARGET_VALID.phase
    assert entry["operator"] == "HUMAN-0/Dustin"


def test_T151_GRB_04_state_delta_non_empty() -> None:
    """State delta contains all changed fields."""
    engine = _engine()
    result = engine.execute(TARGET_VALID, operator="HUMAN-0/Dustin")
    delta = result.state_delta
    assert "phase" in delta
    assert "version" in delta
    assert delta["phase"]["before"] == CURRENT.phase
    assert delta["phase"]["after"] == TARGET_VALID.phase


def test_T151_GRB_05_preflight_included_in_result() -> None:
    """Successful result carries a preflight report with passed=True."""
    engine = _engine()
    result = engine.execute(TARGET_VALID, operator="HUMAN-0/Dustin")
    assert result.preflight is not None
    assert result.preflight.passed is True


# ---------------------------------------------------------------------------
# T151-GRB-06..10  GRB-PREFLIGHT-0 invariant enforcement
# ---------------------------------------------------------------------------

def test_T151_GRB_06_custom_invariant_pass() -> None:
    """Rollback succeeds when custom invariant passes for target state."""
    registry = {"CUSTOM-INV-0": lambda snap: snap.hard_class_count >= 100}
    engine = _engine(invariant_registry=registry)
    result = engine.execute(TARGET_VALID, operator="HUMAN-0/Dustin")
    assert result.status == RollbackStatus.SUCCESS


def test_T151_GRB_07_custom_invariant_fail_blocks_rollback() -> None:
    """Rollback blocked when custom invariant fails for target state."""
    registry = {"CUSTOM-INV-0": lambda snap: snap.hard_class_count >= 300}
    engine = _engine(invariant_registry=registry)
    result = engine.execute(TARGET_VALID, operator="HUMAN-0/Dustin")
    assert result.status == RollbackStatus.PREFLIGHT_FAILED


def test_T151_GRB_08_preflight_failure_no_ledger_write() -> None:
    """Preflight failure must not write to ledger (GRB-ATOMIC-0)."""
    ledger: list = []
    registry = {"INV-BLOCK-0": lambda _: False}
    engine = _engine(invariant_registry=registry, ledger=ledger)
    engine.execute(TARGET_VALID, operator="HUMAN-0/Dustin")
    assert len(ledger) == 0


def test_T151_GRB_09_preflight_report_lists_failed_invariants() -> None:
    """Preflight report enumerates which invariants failed."""
    registry = {"FAIL-INV-0": lambda _: False, "PASS-INV-0": lambda _: True}
    engine = _engine(invariant_registry=registry)
    result = engine.execute(TARGET_VALID, operator="HUMAN-0/Dustin")
    failed_ids = {c.invariant_id for c in result.preflight.failed_invariants}
    assert "FAIL-INV-0" in failed_ids
    assert "PASS-INV-0" not in failed_ids


def test_T151_GRB_10_invariant_exception_treated_as_fail() -> None:
    """Invariant checker that raises is treated as a failure (safe-fail)."""
    def boom(_snap: PhaseStateSnapshot) -> bool:
        raise RuntimeError("unexpected")

    registry = {"EXCEPTION-INV-0": boom}
    engine = _engine(invariant_registry=registry)
    result = engine.execute(TARGET_VALID, operator="HUMAN-0/Dustin")
    assert result.status == RollbackStatus.PREFLIGHT_FAILED


# ---------------------------------------------------------------------------
# T151-GRB-11..15  GRB-HUMAN0-0 operator identity enforcement
# ---------------------------------------------------------------------------

def test_T151_GRB_11_empty_operator_rejected() -> None:
    """Empty string operator violates GRB-HUMAN0-0."""
    engine = _engine()
    result = engine.execute(TARGET_VALID, operator="")
    assert result.status == RollbackStatus.REJECTED_OPERATOR


def test_T151_GRB_12_none_operator_rejected() -> None:
    """None operator violates GRB-HUMAN0-0."""
    engine = _engine()
    result = engine.execute(TARGET_VALID, operator=None)  # type: ignore[arg-type]
    assert result.status == RollbackStatus.REJECTED_OPERATOR


def test_T151_GRB_13_whitespace_only_operator_rejected() -> None:
    """Whitespace-only operator violates GRB-HUMAN0-0."""
    engine = _engine()
    result = engine.execute(TARGET_VALID, operator="   ")
    assert result.status == RollbackStatus.REJECTED_OPERATOR


def test_T151_GRB_14_operator_rejection_no_ledger_write() -> None:
    """HUMAN0-0 rejection must not write to ledger."""
    ledger: list = []
    engine = _engine(ledger=ledger)
    engine.execute(TARGET_VALID, operator="")
    assert len(ledger) == 0


def test_T151_GRB_15_valid_operator_passes() -> None:
    """Non-empty operator passes GRB-HUMAN0-0."""
    engine = _engine()
    result = engine.execute(TARGET_VALID, operator="DEVADAAD")
    assert result.status == RollbackStatus.SUCCESS


# ---------------------------------------------------------------------------
# T151-GRB-16..18  GRB-TARGET-SANITY
# ---------------------------------------------------------------------------

def test_T151_GRB_16_target_same_as_source_rejected() -> None:
    """Target phase == source phase is rejected."""
    same = PhaseStateSnapshot(phase=CURRENT.phase, version="9.83.0", hard_class_count=268, innovations_shipped=56)
    engine = _engine()
    result = engine.execute(same, operator="HUMAN-0/Dustin")
    assert result.status in (RollbackStatus.REJECTED_TARGET, RollbackStatus.PREFLIGHT_FAILED)


def test_T151_GRB_17_future_target_rejected() -> None:
    """Target phase > source phase is rejected."""
    future = PhaseStateSnapshot(phase=200, version="9.99.0", hard_class_count=400, innovations_shipped=80)
    engine = _engine()
    result = engine.execute(future, operator="HUMAN-0/Dustin")
    assert result.status in (RollbackStatus.REJECTED_TARGET, RollbackStatus.PREFLIGHT_FAILED)


def test_T151_GRB_18_zero_phase_target_rejected() -> None:
    """Target phase == 0 is rejected."""
    zero = PhaseStateSnapshot(phase=0, version="0.0.0", hard_class_count=0, innovations_shipped=0)
    engine = _engine()
    result = engine.execute(zero, operator="HUMAN-0/Dustin")
    assert result.status in (RollbackStatus.REJECTED_TARGET, RollbackStatus.PREFLIGHT_FAILED)


# ---------------------------------------------------------------------------
# T151-GRB-19..22  GRB-LEDGER-0 / GRB-ATOMIC-0 ledger behaviour
# ---------------------------------------------------------------------------

def test_T151_GRB_19_ledger_entry_has_chain_digest() -> None:
    """Ledger entry has a non-empty chain_digest (GRB-LEDGER-0)."""
    ledger: list = []
    engine = _engine(ledger=ledger)
    engine.execute(TARGET_VALID, operator="HUMAN-0/Dustin")
    assert "chain_digest" in ledger[0]
    assert len(ledger[0]["chain_digest"]) == 64  # SHA-256 hex


def test_T151_GRB_20_multiple_rollbacks_accumulate_ledger() -> None:
    """Multiple rollbacks accumulate distinct ledger entries."""
    ledger: list = []
    engine = _engine(ledger=ledger)
    engine.execute(TARGET_VALID, operator="HUMAN-0/Dustin")
    target2 = PhaseStateSnapshot(phase=140, version="9.70.0", hard_class_count=220, innovations_shipped=46)
    engine.execute(target2, operator="HUMAN-0/Dustin")
    assert len(ledger) == 2
    assert ledger[0]["target_phase"] != ledger[1]["target_phase"]


def test_T151_GRB_21_ledger_snapshot_is_copy() -> None:
    """ledger_snapshot() returns a copy, not the internal list."""
    ledger: list = []
    engine = _engine(ledger=ledger)
    engine.execute(TARGET_VALID, operator="HUMAN-0/Dustin")
    snap = engine.ledger_snapshot()
    snap.clear()
    assert len(engine.ledger_snapshot()) == 1  # internal list unchanged


def test_T151_GRB_22_ledger_entry_preflight_passed_flag() -> None:
    """Ledger entry records preflight_passed=True on success."""
    ledger: list = []
    engine = _engine(ledger=ledger)
    engine.execute(TARGET_VALID, operator="HUMAN-0/Dustin")
    assert ledger[0]["preflight_passed"] is True


# ---------------------------------------------------------------------------
# T151-GRB-23..25  GRB-DETERM-0 determinism
# ---------------------------------------------------------------------------

def test_T151_GRB_23_digest_is_deterministic() -> None:
    """Same inputs always produce the same entry_digest (GRB-DETERM-0)."""
    d1 = _compute_entry_digest(GRB_EVENT_TYPE, 150, 144, "HUMAN-0/Dustin", 1)
    d2 = _compute_entry_digest(GRB_EVENT_TYPE, 150, 144, "HUMAN-0/Dustin", 1)
    assert d1 == d2


def test_T151_GRB_24_different_targets_produce_different_digests() -> None:
    """Different target phases produce different digests."""
    d1 = _compute_entry_digest(GRB_EVENT_TYPE, 150, 144, "op", 1)
    d2 = _compute_entry_digest(GRB_EVENT_TYPE, 150, 140, "op", 1)
    assert d1 != d2


def test_T151_GRB_25_state_delta_is_deterministic() -> None:
    """State delta is deterministic for the same snapshot pair."""
    delta1 = _compute_state_delta(CURRENT, TARGET_VALID)
    delta2 = _compute_state_delta(CURRENT, TARGET_VALID)
    assert delta1 == delta2


# ---------------------------------------------------------------------------
# T151-GRB-26..28  verify_chain
# ---------------------------------------------------------------------------

def test_T151_GRB_26_empty_ledger_chain_valid() -> None:
    """Empty ledger passes chain verification."""
    engine = _engine()
    assert engine.verify_chain() is True


def test_T151_GRB_27_single_entry_chain_valid() -> None:
    """Single rollback ledger is chain-valid."""
    engine = _engine()
    engine.execute(TARGET_VALID, operator="HUMAN-0/Dustin")
    assert engine.verify_chain() is True


def test_T151_GRB_28_tampered_entry_chain_invalid() -> None:
    """Tampered chain_digest causes verify_chain() to return False."""
    ledger: list = []
    engine = _engine(ledger=ledger)
    engine.execute(TARGET_VALID, operator="HUMAN-0/Dustin")
    ledger[0]["chain_digest"] = "deadbeef" * 8  # tamper
    assert engine.verify_chain() is False


# ---------------------------------------------------------------------------
# T151-GRB-29..30  Registry wrapper / metadata
# ---------------------------------------------------------------------------

def test_T151_GRB_29_registry_wrapper_imports() -> None:
    """Registry wrapper exports all required symbols."""
    from runtime.innovations30.governed_rollback import (
        INNOVATION_ID,
        INNOVATION_NAME,
        PHASE,
        VERSION,
        HARD_CLASS_INVARIANTS,
        build_rollback_engine,
    )
    assert INNOVATION_ID == "INNOV-57"
    assert INNOVATION_NAME == "Governed Rollback (GRB)"
    assert PHASE == 151
    assert VERSION == "9.84.0"
    assert len(HARD_CLASS_INVARIANTS) == 5


def test_T151_GRB_30_invariant_ids_complete() -> None:
    """INVARIANT_IDS tuple contains all five GRB invariants."""
    expected = {
        "GRB-PREFLIGHT-0",
        "GRB-LEDGER-0",
        "GRB-ATOMIC-0",
        "GRB-DETERM-0",
        "GRB-HUMAN0-0",
    }
    assert expected == set(INVARIANT_IDS)
