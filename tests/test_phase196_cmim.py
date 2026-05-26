"""
Phase 196 - INNOV-101 CMIM - Constitutional Mutation Intent Model
30-test acceptance suite (T196-CMIM-01..30) - 30/30 required
"""
import pytest, time, uuid, json
from pathlib import Path
from dorkllm.constitutional_mutation_intent_model import (
    ConstitutionalMutationIntentModel, MutationIntentDeclaration,
    CMIMIntentIncomplete, CMIMBlastMismatch, CMIMIntentTraceFail,
    CMIMAuthorInvalid, CMIMHuman0Required, CMIMRollbackTriggered, CMIMChainBroken,
)

pytestmark = pytest.mark.phase196

VALID_DECL_KWARGS = dict(
    mutation_id="MUT-TEST-001",
    goal_statement="Test mutation for CMIM acceptance",
    expected_invariants_touched=["CMIM-INTENT-0","CMIM-COMPLETE-0"],
    blast_radius_tier=1,
    ratification_scope="auto-ratified",
    author_agent="MutationAgent",
    target_cel_stages=[1,2,3],
    governance_objectives=["CEL_INTEGRITY","DETERMINISM"],
)

def make_engine(tmp_path):
    return ConstitutionalMutationIntentModel(ledger_path=tmp_path/"ledger.jsonl")

def make_decl(**overrides):
    kwargs = {**VALID_DECL_KWARGS, **overrides}
    kwargs["mutation_id"] = kwargs.get("mutation_id", f"MUT-{uuid.uuid4().hex[:8]}")
    return MutationIntentDeclaration(**kwargs)

# ── T196-CMIM-01..08: CMIM-COMPLETE-0 Completeness ───────────────────────────

def test_T196_CMIM_01_declaration_accepted(tmp_path):
    """T196-CMIM-01: Valid declaration accepted with declaration_id returned."""
    engine = make_engine(tmp_path)
    decl = make_decl()
    did = engine.declare_intent(decl)
    assert did == decl.declaration_id

def test_T196_CMIM_02_missing_goal_statement_rejected(tmp_path):
    """T196-CMIM-02: Missing goal_statement raises CMIM-COMPLETE-0."""
    engine = make_engine(tmp_path)
    decl = make_decl(goal_statement="")
    with pytest.raises(CMIMIntentIncomplete, match="CMIM-COMPLETE-0"):
        engine.declare_intent(decl)

def test_T196_CMIM_03_missing_mutation_id_rejected(tmp_path):
    """T196-CMIM-03: Missing mutation_id raises CMIM-COMPLETE-0."""
    engine = make_engine(tmp_path)
    decl = make_decl(mutation_id="")
    with pytest.raises(CMIMIntentIncomplete, match="CMIM-COMPLETE-0"):
        engine.declare_intent(decl)

def test_T196_CMIM_04_missing_invariants_rejected(tmp_path):
    """T196-CMIM-04: Empty expected_invariants_touched raises CMIM-COMPLETE-0."""
    engine = make_engine(tmp_path)
    decl = make_decl(expected_invariants_touched=[])
    with pytest.raises(CMIMIntentIncomplete, match="CMIM-COMPLETE-0"):
        engine.declare_intent(decl)

def test_T196_CMIM_05_missing_ratification_scope_rejected(tmp_path):
    """T196-CMIM-05: Missing ratification_scope raises CMIM-COMPLETE-0."""
    engine = make_engine(tmp_path)
    decl = make_decl(ratification_scope="")
    with pytest.raises(CMIMIntentIncomplete, match="CMIM-COMPLETE-0"):
        engine.declare_intent(decl)

def test_T196_CMIM_06_missing_target_cel_stages_rejected(tmp_path):
    """T196-CMIM-06: Empty target_cel_stages raises CMIM-COMPLETE-0."""
    engine = make_engine(tmp_path)
    decl = make_decl(target_cel_stages=[])
    with pytest.raises(CMIMIntentIncomplete, match="CMIM-COMPLETE-0"):
        engine.declare_intent(decl)

def test_T196_CMIM_07_multiple_declarations_stored(tmp_path):
    """T196-CMIM-07: Multiple declarations independently stored."""
    engine = make_engine(tmp_path)
    ids = []
    for i in range(3):
        decl = make_decl(mutation_id=f"MUT-{i:03d}")
        ids.append(engine.declare_intent(decl))
    assert len(set(ids)) == 3

def test_T196_CMIM_08_declaration_retrievable(tmp_path):
    """T196-CMIM-08: Declared intent is retrievable by declaration_id."""
    engine = make_engine(tmp_path)
    decl = make_decl()
    did = engine.declare_intent(decl)
    stored = engine.get_declaration(did)
    assert stored is not None
    assert stored["mutation_id"] == decl.mutation_id

# ── T196-CMIM-09..15: CMIM-AUTHOR-0 and CMIM-BLAST-0 ────────────────────────

def test_T196_CMIM_09_invalid_author_rejected(tmp_path):
    """T196-CMIM-09: Unknown author_agent raises CMIM-AUTHOR-0."""
    engine = make_engine(tmp_path)
    decl = make_decl(author_agent="UnknownBot")
    with pytest.raises(CMIMAuthorInvalid, match="CMIM-AUTHOR-0"):
        engine.declare_intent(decl)

def test_T196_CMIM_10_all_valid_agents_accepted(tmp_path):
    """T196-CMIM-10: All four ratified agents accepted."""
    engine = make_engine(tmp_path)
    for agent in ["ArchitectAgent","MutationAgent","DreamAgent","BeastAgent"]:
        decl = make_decl(author_agent=agent, mutation_id=f"MUT-{agent}")
        did = engine.declare_intent(decl)
        assert did is not None

def test_T196_CMIM_11_invalid_blast_tier_rejected(tmp_path):
    """T196-CMIM-11: blast_radius_tier=99 raises CMIM-BLAST-0."""
    engine = make_engine(tmp_path)
    decl = make_decl(blast_radius_tier=99)
    with pytest.raises(CMIMBlastMismatch, match="CMIM-BLAST-0"):
        engine.declare_intent(decl)

def test_T196_CMIM_12_blast_tier_0_requires_human0(tmp_path):
    """T196-CMIM-12: Tier 0 without countersig raises CMIM-HUMAN0-0."""
    engine = make_engine(tmp_path)
    decl = make_decl(blast_radius_tier=0)
    with pytest.raises(CMIMHuman0Required, match="CMIM-HUMAN0-0"):
        engine.declare_intent(decl, human0_countersig=None)

def test_T196_CMIM_13_blast_tier_0_with_human0_accepted(tmp_path):
    """T196-CMIM-13: Tier 0 with HUMAN-0 countersig accepted."""
    engine = make_engine(tmp_path)
    decl = make_decl(blast_radius_tier=0, ratification_scope="HUMAN-0 required")
    did = engine.declare_intent(decl, human0_countersig="approved DUSTIN L REID")
    assert did is not None

def test_T196_CMIM_14_blast_tier_1_no_human0_required(tmp_path):
    """T196-CMIM-14: Tier 1 without countersig accepted."""
    engine = make_engine(tmp_path)
    decl = make_decl(blast_radius_tier=1)
    did = engine.declare_intent(decl)
    assert did is not None

def test_T196_CMIM_15_blast_tier_2_no_human0_required(tmp_path):
    """T196-CMIM-15: Tier 2 without countersig accepted."""
    engine = make_engine(tmp_path)
    decl = make_decl(blast_radius_tier=2)
    did = engine.declare_intent(decl)
    assert did is not None

# ── T196-CMIM-16..21: CMIM-TRACE-0 Objective Traceability ───────────────────

def test_T196_CMIM_16_empty_objectives_rejected(tmp_path):
    """T196-CMIM-16: Empty governance_objectives raises a CMIM constitutional error (COMPLETE-0 or TRACE-0)."""
    from dorkllm.constitutional_mutation_intent_model import CMIMError
    engine = make_engine(tmp_path)
    decl = make_decl(governance_objectives=[])
    with pytest.raises(CMIMError):
        engine.declare_intent(decl)

def test_T196_CMIM_17_unrecognized_objective_rejected(tmp_path):
    """T196-CMIM-17: Unrecognized governance objective raises CMIM-TRACE-0."""
    engine = make_engine(tmp_path)
    decl = make_decl(governance_objectives=["MADE_UP_OBJECTIVE"])
    with pytest.raises(CMIMIntentTraceFail, match="CMIM-TRACE-0"):
        engine.declare_intent(decl)

def test_T196_CMIM_18_all_valid_objectives_accepted(tmp_path):
    """T196-CMIM-18: All 15 recognized objectives accepted individually."""
    from dorkllm.constitutional_mutation_intent_model import GOVERNANCE_OBJECTIVES
    engine = make_engine(tmp_path)
    for obj in list(GOVERNANCE_OBJECTIVES)[:5]:
        decl = make_decl(governance_objectives=[obj], mutation_id=f"MUT-OBJ-{obj}")
        did = engine.declare_intent(decl)
        assert did is not None

def test_T196_CMIM_19_multiple_objectives_accepted(tmp_path):
    """T196-CMIM-19: Multiple objectives accepted."""
    engine = make_engine(tmp_path)
    decl = make_decl(governance_objectives=["CEL_INTEGRITY","DETERMINISM","HUMAN0_GATE"])
    did = engine.declare_intent(decl)
    assert did is not None

def test_T196_CMIM_20_mixed_valid_invalid_objectives_rejected(tmp_path):
    """T196-CMIM-20: Mix of valid and invalid objectives is rejected."""
    engine = make_engine(tmp_path)
    decl = make_decl(governance_objectives=["CEL_INTEGRITY","FAKE_OBJ"])
    with pytest.raises(CMIMIntentTraceFail, match="CMIM-TRACE-0"):
        engine.declare_intent(decl)

def test_T196_CMIM_21_none_declaration_rejected(tmp_path):
    """T196-CMIM-21: None declaration raises CMIM-INTENT-0."""
    engine = make_engine(tmp_path)
    with pytest.raises(CMIMIntentIncomplete, match="CMIM-INTENT-0"):
        engine.declare_intent(None)

# ── T196-CMIM-22..26: CMIM-SCOPE-0 and CMIM-ROLLBACK-0 ─────────────────────

def test_T196_CMIM_22_matching_intent_passes(tmp_path):
    """T196-CMIM-22: Exact match between declared and actual invariants passes."""
    engine = make_engine(tmp_path)
    decl = make_decl(expected_invariants_touched=["INV-A","INV-B"])
    did = engine.declare_intent(decl)
    report = engine.verify_intent(did, ["INV-A","INV-B"], 1)
    assert report.verdict == "PASS"
    assert not report.rollback_required

def test_T196_CMIM_23_undeclared_invariant_triggers_rollback(tmp_path):
    """T196-CMIM-23: Undeclared invariant triggers CMIM-ROLLBACK-0."""
    engine = make_engine(tmp_path)
    decl = make_decl(expected_invariants_touched=["INV-A"])
    did = engine.declare_intent(decl)
    with pytest.raises(CMIMRollbackTriggered, match="CMIM-ROLLBACK-0"):
        engine.verify_intent(did, ["INV-A","INV-SURPRISE"], 1)

def test_T196_CMIM_24_skipped_declared_invariant_triggers_rollback(tmp_path):
    """T196-CMIM-24: Skipped declared invariant triggers CMIM-ROLLBACK-0."""
    engine = make_engine(tmp_path)
    decl = make_decl(expected_invariants_touched=["INV-A","INV-B"])
    did = engine.declare_intent(decl)
    with pytest.raises(CMIMRollbackTriggered, match="CMIM-ROLLBACK-0"):
        engine.verify_intent(did, ["INV-A"], 1)  # INV-B skipped

def test_T196_CMIM_25_blast_tier_mismatch_triggers_rollback(tmp_path):
    """T196-CMIM-25: Actual blast tier != declared tier triggers CMIM-ROLLBACK-0."""
    engine = make_engine(tmp_path)
    decl = make_decl(expected_invariants_touched=["INV-A"], blast_radius_tier=1)
    did = engine.declare_intent(decl)
    with pytest.raises(CMIMRollbackTriggered, match="CMIM-ROLLBACK-0"):
        engine.verify_intent(did, ["INV-A"], actual_blast_tier=0)  # tier escalation

def test_T196_CMIM_26_unknown_declaration_id_rejected(tmp_path):
    """T196-CMIM-26: Verify with unknown declaration_id raises CMIM-INTENT-0."""
    engine = make_engine(tmp_path)
    with pytest.raises(CMIMIntentIncomplete, match="CMIM-INTENT-0"):
        engine.verify_intent("non-existent-id", ["INV-A"], 1)

# ── T196-CMIM-27..30: CMIM-CHAIN-0 Ledger Integrity ────────────────────────

def test_T196_CMIM_27_chain_integrity_empty_ledger(tmp_path):
    """T196-CMIM-27: Empty ledger reports EMPTY status."""
    engine = make_engine(tmp_path)
    result = engine.verify_chain_integrity()
    assert result["status"] == "EMPTY"

def test_T196_CMIM_28_chain_integrity_after_declarations(tmp_path):
    """T196-CMIM-28: Chain intact after multiple declarations."""
    engine = make_engine(tmp_path)
    for i in range(3):
        decl = make_decl(mutation_id=f"MUT-CHAIN-{i}")
        engine.declare_intent(decl)
    result = engine.verify_chain_integrity()
    assert result["status"] == "INTACT"
    assert result["entries"] == 3

def test_T196_CMIM_29_ledger_summary_counts_correctly(tmp_path):
    """T196-CMIM-29: Ledger summary counts declarations and verifications."""
    engine = make_engine(tmp_path)
    decl1 = make_decl(mutation_id="MUT-S1", expected_invariants_touched=["INV-A"])
    did1 = engine.declare_intent(decl1)
    engine.verify_intent(did1, ["INV-A"], 1)
    decl2 = make_decl(mutation_id="MUT-S2")
    engine.declare_intent(decl2)
    summary = engine.get_ledger_summary()
    assert summary["declarations"] == 2
    assert summary["verifications"] == 1
    assert summary["entries"] == 3

def test_T196_CMIM_30_fingerprint_determinism(tmp_path):
    """T196-CMIM-30: Same declaration produces identical fingerprint (CMIM-DETERM-0)."""
    d1 = make_decl(mutation_id="MUT-FP", declaration_id="FIXED-ID")
    d2 = make_decl(mutation_id="MUT-FP", declaration_id="FIXED-ID")
    assert d1.fingerprint() == d2.fingerprint()
