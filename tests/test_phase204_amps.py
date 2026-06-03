# SPDX-License-Identifier: Apache-2.0
"""Phase 204 · INNOV-109 · AMPS — Autonomous Mutation Proposal Synthesizer
30-test acceptance suite (T204-AMPS-01 … T204-AMPS-30).

All 30 tests must pass before Phase 204 is promoted.
Governor: DUSTIN L REID · InnovativeAI LLC
"""

from __future__ import annotations

import json
import hashlib
import os
import tempfile
from pathlib import Path
from typing import Generator

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_paths(tmp_path: Path):
    ledger = tmp_path / "amps_ledger.jsonl"
    synth_log = tmp_path / "amps_synth_log.jsonl"
    return ledger, synth_log


@pytest.fixture()
def healthy_amps(tmp_paths):
    from dorkllm.autonomous_mutation_proposal_synthesizer import (
        AutonomousMutationProposalSynthesizer,
    )
    ledger, synth_log = tmp_paths
    return AutonomousMutationProposalSynthesizer(
        ledger_path=ledger,
        synthesis_log_path=synth_log,
        cgdr_status_override="HEALTHY",
    )


@pytest.fixture()
def drifted_amps(tmp_paths):
    from dorkllm.autonomous_mutation_proposal_synthesizer import (
        AutonomousMutationProposalSynthesizer,
    )
    ledger, synth_log = tmp_paths
    return AutonomousMutationProposalSynthesizer(
        ledger_path=ledger,
        synthesis_log_path=synth_log,
        cgdr_status_override="DRIFTED",
    )


@pytest.fixture()
def alert_amps(tmp_paths):
    from dorkllm.autonomous_mutation_proposal_synthesizer import (
        AutonomousMutationProposalSynthesizer,
    )
    ledger, synth_log = tmp_paths
    return AutonomousMutationProposalSynthesizer(
        ledger_path=ledger,
        synthesis_log_path=synth_log,
        cgdr_status_override="DRIFT_ALERT",
    )


# ===========================================================================
# T204-AMPS-01: synthesize returns PROPOSALS_GENERATED when CGDR is HEALTHY
# ===========================================================================
@pytest.mark.phase204
def test_t204_amps_01_synthesize_healthy(healthy_amps):
    result = healthy_amps.synthesize(max_proposals=3)
    assert result["outcome"] == "PROPOSALS_GENERATED"
    assert len(result["proposals"]) == 3


# ===========================================================================
# T204-AMPS-02: each proposal has a constitutional_fitness score
# ===========================================================================
@pytest.mark.phase204
def test_t204_amps_02_proposals_have_score(healthy_amps):
    result = healthy_amps.synthesize(max_proposals=3)
    for prop in result["proposals"]:
        score = prop.get("constitutional_fitness")
        assert score is not None, "AMPS-SCORE-0: score must be present"
        assert 0.0 <= score <= 1.0, "AMPS-SCORE-0: score must be in [0.0, 1.0]"


# ===========================================================================
# T204-AMPS-03: each proposal has a blast_radius classification
# ===========================================================================
@pytest.mark.phase204
def test_t204_amps_03_proposals_have_blast_radius(healthy_amps):
    result = healthy_amps.synthesize(max_proposals=3)
    valid_radii = {"TIER0", "TIER1", "TIER2"}
    for prop in result["proposals"]:
        assert prop.get("blast_radius") in valid_radii, "AMPS-BLAST-0: blast_radius must be classified"


# ===========================================================================
# T204-AMPS-04: proposal IDs are deterministic (AMPS-DETERM-0)
# ===========================================================================
@pytest.mark.phase204
def test_t204_amps_04_deterministic_proposal_ids(tmp_paths):
    from dorkllm.autonomous_mutation_proposal_synthesizer import AutonomousMutationProposalSynthesizer
    ledger, synth = tmp_paths
    # Two engines with same inputs — prop IDs are derived from title+category+ts
    # We verify format: starts with PROP- and has 16 hex chars
    eng = AutonomousMutationProposalSynthesizer(ledger_path=ledger, synthesis_log_path=synth, cgdr_status_override="HEALTHY")
    result = eng.synthesize(max_proposals=1)
    prop_id = result["proposals"][0]["proposal_id"]
    assert prop_id.startswith("PROP-"), "AMPS-DETERM-0: ID must start with PROP-"
    suffix = prop_id[5:]
    assert len(suffix) == 16, "AMPS-DETERM-0: suffix must be 16 chars"
    assert all(c in "0123456789ABCDEF" for c in suffix), "AMPS-DETERM-0: suffix must be hex"


# ===========================================================================
# T204-AMPS-05: proposals sealed with content_seal (AMPS-SEAL-0)
# ===========================================================================
@pytest.mark.phase204
def test_t204_amps_05_content_seal_present(healthy_amps):
    result = healthy_amps.synthesize(max_proposals=2)
    for prop in result["proposals"]:
        assert "content_seal" in prop, "AMPS-SEAL-0: content_seal must be present"
        assert len(prop["content_seal"]) == 64, "AMPS-SEAL-0: SHA-256 seal must be 64 hex chars"


# ===========================================================================
# T204-AMPS-06: proposals sealed in HMAC-chained ledger (AMPS-CHAIN-0)
# ===========================================================================
@pytest.mark.phase204
def test_t204_amps_06_ledger_chain_valid_after_synthesize(healthy_amps):
    healthy_amps.synthesize(max_proposals=3)
    chain_result = healthy_amps.verify_chain()
    assert chain_result["valid"] is True, "AMPS-CHAIN-0: ledger chain must be valid"


# ===========================================================================
# T204-AMPS-07: synthesis run logged in synthesis log (AMPS-AUDIT-0)
# ===========================================================================
@pytest.mark.phase204
def test_t204_amps_07_synthesis_audit_logged(tmp_paths):
    from dorkllm.autonomous_mutation_proposal_synthesizer import AutonomousMutationProposalSynthesizer
    ledger, synth = tmp_paths
    eng = AutonomousMutationProposalSynthesizer(ledger_path=ledger, synthesis_log_path=synth, cgdr_status_override="HEALTHY")
    eng.synthesize(max_proposals=2)
    assert synth.exists(), "AMPS-AUDIT-0: synthesis log must exist after run"
    lines = [l for l in synth.read_text().splitlines() if l.strip()]
    assert len(lines) >= 1, "AMPS-AUDIT-0: synthesis log must have at least one entry"


# ===========================================================================
# T204-AMPS-08: ratification by HUMAN-0 succeeds
# ===========================================================================
@pytest.mark.phase204
def test_t204_amps_08_ratification_by_human0_succeeds(healthy_amps):
    result = healthy_amps.synthesize(max_proposals=1)
    prop_id = result["proposals"][0]["proposal_id"]
    ratified = healthy_amps.ratify_proposal(prop_id, human_id="HUMAN-0")
    assert ratified["status"] == "RATIFIED"
    assert ratified["ratified_by"] == "HUMAN-0"


# ===========================================================================
# T204-AMPS-09: ratification by non-HUMAN-0 raises AMPSHuman0Error (AMPS-HUMAN0-0)
# ===========================================================================
@pytest.mark.phase204
def test_t204_amps_09_ratification_rejects_non_human0(healthy_amps):
    from dorkllm.autonomous_mutation_proposal_synthesizer import AMPSHuman0Error
    result = healthy_amps.synthesize(max_proposals=1)
    prop_id = result["proposals"][0]["proposal_id"]
    with pytest.raises(AMPSHuman0Error):
        healthy_amps.ratify_proposal(prop_id, human_id="RANDOM_USER")


# ===========================================================================
# T204-AMPS-10: ratification blocked when CGDR is DRIFTED (AMPS-CGDR-0)
# ===========================================================================
@pytest.mark.phase204
def test_t204_amps_10_ratification_blocked_when_drifted(tmp_paths):
    from dorkllm.autonomous_mutation_proposal_synthesizer import (
        AutonomousMutationProposalSynthesizer, AMPSCGDRGateError
    )
    ledger, synth = tmp_paths
    # Synthesize while healthy
    healthy = AutonomousMutationProposalSynthesizer(ledger_path=ledger, synthesis_log_path=synth, cgdr_status_override="HEALTHY")
    result = healthy.synthesize(max_proposals=1)
    prop_id = result["proposals"][0]["proposal_id"]
    # Now ratify with DRIFTED engine
    drifted = AutonomousMutationProposalSynthesizer(ledger_path=ledger, synthesis_log_path=synth, cgdr_status_override="DRIFTED")
    with pytest.raises(AMPSCGDRGateError):
        drifted.ratify_proposal(prop_id, human_id="HUMAN-0")


# ===========================================================================
# T204-AMPS-11: re-ratification of already-ratified proposal raises AMPSImmutabilityError (AMPS-IMMUT-0)
# ===========================================================================
@pytest.mark.phase204
def test_t204_amps_11_no_double_ratification(healthy_amps):
    from dorkllm.autonomous_mutation_proposal_synthesizer import AMPSImmutabilityError
    result = healthy_amps.synthesize(max_proposals=1)
    prop_id = result["proposals"][0]["proposal_id"]
    healthy_amps.ratify_proposal(prop_id, human_id="HUMAN-0")
    with pytest.raises(AMPSImmutabilityError):
        healthy_amps.ratify_proposal(prop_id, human_id="HUMAN-0")


# ===========================================================================
# T204-AMPS-12: get_proposals returns all proposals
# ===========================================================================
@pytest.mark.phase204
def test_t204_amps_12_get_proposals_returns_all(healthy_amps):
    healthy_amps.synthesize(max_proposals=3)
    proposals = healthy_amps.get_proposals()
    assert len(proposals) == 3


# ===========================================================================
# T204-AMPS-13: get_proposals with status_filter works
# ===========================================================================
@pytest.mark.phase204
def test_t204_amps_13_status_filter(healthy_amps):
    result = healthy_amps.synthesize(max_proposals=2)
    prop_id = result["proposals"][0]["proposal_id"]
    healthy_amps.ratify_proposal(prop_id, human_id="HUMAN-0")
    pending = healthy_amps.get_proposals(status_filter="PENDING")
    ratified = healthy_amps.get_proposals(status_filter="RATIFIED")
    assert len(pending) == 1
    assert len(ratified) == 1


# ===========================================================================
# T204-AMPS-14: get_proposal by ID returns correct record
# ===========================================================================
@pytest.mark.phase204
def test_t204_amps_14_get_proposal_by_id(healthy_amps):
    result = healthy_amps.synthesize(max_proposals=1)
    prop_id = result["proposals"][0]["proposal_id"]
    fetched = healthy_amps.get_proposal(prop_id)
    assert fetched["proposal_id"] == prop_id


# ===========================================================================
# T204-AMPS-15: get_proposal raises KeyError for unknown ID
# ===========================================================================
@pytest.mark.phase204
def test_t204_amps_15_get_proposal_unknown_id_raises(healthy_amps):
    with pytest.raises(KeyError):
        healthy_amps.get_proposal("PROP-DOESNOTEXIST123456")


# ===========================================================================
# T204-AMPS-16: get_status returns correct structure
# ===========================================================================
@pytest.mark.phase204
def test_t204_amps_16_get_status_structure(healthy_amps):
    status = healthy_amps.get_status()
    assert status["engine"] == "AMPS"
    assert "cgdr_gate_status" in status
    assert "total_proposals" in status
    assert "invariants" in status
    assert len(status["invariants"]) == 10


# ===========================================================================
# T204-AMPS-17: status promotion_gate is OPEN when CGDR HEALTHY
# ===========================================================================
@pytest.mark.phase204
def test_t204_amps_17_promotion_gate_open_when_healthy(healthy_amps):
    status = healthy_amps.get_status()
    assert status["promotion_gate"] == "OPEN"


# ===========================================================================
# T204-AMPS-18: status promotion_gate is BLOCKED when CGDR DRIFTED
# ===========================================================================
@pytest.mark.phase204
def test_t204_amps_18_promotion_gate_blocked_when_drifted(drifted_amps):
    status = drifted_amps.get_status()
    assert status["promotion_gate"] == "BLOCKED"


# ===========================================================================
# T204-AMPS-19: proposals ranked by constitutional_fitness descending
# ===========================================================================
@pytest.mark.phase204
def test_t204_amps_19_proposals_ranked_by_fitness(healthy_amps):
    healthy_amps.synthesize(max_proposals=3)
    proposals = healthy_amps.get_proposals()
    scores = [p["constitutional_fitness"] for p in proposals]
    assert scores == sorted(scores, reverse=True), "Proposals must be ranked by fitness descending"


# ===========================================================================
# T204-AMPS-20: all proposals have governor field set to DUSTIN L REID
# ===========================================================================
@pytest.mark.phase204
def test_t204_amps_20_governor_field(healthy_amps):
    result = healthy_amps.synthesize(max_proposals=3)
    for prop in result["proposals"]:
        assert prop.get("governor") == "DUSTIN L REID"


# ===========================================================================
# T204-AMPS-21: synthesis with max_proposals=1 returns exactly 1 proposal
# ===========================================================================
@pytest.mark.phase204
def test_t204_amps_21_max_proposals_respected(healthy_amps):
    result = healthy_amps.synthesize(max_proposals=1)
    assert len(result["proposals"]) == 1


# ===========================================================================
# T204-AMPS-22: synthesis with DRIFT_ALERT still succeeds (alert < drifted)
# ===========================================================================
@pytest.mark.phase204
def test_t204_amps_22_synthesis_ok_on_drift_alert(alert_amps):
    result = alert_amps.synthesize(max_proposals=2)
    assert result["outcome"] == "PROPOSALS_GENERATED"


# ===========================================================================
# T204-AMPS-23: CGDR status is reflected in synthesis result
# ===========================================================================
@pytest.mark.phase204
def test_t204_amps_23_cgdr_status_in_result(healthy_amps):
    result = healthy_amps.synthesize(max_proposals=1)
    assert result.get("cgdr_status") == "HEALTHY"


# ===========================================================================
# T204-AMPS-24: chain verify returns entries count
# ===========================================================================
@pytest.mark.phase204
def test_t204_amps_24_verify_chain_entries_count(healthy_amps):
    healthy_amps.synthesize(max_proposals=3)
    chain = healthy_amps.verify_chain()
    assert chain["valid"] is True
    assert chain["entries"] >= 3


# ===========================================================================
# T204-AMPS-25: chain tip is a hex string
# ===========================================================================
@pytest.mark.phase204
def test_t204_amps_25_chain_tip_is_hex(healthy_amps):
    healthy_amps.synthesize(max_proposals=1)
    chain = healthy_amps.verify_chain()
    tip = chain["tip"]
    assert all(c in "0123456789abcdef" for c in tip), "Chain tip must be hex"


# ===========================================================================
# T204-AMPS-26: proposals have synthesized_at timestamp
# ===========================================================================
@pytest.mark.phase204
def test_t204_amps_26_proposals_have_timestamp(healthy_amps):
    result = healthy_amps.synthesize(max_proposals=2)
    for prop in result["proposals"]:
        assert prop.get("synthesized_at") is not None


# ===========================================================================
# T204-AMPS-27: proposals have synthesis_run_id linking to run
# ===========================================================================
@pytest.mark.phase204
def test_t204_amps_27_proposals_linked_to_run(healthy_amps):
    result = healthy_amps.synthesize(max_proposals=2)
    run_id = result["run_id"]
    for prop in result["proposals"]:
        assert prop.get("synthesis_run_id") == run_id


# ===========================================================================
# T204-AMPS-28: DUSTIN L REID is a valid HUMAN-0 identity
# ===========================================================================
@pytest.mark.phase204
def test_t204_amps_28_dustin_reid_valid_human0(healthy_amps):
    result = healthy_amps.synthesize(max_proposals=1)
    prop_id = result["proposals"][0]["proposal_id"]
    ratified = healthy_amps.ratify_proposal(prop_id, human_id="DUSTIN L REID")
    assert ratified["status"] == "RATIFIED"


# ===========================================================================
# T204-AMPS-29: ratification sealed with new content_seal (AMPS-SEAL-0)
# ===========================================================================
@pytest.mark.phase204
def test_t204_amps_29_ratification_updates_seal(healthy_amps):
    result = healthy_amps.synthesize(max_proposals=1)
    prop = result["proposals"][0]
    prop_id = prop["proposal_id"]
    original_seal = prop["content_seal"]
    ratified = healthy_amps.ratify_proposal(prop_id, human_id="HUMAN-0")
    # Seal must change because status and ratified_by changed
    assert ratified["content_seal"] != original_seal, "AMPS-SEAL-0: seal must be updated after ratification"


# ===========================================================================
# T204-AMPS-30: status proposal counts update after ratification
# ===========================================================================
@pytest.mark.phase204
def test_t204_amps_30_status_counts_update_after_ratification(healthy_amps):
    result = healthy_amps.synthesize(max_proposals=2)
    prop_id = result["proposals"][0]["proposal_id"]
    before = healthy_amps.get_status()
    assert before["pending"] == 2
    healthy_amps.ratify_proposal(prop_id, human_id="HUMAN-0")
    after = healthy_amps.get_status()
    assert after["pending"] == 1
    assert after["ratified"] == 1
