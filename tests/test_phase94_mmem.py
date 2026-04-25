# SPDX-License-Identifier: Apache-2.0
"""
Phase 94 — INNOV-10 Morphogenetic Memory (MMEM)
Test suite: T94-MMEM-01..33  (33 tests)

Invariants under test:
  MMEM-0         — check() never raises; fallback path returns consistent=False
  MMEM-CHAIN-0   — hash chain is intact; discontinuity raises ChainIntegrityError
  MMEM-READONLY-0 — check() has no side effects on ledger state
  MMEM-WIRE-0    — IdentityContextInjector never blocks run_epoch
  MMEM-LEDGER-0  — append() without attestation raises IdentityAppendWithoutAttestationError
  MMEM-DETERM-0  — identical inputs → identical hash output

Migration note (2026-04-25): this suite previously used module-wide scaffold
xfail markers while Phase 94 MMEM primitives were landing. The runtime
implementation is now stable in-memory and lineage wiring, so scaffold framing
has been removed and all tests execute as strict pass/fail invariants.
"""
from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from runtime.memory.identity_ledger import (
    ZERO_HASH,
    ChainIntegrityError,
    IdentityAppendWithoutAttestationError,
    IdentityConsistencyResult,
    IdentityLedger,
    IdentityStatement,
    VALID_CATEGORIES,
)
from runtime.memory.identity_context_injector import (
    IdentityContextInjector,
    InjectionResult,
)
from runtime.lineage.lineage_ledger_v2 import (
    LineageLedgerV2,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def empty_ledger(tmp_path: Path) -> IdentityLedger:
    """IdentityLedger with no statements loaded."""
    ledger = IdentityLedger(
        ledger_path=tmp_path / "ledger.jsonl",
        genesis_seed_path=Path("artifacts/governance/phase94/identity_ledger_seed.json"),
    )
    return ledger


@pytest.fixture
def genesis_ledger(tmp_path: Path) -> IdentityLedger:
    """IdentityLedger pre-loaded from real genesis seed."""
    return IdentityLedger.load_genesis(
        genesis_seed_path=Path("artifacts/governance/phase94/identity_ledger_seed.json"),
        ledger_path=tmp_path / "ledger.jsonl",
    )


@pytest.fixture
def mock_context() -> MagicMock:
    ctx = MagicMock()
    ctx.file_path = "runtime/evolution/fitness_v2.py"
    ctx.description = "Add weight normalisation to FitnessEngineV2"
    ctx.before_source = ""
    ctx.after_source = ""
    ctx.identity_consistency_score = None
    ctx.identity_violated_statements = []
    return ctx


# ---------------------------------------------------------------------------
# T94-MMEM-01..05  IdentityStatement construction + MMEM-DETERM-0
# ---------------------------------------------------------------------------


def test_T94_MMEM_01_statement_hash_deterministic() -> None:
    """MMEM-DETERM-0: identical fields → identical hash."""
    s1 = IdentityStatement(
        statement_id="IS-001",
        category="purpose",
        statement="ADAAD exists to be governable.",
        author="test",
        epoch_id="v9.27.0",
        predecessor_hash=ZERO_HASH,
    )
    s2 = IdentityStatement(
        statement_id="IS-001",
        category="purpose",
        statement="ADAAD exists to be governable.",
        author="test",
        epoch_id="v9.27.0",
        predecessor_hash=ZERO_HASH,
    )
    assert s1.statement_hash == s2.statement_hash


def test_T94_MMEM_02_statement_hash_not_empty() -> None:
    """Statement hash must be populated after init."""
    s = IdentityStatement(
        statement_id="IS-001",
        category="purpose",
        statement="test statement",
        author="test",
        epoch_id="e1",
        predecessor_hash=ZERO_HASH,
    )
    assert s.statement_hash != ""
    assert s.statement_hash.startswith("sha256:")


def test_T94_MMEM_03_statement_hash_changes_with_content() -> None:
    """Different statement text → different hash (MMEM-DETERM-0)."""
    s1 = IdentityStatement("IS-001", "purpose", "statement A", "test", "e1", ZERO_HASH)
    s2 = IdentityStatement("IS-001", "purpose", "statement B", "test", "e1", ZERO_HASH)
    assert s1.statement_hash != s2.statement_hash


def test_T94_MMEM_04_statement_hash_changes_with_predecessor() -> None:
    """Different predecessor → different hash (MMEM-DETERM-0)."""
    hash_a = "sha256:" + "a" * 64
    hash_b = "sha256:" + "b" * 64
    s1 = IdentityStatement("IS-001", "purpose", "same", "test", "e1", hash_a)
    s2 = IdentityStatement("IS-001", "purpose", "same", "test", "e1", hash_b)
    assert s1.statement_hash != s2.statement_hash


def test_T94_MMEM_05_valid_categories_accepted() -> None:
    """All VALID_CATEGORIES can be used without error."""
    for cat in VALID_CATEGORIES:
        s = IdentityStatement("IS-001", cat, "stmt", "test", "e1", ZERO_HASH)
        assert s.category == cat


# ---------------------------------------------------------------------------
# T94-MMEM-06..10  IdentityLedger genesis loading
# ---------------------------------------------------------------------------


def test_T94_MMEM_06_load_genesis_returns_ledger(tmp_path: Path) -> None:
    """load_genesis() returns a non-empty IdentityLedger."""
    ledger = IdentityLedger.load_genesis(
        genesis_seed_path=Path("artifacts/governance/phase94/identity_ledger_seed.json"),
        ledger_path=tmp_path / "ledger.jsonl",
    )
    assert isinstance(ledger, IdentityLedger)
    assert len(ledger) > 0


def test_T94_MMEM_07_genesis_loads_8_statements(genesis_ledger: IdentityLedger) -> None:
    """Genesis seed contains exactly 8 IdentityStatements."""
    assert len(genesis_ledger) == 8


def test_T94_MMEM_08_genesis_statement_ids(genesis_ledger: IdentityLedger) -> None:
    """Genesis statements have IDs IS-001..IS-008."""
    ids = {s.statement_id for s in genesis_ledger.statements()}
    assert ids == {f"IS-{i:03d}" for i in range(1, 9)}


def test_T94_MMEM_09_genesis_chain_intact(genesis_ledger: IdentityLedger) -> None:
    """verify_chain() returns True for freshly-loaded genesis (MMEM-CHAIN-0)."""
    assert genesis_ledger.verify_chain() is True


def test_T94_MMEM_10_genesis_first_predecessor_is_zero_hash(
    genesis_ledger: IdentityLedger,
) -> None:
    """First statement has ZERO_HASH as predecessor (MMEM-CHAIN-0)."""
    first = genesis_ledger.statements()[0]
    assert first.predecessor_hash == ZERO_HASH


# ---------------------------------------------------------------------------
# T94-MMEM-11..16  check() — MMEM-0 (never raises) + MMEM-READONLY-0
# ---------------------------------------------------------------------------


def test_T94_MMEM_11_check_never_raises_on_empty_ledger(
    empty_ledger: IdentityLedger,
) -> None:
    """MMEM-0: check() on empty ledger returns result, does not raise."""
    result = empty_ledger.check("mut-001", "some intent")
    assert isinstance(result, IdentityConsistencyResult)


def test_T94_MMEM_12_check_returns_consistency_result(
    genesis_ledger: IdentityLedger,
) -> None:
    """check() returns IdentityConsistencyResult with required fields."""
    result = genesis_ledger.check("mut-001", "add logging to fitness engine")
    assert hasattr(result, "consistent")
    assert hasattr(result, "consistency_score")
    assert hasattr(result, "violated_statements")
    assert 0.0 <= result.consistency_score <= 1.0


def test_T94_MMEM_13_check_score_bounded(genesis_ledger: IdentityLedger) -> None:
    """MMEM-0: consistency_score always in [0.0, 1.0]."""
    result = genesis_ledger.check("mut-002", "bypass governance gate entirely")
    assert 0.0 <= result.consistency_score <= 1.0


def test_T94_MMEM_14_check_does_not_modify_ledger(
    genesis_ledger: IdentityLedger,
) -> None:
    """MMEM-READONLY-0: check() does not change ledger state."""
    count_before = len(genesis_ledger)
    genesis_ledger.check("mut-003", "refactor weight adaptor")
    assert len(genesis_ledger) == count_before


def test_T94_MMEM_15_check_violation_detected(genesis_ledger: IdentityLedger) -> None:
    """Intent contradicting IS-003 (human authority) should flag violation."""
    result = genesis_ledger.check(
        "mut-bypass",
        "remove HUMAN-0 gate and allow autonomous release promotion",
    )
    assert not result.consistent or len(result.violated_statements) > 0


def test_T94_MMEM_16_check_fallback_on_corrupt_state(tmp_path: Path) -> None:
    """MMEM-0: check() returns fallback result if internal error occurs."""
    ledger = IdentityLedger(ledger_path=tmp_path / "l.jsonl")
    # Force internal state corruption
    ledger._statements = None  # type: ignore[assignment]
    result = ledger.check("mut-err", "test")
    assert isinstance(result, IdentityConsistencyResult)
    assert result.fallback_used is True


# ---------------------------------------------------------------------------
# T94-MMEM-17..20  append() — MMEM-LEDGER-0
# ---------------------------------------------------------------------------


def test_T94_MMEM_17_append_without_token_raises(
    genesis_ledger: IdentityLedger,
) -> None:
    """MMEM-LEDGER-0: append() with empty token raises IdentityAppendWithoutAttestationError."""
    with pytest.raises(IdentityAppendWithoutAttestationError):
        genesis_ledger.append(
            category="purpose",
            statement="New statement",
            author="test",
            epoch_id="v9.27.0",
            attestation_token="",
        )


def test_T94_MMEM_18_append_with_valid_token_succeeds(
    genesis_ledger: IdentityLedger,
) -> None:
    """append() with valid token adds a statement and extends chain."""
    count_before = len(genesis_ledger)
    stmt = genesis_ledger.append(
        category="value",
        statement="Transparency is non-negotiable.",
        author="Dustin L. Reid",
        epoch_id="v9.27.0",
        attestation_token="phase94-human0-ratified",
    )
    assert isinstance(stmt, IdentityStatement)
    assert len(genesis_ledger) == count_before + 1


def test_T94_MMEM_19_append_links_predecessor(genesis_ledger: IdentityLedger) -> None:
    """New statement's predecessor_hash equals prior terminal hash (MMEM-CHAIN-0)."""
    prior_last = genesis_ledger.statements()[-1].statement_hash
    stmt = genesis_ledger.append(
        category="capability",
        statement="Mutation is governed.",
        author="Dustin L. Reid",
        epoch_id="v9.27.0",
        attestation_token="phase94-human0-ratified",
    )
    assert stmt.predecessor_hash == prior_last


def test_T94_MMEM_20_append_chain_still_valid_after_append(
    genesis_ledger: IdentityLedger,
) -> None:
    """verify_chain() returns True after valid append (MMEM-CHAIN-0)."""
    genesis_ledger.append(
        category="value",
        statement="Audit trails survive external review.",
        author="Dustin L. Reid",
        epoch_id="v9.27.0",
        attestation_token="phase94-human0-ratified",
    )
    assert genesis_ledger.verify_chain() is True


# ---------------------------------------------------------------------------
# T94-MMEM-21..24  verify_chain() — MMEM-CHAIN-0
# ---------------------------------------------------------------------------


def test_T94_MMEM_21_verify_chain_passes_genesis(genesis_ledger: IdentityLedger) -> None:
    """Clean genesis ledger passes verify_chain() (MMEM-CHAIN-0)."""
    assert genesis_ledger.verify_chain() is True


def test_T94_MMEM_22_verify_chain_detects_tamper(genesis_ledger: IdentityLedger) -> None:
    """Tampered predecessor_hash raises ChainIntegrityError (MMEM-CHAIN-0)."""
    stmts = genesis_ledger.statements()
    # Tamper in-place
    stmts[2].predecessor_hash = "sha256:" + "f" * 64
    genesis_ledger._statements = stmts  # type: ignore[assignment]
    with pytest.raises(ChainIntegrityError):
        genesis_ledger.verify_chain()


def test_T94_MMEM_23_verify_chain_detects_hash_mutation(
    genesis_ledger: IdentityLedger,
) -> None:
    """Mutated statement_hash raises ChainIntegrityError (MMEM-CHAIN-0)."""
    stmts = genesis_ledger.statements()
    stmts[0].statement_hash = "sha256:" + "0" * 63 + "1"
    genesis_ledger._statements = stmts  # type: ignore[assignment]
    with pytest.raises(ChainIntegrityError):
        genesis_ledger.verify_chain()


def test_T94_MMEM_24_empty_ledger_verify_chain_passes(
    empty_ledger: IdentityLedger,
) -> None:
    """Empty ledger is trivially valid chain (MMEM-CHAIN-0)."""
    assert empty_ledger.verify_chain() is True


# ---------------------------------------------------------------------------
# T94-MMEM-25..28  IdentityContextInjector — MMEM-WIRE-0
# ---------------------------------------------------------------------------


def test_T94_MMEM_25_injector_returns_result(
    genesis_ledger: IdentityLedger, mock_context: MagicMock
) -> None:
    """inject() returns InjectionResult (MMEM-WIRE-0)."""
    injector = IdentityContextInjector(genesis_ledger)
    result = injector.inject(mock_context, epoch_id="v9.27.0", mutation_id="mut-001")
    assert isinstance(result, InjectionResult)


def test_T94_MMEM_26_injector_sets_context_score(
    genesis_ledger: IdentityLedger, mock_context: MagicMock
) -> None:
    """inject() sets identity_consistency_score on context (MMEM-WIRE-0)."""
    injector = IdentityContextInjector(genesis_ledger)
    injector.inject(mock_context, epoch_id="v9.27.0")
    assert mock_context.identity_consistency_score is not None
    assert 0.0 <= mock_context.identity_consistency_score <= 1.0


def test_T94_MMEM_27_injector_never_raises_on_bad_ledger(
    mock_context: MagicMock,
) -> None:
    """MMEM-WIRE-0: inject() degrades gracefully if ledger is broken."""
    bad_ledger = MagicMock()
    bad_ledger.check.side_effect = RuntimeError("ledger exploded")
    injector = IdentityContextInjector(bad_ledger)
    result = injector.inject(mock_context, epoch_id="v9.27.0")
    assert isinstance(result, InjectionResult)
    assert result.fallback_used is True


def test_T94_MMEM_28_injector_idempotent(
    genesis_ledger: IdentityLedger, mock_context: MagicMock
) -> None:
    """Calling inject() twice is safe and idempotent (MMEM-WIRE-0)."""
    injector = IdentityContextInjector(genesis_ledger)
    r1 = injector.inject(mock_context, epoch_id="v9.27.0", mutation_id="m1")
    r2 = injector.inject(mock_context, epoch_id="v9.27.0", mutation_id="m1")
    assert r1.consistency_score == r2.consistency_score


# ---------------------------------------------------------------------------
# T94-MMEM-29..31  LineageLedgerV2 — MMEM Phase 94 enrichment
# ---------------------------------------------------------------------------


def test_T94_MMEM_29_lineage_attach_identity_result(tmp_path: Path) -> None:
    """attach_identity_result() writes MMEM signal to existing event."""
    ledger = LineageLedgerV2(ledger_path=tmp_path / "ll.jsonl")
    event = ledger.record_proposal(
        mutation_id="mut-001",
        epoch_id="v9.27.0",
        payload={"description": "test"},
    )
    ledger.attach_identity_result(
        event_id=event.event_id,
        consistency_score=0.85,
        violated_statements=[],
    )
    events = ledger.events()
    matching = [e for e in events if e.event_id == event.event_id]
    assert matching[0].identity_consistency_score == 0.85


def test_T94_MMEM_30_lineage_verify_chain_after_attach(tmp_path: Path) -> None:
    """verify_chain() passes after attach_identity_result() (MMEM-CHAIN-0 via lineage)."""
    ledger = LineageLedgerV2(ledger_path=tmp_path / "ll.jsonl")
    event = ledger.record_proposal("mut-002", "v9.27.0", {})
    ledger.attach_identity_result(event.event_id, 0.9, [])
    assert ledger.verify_chain() is True


def test_T94_MMEM_31_lineage_semantic_proximity_score(tmp_path: Path) -> None:
    """semantic_proximity_score() returns ProximityScore in [0,1]."""
    from runtime.lineage.lineage_ledger_v2 import ProximityScore
    ledger = LineageLedgerV2(ledger_path=tmp_path / "ll.jsonl")
    result = ledger.semantic_proximity_score("def foo(): pass")
    assert isinstance(result, ProximityScore)
    assert 0.0 <= result.score <= 1.0


# ---------------------------------------------------------------------------
# T94-MMEM-32..33  Integration — MMEM-WIRE-0 evolution loop contract
# ---------------------------------------------------------------------------


def test_T94_MMEM_32_evolution_loop_has_identity_injector_slot() -> None:
    """EvolutionLoop contains MMEM identity injector initialization and call sites."""
    from runtime.evolution.evolution_loop import EvolutionLoop

    source = inspect.getsource(EvolutionLoop)
    assert "self._identity_injector = None" in source
    assert "if self._identity_injector is not None:" in source
    assert "_mmem_result = self._identity_injector.inject(" in source


def test_T94_MMEM_33_import_contracts() -> None:
    """All MMEM public symbols importable from expected module paths."""
    from runtime.memory.identity_ledger import (  # noqa: F401
        IdentityLedger,
        IdentityStatement,
        IdentityConsistencyResult,
        ChainIntegrityError,
        IdentityAppendWithoutAttestationError,
        ZERO_HASH,
    )
    from runtime.memory.identity_context_injector import (  # noqa: F401
        IdentityContextInjector,
        InjectionResult,
    )
    from runtime.lineage.lineage_ledger_v2 import (  # noqa: F401
        LineageLedgerV2,
        LineageEvent,
    )
    assert True
