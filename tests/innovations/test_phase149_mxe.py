# SPDX-License-Identifier: Apache-2.0
"""Phase 149 / INNOV-55 — Mutation Explainability Engine (MXE) acceptance tests.

30 tests covering:
  - MutationExplanation determinism (MXE-DETERM-0)
  - HMAC chain integrity (MXE-CHAIN-0)
  - Immutability enforcement (MXE-IMMUT-0)
  - Scope restriction (MXE-SCOPE-0)
  - Audit persistence guarantee (MXE-AUDIT-0)
  - MXEExplainer engine behaviour
  - INNOV-55 registry wrapper
  - MCP server route presence
"""

from __future__ import annotations

import hashlib
import hmac as hmac_lib
import json
import os
import tempfile
from pathlib import Path

import pytest

from runtime.mcp.mutation_explainability import (
    MXEAuditViolation,
    MXEChainState,
    MXEChainViolation,
    MXEExplainer,
    MXEMutabilityViolation,
    MXEScopeViolation,
    MutationExplanation,
    InvariantFinding,
    ReasoningStep,
    VALID_VERDICTS,
    explain_mutation,
    get_explainer,
)
from runtime.innovations30.mutation_explainability import (
    INNOV_ID,
    INVARIANTS,
    INNOV_PHASE,
    probe,
    registry_entry,
)

_HMAC_KEY = os.getenv("ADAAD_MXE_HMAC_KEY", "adaad-mxe-dev-secret-do-not-use-in-prod").encode()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tmp_ledger() -> Path:
    d = Path(tempfile.mkdtemp())
    return d / "test.mxe.jsonl"


def _engine() -> MXEExplainer:
    return MXEExplainer(ledger_path=_tmp_ledger())


def _expl(
    verdict: str = "ACCEPT",
    mutation_id: str = "mut-001",
    prev_hmac: str = "",
) -> MutationExplanation:
    return MutationExplanation(
        explanation_id="EXP-001",
        mutation_id=mutation_id,
        verdict=verdict,
        confidence=0.95,
        summary="test explanation",
        prev_hmac=prev_hmac,
    )


# ===========================================================================
# Group 1: MutationExplanation — MXE-DETERM-0
# ===========================================================================


@pytest.mark.T149
def test_mxe01_canonical_dict_keys_sorted():
    """MXE-DETERM-0: canonical dict keys are sorted."""
    expl = _expl()
    d = expl._canonical_dict()
    assert list(d.keys()) == sorted(d.keys())


@pytest.mark.T149
def test_mxe02_to_json_stable():
    """MXE-DETERM-0: two calls to to_json() produce identical strings."""
    expl = _expl()
    assert expl.to_json() == expl.to_json()


@pytest.mark.T149
def test_mxe03_confidence_rounded():
    """MXE-DETERM-0: confidence is rounded to 6 decimal places."""
    expl = MutationExplanation("EXP-001", "mut-001", "ACCEPT", 0.999999999, "test", prev_hmac="")
    assert expl.confidence == round(0.999999999, 6)


@pytest.mark.T149
def test_mxe04_hmac_computed_on_init():
    """MXE-CHAIN-0: explanation_hmac is 64-char hex after init."""
    expl = _expl()
    assert len(expl.explanation_hmac) == 64


@pytest.mark.T149
def test_mxe05_hmac_deterministic():
    """MXE-CHAIN-0: same inputs produce same hmac."""
    ts = "2026-04-22T00:00:00+00:00"
    e1 = MutationExplanation("EXP-001", "mut-001", "ACCEPT", 0.9, "s", timestamp_iso=ts, prev_hmac="")
    e2 = MutationExplanation("EXP-001", "mut-001", "ACCEPT", 0.9, "s", timestamp_iso=ts, prev_hmac="")
    assert e1.explanation_hmac == e2.explanation_hmac


@pytest.mark.T149
def test_mxe06_roundtrip_from_dict():
    """MXE-DETERM-0: from_dict preserves all fields."""
    expl = _expl(verdict="REJECT", mutation_id="mut-xyz")
    d = expl.to_dict()
    restored = MutationExplanation.from_dict(d)
    assert restored.verdict == expl.verdict
    assert restored.mutation_id == expl.mutation_id
    assert restored.explanation_hmac == expl.explanation_hmac


@pytest.mark.T149
def test_mxe07_different_summaries_produce_different_hmacs():
    """MXE-DETERM-0: mutation in summary changes hmac."""
    ts = "2026-04-22T00:00:00+00:00"
    e1 = MutationExplanation("EXP-001", "mut-001", "ACCEPT", 0.9, "summary_a", timestamp_iso=ts, prev_hmac="")
    e2 = MutationExplanation("EXP-001", "mut-001", "ACCEPT", 0.9, "summary_b", timestamp_iso=ts, prev_hmac="")
    assert e1.explanation_hmac != e2.explanation_hmac


# ===========================================================================
# Group 2: Scope — MXE-SCOPE-0
# ===========================================================================


@pytest.mark.T149
def test_mxe08_invalid_verdict_raises_scope_violation():
    """MXE-SCOPE-0: invalid verdict raises MXEScopeViolation."""
    with pytest.raises(MXEScopeViolation):
        MutationExplanation("EXP-001", "mut-001", "UNKNOWN_VERDICT", 0.9, "test", prev_hmac="")


@pytest.mark.T149
def test_mxe09_valid_verdicts_accepted():
    """MXE-SCOPE-0: ACCEPT, REJECT, BLOCK all accepted."""
    for v in VALID_VERDICTS:
        expl = MutationExplanation("EXP-001", "mut-001", v, 0.9, "test", prev_hmac="")
        assert expl.verdict == v


@pytest.mark.T149
def test_mxe10_valid_verdicts_frozenset():
    """MXE-SCOPE-0: VALID_VERDICTS contains exactly ACCEPT, REJECT, BLOCK."""
    assert VALID_VERDICTS == frozenset({"ACCEPT", "REJECT", "BLOCK"})


# ===========================================================================
# Group 3: Chain — MXE-CHAIN-0
# ===========================================================================


@pytest.mark.T149
def test_mxe11_chain_starts_empty():
    """MXE-CHAIN-0: initial tail is empty string."""
    cs = MXEChainState()
    assert cs.tail == ""


@pytest.mark.T149
def test_mxe12_chain_advance_updates_tail():
    """MXE-CHAIN-0: advance moves tail to explanation_hmac."""
    cs = MXEChainState()
    expl = _expl(prev_hmac="")
    cs.advance(expl)
    assert cs.tail == expl.explanation_hmac


@pytest.mark.T149
def test_mxe13_chain_broken_raises():
    """MXE-CHAIN-0: mismatched prev_hmac raises MXEChainViolation."""
    cs = MXEChainState()
    expl = _expl(prev_hmac="wrong_hmac")
    with pytest.raises(MXEChainViolation):
        cs.advance(expl)


@pytest.mark.T149
def test_mxe14_chain_sequential_valid():
    """MXE-CHAIN-0: sequential explanations chain correctly."""
    cs = MXEChainState()
    e1 = _expl(mutation_id="mut-001", prev_hmac="")
    cs.advance(e1)
    e2 = _expl(mutation_id="mut-002", prev_hmac=e1.explanation_hmac)
    cs.advance(e2)
    assert cs.tail == e2.explanation_hmac


@pytest.mark.T149
def test_mxe15_chain_reset():
    """MXE-CHAIN-0: reset returns tail to empty."""
    cs = MXEChainState()
    expl = _expl(prev_hmac="")
    cs.advance(expl)
    cs.reset()
    assert cs.tail == ""


# ===========================================================================
# Group 4: Immutability — MXE-IMMUT-0
# ===========================================================================


@pytest.mark.T149
def test_mxe16_explain_idempotent():
    """MXE-IMMUT-0: second explain() call for same mutation_id returns same object."""
    engine = _engine()
    e1 = engine.explain("mut-abc", "ACCEPT")
    e2 = engine.explain("mut-abc", "REJECT")  # verdict ignored — idempotent
    assert e1.explanation_hmac == e2.explanation_hmac
    assert e2.verdict == "ACCEPT"


@pytest.mark.T149
def test_mxe17_get_returns_stored():
    """MXE-IMMUT-0: get() returns previously stored explanation."""
    engine = _engine()
    engine.explain("mut-stored", "BLOCK")
    expl = engine.get("mut-stored")
    assert expl is not None
    assert expl.verdict == "BLOCK"


@pytest.mark.T149
def test_mxe18_get_unknown_returns_none():
    """MXE-IMMUT-0: get() returns None for unknown mutation_id."""
    engine = _engine()
    assert engine.get("nonexistent-mut") is None


# ===========================================================================
# Group 5: Audit persistence — MXE-AUDIT-0
# ===========================================================================


@pytest.mark.T149
def test_mxe19_explain_writes_ledger():
    """MXE-AUDIT-0: explain() persists to ledger before returning."""
    engine = _engine()
    engine.explain("mut-audit", "ACCEPT")
    assert engine._ledger_path.exists()
    lines = engine._ledger_path.read_text().strip().splitlines()
    assert len(lines) == 1


@pytest.mark.T149
def test_mxe20_ledger_append_only():
    """MXE-AUDIT-0: each explanation appends a new JSONL line."""
    engine = _engine()
    engine.explain("mut-001", "ACCEPT")
    engine.explain("mut-002", "REJECT")
    engine.explain("mut-003", "BLOCK")
    lines = engine._ledger_path.read_text().strip().splitlines()
    assert len(lines) == 3


@pytest.mark.T149
def test_mxe21_ledger_line_is_valid_json():
    """MXE-AUDIT-0: each ledger line parses as valid JSON."""
    engine = _engine()
    engine.explain("mut-json", "ACCEPT")
    for line in engine._ledger_path.read_text().strip().splitlines():
        d = json.loads(line)
        assert "explanation_hmac" in d
        assert "mutation_id" in d


# ===========================================================================
# Group 6: Engine behaviour
# ===========================================================================


@pytest.mark.T149
def test_mxe22_explain_accept_summary():
    """Engine: ACCEPT verdict produces appropriate summary."""
    engine = _engine()
    expl = engine.explain("mut-accept", "ACCEPT")
    assert "ACCEPTED" in expl.summary


@pytest.mark.T149
def test_mxe23_explain_reject_summary():
    """Engine: REJECT verdict produces appropriate summary."""
    engine = _engine()
    expl = engine.explain("mut-reject", "REJECT", gate_report={
        "fitness_threshold_gate": {"ok": False, "detail": "below threshold", "rationale": "score < 0.5"}
    })
    assert "REJECTED" in expl.summary


@pytest.mark.T149
def test_mxe24_explain_block_summary():
    """Engine: BLOCK verdict produces appropriate summary."""
    engine = _engine()
    expl = engine.explain("mut-block", "BLOCK", gate_report={
        "founders_law_invariant_gate": {"ok": False, "detail": "Hard invariant fired", "rationale": "CEL-BLOCK-0 triggered"}
    })
    assert "BLOCKED" in expl.summary


@pytest.mark.T149
def test_mxe25_explain_with_gate_report_builds_findings():
    """Engine: gate_report is parsed into InvariantFinding list."""
    engine = _engine()
    expl = engine.explain("mut-gate", "REJECT", gate_report={
        "fitness_threshold_gate": {"ok": False, "detail": "low score", "rationale": "too low"},
        "cert_reference_gate": {"ok": True, "detail": "cert present", "rationale": "valid"},
    })
    assert len(expl.invariant_findings) == 2
    fired = [f for f in expl.invariant_findings if f.fired]
    assert len(fired) == 1
    assert fired[0].invariant_id == "fitness_threshold_gate"


@pytest.mark.T149
def test_mxe26_verify_chain_no_ledger():
    """Chain verify returns ok with 0 explanations when ledger absent."""
    engine = _engine()
    result = engine.verify_chain()
    assert result["ok"] is True
    assert result["explanations"] == 0


@pytest.mark.T149
def test_mxe27_verify_chain_valid():
    """Chain verify passes after sequential explanations."""
    engine = _engine()
    engine.explain("mut-v1", "ACCEPT")
    engine.explain("mut-v2", "REJECT")
    result = engine.verify_chain()
    assert result["ok"] is True
    assert result["explanations"] == 2


@pytest.mark.T149
def test_mxe28_health_check_returns_dict():
    """health_check() returns a dict with required keys."""
    engine = _engine()
    h = engine.health_check()
    assert h["ok"] is True
    assert "explanations_stored" in h
    assert "chain_tail" in h


# ===========================================================================
# Group 7: INNOV-55 registry
# ===========================================================================


@pytest.mark.T149
def test_mxe29_registry_entry_fields():
    """INNOV-55 registry_entry() contains required fields."""
    entry = registry_entry()
    assert entry["id"] == "INNOV-55"
    assert entry["phase"] == 149
    assert len(entry["invariants"]) == 5
    assert "POST /mutation/explain" in entry["endpoints"]


@pytest.mark.T149
def test_mxe30_list_explanations_sorted():
    """list_explanations() returns records sorted by timestamp desc."""
    engine = _engine()
    import time
    engine.explain("mut-first", "ACCEPT")
    time.sleep(0.01)
    engine.explain("mut-second", "REJECT")
    records = engine.list_explanations(limit=10)
    assert len(records) == 2
    # Most recent should be first
    assert records[0]["mutation_id"] == "mut-second"
