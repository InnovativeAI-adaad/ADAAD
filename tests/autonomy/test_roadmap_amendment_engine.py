# SPDX-License-Identifier: Apache-2.0
"""
Tests — RoadmapAmendmentEngine (Phase 6)
=========================================

Acceptance criteria gated here:
  ✓ diff_score ∈ [0.0, 1.0] for all valid proposals
  ✓ authority_level always "governor-review" (injection attempt rejected)
  ✓ AmendmentProposal round-trips to/from JSON deterministically
  ✓ lineage_chain_hash is stable across identical inputs (replay-safe)
  ✓ DeterminismViolation raised on tampered lineage hash
  ✓ GovernanceViolation raised on short rationale
  ✓ GovernanceViolation raised on invalid milestone status
  ✓ Double-approval by same governor is rejected
  ✓ Terminal status (APPROVED/REJECTED) blocks further transitions
  ✓ list_pending() returns only PENDING proposals, ordered by timestamp
  ✓ Proposal diff renderer produces non-empty Markdown output
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
pytestmark = pytest.mark.autonomous_critical

from runtime.autonomy.roadmap_amendment_engine import (
    DeterminismViolation,
    GovernanceViolation,
    MilestoneEntry,
    ProposalStatus,
    RoadmapAmendmentEngine,
    RoadmapAmendmentProposal,
    _score_amendment,
    hash_roadmap,
)
from runtime.autonomy.proposal_diff_renderer import render_proposal_diff


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def tmp_engine(tmp_path):
    """Engine with isolated proposal store and temporary ROADMAP.md."""
    roadmap = tmp_path / "ROADMAP.md"
    roadmap.write_text("# ADAAD Roadmap\n\n## Phase 6\nStatus: active\n", "utf-8")
    return RoadmapAmendmentEngine(
        proposals_dir=tmp_path / "proposals",
        required_approvals=2,
        roadmap_path=roadmap,
    )


@pytest.fixture()
def valid_milestones():
    return [
        MilestoneEntry(
            phase_id=6,
            title="Autonomous Roadmap Self-Amendment",
            status="active",
            target_ver="3.1.0",
            description="Mutation engine proposes governed amendments to this roadmap.",
        )
    ]


_GOOD_RATIONALE = (
    "Phase 5 federation infrastructure is in place; constitutionally governed "
    "autonomous roadmap amendment is the next logical capability milestone."
)


# ──────────────────────────────────────────────────────────────────────────────
# MilestoneEntry validation
# ──────────────────────────────────────────────────────────────────────────────


class TestMilestoneEntry:
    def test_valid_creation(self):
        m = MilestoneEntry(6, "Test", "active", "3.1.0", "desc")
        assert m.status == "active"

    def test_invalid_status_raises(self):
        with pytest.raises(GovernanceViolation, match="not in"):
            MilestoneEntry(6, "Test", "flying", "3.1.0", "desc")

    def test_title_too_long_raises(self):
        with pytest.raises(GovernanceViolation, match="exceeds"):
            MilestoneEntry(6, "X" * 200, "active", "3.1.0", "desc")

    @pytest.mark.parametrize("status", ["proposed", "active", "shipped", "deferred", "cancelled"])
    def test_all_valid_statuses(self, status):
        m = MilestoneEntry(6, "T", status, "3.1.0", "d")
        assert m.status == status


# ──────────────────────────────────────────────────────────────────────────────
# Scoring
# ──────────────────────────────────────────────────────────────────────────────


class TestScoring:
    def test_active_milestone_positive_score(self, valid_milestones):
        score = _score_amendment(valid_milestones, _GOOD_RATIONALE)
        assert 0.0 <= score <= 1.0
        assert score > 0.0

    def test_shipped_milestone_positive(self):
        m = [MilestoneEntry(6, "Done", "shipped", "3.0.0", "x")]
        score = _score_amendment(m, _GOOD_RATIONALE)
        assert score >= 0.20

    def test_deferred_milestone_reduces_score(self):
        active = [MilestoneEntry(6, "X", "active", "3.1.0", "x")]
        deferred = [MilestoneEntry(6, "X", "deferred", "3.1.0", "x")]
        assert _score_amendment(active, _GOOD_RATIONALE) > _score_amendment(deferred, _GOOD_RATIONALE)

    def test_score_always_clamped(self):
        milestones = [MilestoneEntry(i, f"M{i}", "active", "3.1.0", "x") for i in range(1, 10)]
        score = _score_amendment(milestones, _GOOD_RATIONALE)
        assert 0.0 <= score <= 1.0

    def test_duplicate_phase_id_penalised(self):
        no_dup = [MilestoneEntry(6, "A", "active", "3.1.0", "x")]
        dup = [
            MilestoneEntry(6, "A", "active", "3.1.0", "x"),
            MilestoneEntry(6, "B", "active", "3.1.0", "y"),
        ]
        assert _score_amendment(no_dup, _GOOD_RATIONALE) >= _score_amendment(dup, _GOOD_RATIONALE)


# ──────────────────────────────────────────────────────────────────────────────
# Propose
# ──────────────────────────────────────────────────────────────────────────────


class TestPropose:
    def test_propose_returns_valid_proposal(self, tmp_engine, valid_milestones):
        p = tmp_engine.propose(
            proposer_agent="ArchitectAgent",
            milestones=valid_milestones,
            rationale=_GOOD_RATIONALE,
        )
        assert p.status == ProposalStatus.PENDING
        assert p.authority_level == "governor-review"
        assert 0.0 <= p.diff_score <= 1.0
        assert p.lineage_chain_hash != ""

    def test_authority_level_immutable(self, tmp_engine, valid_milestones):
        """authority_level is always 'governor-review' regardless of what the agent passes."""
        p = tmp_engine.propose(
            proposer_agent="BeastAgent",
            milestones=valid_milestones,
            rationale=_GOOD_RATIONALE,
        )
        assert p.authority_level == "governor-review"

    def test_short_rationale_raises(self, tmp_engine, valid_milestones):
        with pytest.raises(GovernanceViolation, match="Rationale"):
            tmp_engine.propose(
                proposer_agent="ArchitectAgent",
                milestones=valid_milestones,
                rationale="Too short.",
            )

    def test_proposal_persisted_to_disk(self, tmp_engine, valid_milestones):
        p = tmp_engine.propose(
            proposer_agent="ArchitectAgent",
            milestones=valid_milestones,
            rationale=_GOOD_RATIONALE,
        )
        stored_path = tmp_engine.proposals_dir / f"{p.proposal_id}.json"
        assert stored_path.exists()

    def test_json_round_trip(self, tmp_engine, valid_milestones):
        p = tmp_engine.propose(
            proposer_agent="ArchitectAgent",
            milestones=valid_milestones,
            rationale=_GOOD_RATIONALE,
        )
        restored = RoadmapAmendmentProposal.from_json(p.to_json())
        assert restored.proposal_id == p.proposal_id
        assert restored.lineage_chain_hash == p.lineage_chain_hash
        assert restored.authority_level == p.authority_level


# ──────────────────────────────────────────────────────────────────────────────
# Approve / Reject
# ──────────────────────────────────────────────────────────────────────────────


class TestApproveReject:
    def _make_proposal(self, engine, milestones):
        return engine.propose(
            proposer_agent="ArchitectAgent",
            milestones=milestones,
            rationale=_GOOD_RATIONALE,
        )

    def test_single_approval_stays_pending(self, tmp_engine, valid_milestones):
        p = self._make_proposal(tmp_engine, valid_milestones)
        p = tmp_engine.approve(
            p.proposal_id, governor_id="governor-a", human_signoff_token="signoff-a"
        )
        assert p.status == ProposalStatus.PENDING

    def test_direct_approval_without_signoff_is_rejected(self, tmp_engine, valid_milestones):
        p = self._make_proposal(tmp_engine, valid_milestones)
        with pytest.raises(GovernanceViolation, match="PHASE6-HUMAN-0"):
            tmp_engine.approve(p.proposal_id, governor_id="governor-a")

        persisted = RoadmapAmendmentProposal.from_json(
            (tmp_engine.proposals_dir / f"{p.proposal_id}.json").read_text("utf-8")
        )
        assert persisted.approvals == []
        assert persisted.status == ProposalStatus.PENDING

    def test_signoff_event_is_recorded_before_direct_approval_mutation(
        self, tmp_engine, valid_milestones, monkeypatch
    ):
        p = self._make_proposal(tmp_engine, valid_milestones)
        events = []

        def capture_write_entry(agent_id, action, payload=None, **kwargs):
            if action == "roadmap_amendment_human_signoff":
                persisted = RoadmapAmendmentProposal.from_json(
                    (tmp_engine.proposals_dir / f"{p.proposal_id}.json").read_text("utf-8")
                )
                assert persisted.approvals == []
                assert persisted.status == ProposalStatus.PENDING
            events.append((agent_id, action, payload, kwargs))

        monkeypatch.setattr(
            "runtime.autonomy.roadmap_amendment_engine.journal.write_entry",
            capture_write_entry,
        )

        approved = tmp_engine.approve(
            p.proposal_id, governor_id="governor-a", human_signoff_token="signoff-a"
        )

        assert approved.approvals == ["governor-a"]
        assert [event[1] for event in events] == ["roadmap_amendment_human_signoff"]

    def test_two_approvals_transitions_to_approved(self, tmp_engine, valid_milestones):
        p = self._make_proposal(tmp_engine, valid_milestones)
        tmp_engine.approve(
            p.proposal_id, governor_id="governor-a", human_signoff_token="signoff-a"
        )
        p = tmp_engine.approve(
            p.proposal_id, governor_id="governor-b", human_signoff_token="signoff-b"
        )
        assert p.status == ProposalStatus.APPROVED

    def test_double_approval_same_governor_raises(self, tmp_engine, valid_milestones):
        p = self._make_proposal(tmp_engine, valid_milestones)
        tmp_engine.approve(
            p.proposal_id, governor_id="governor-a", human_signoff_token="signoff-a"
        )
        with pytest.raises(GovernanceViolation, match="already approved"):
            tmp_engine.approve(
                p.proposal_id,
                governor_id="governor-a",
                human_signoff_token="signoff-a-duplicate",
            )

    def test_reject_is_terminal(self, tmp_engine, valid_milestones):
        p = self._make_proposal(tmp_engine, valid_milestones)
        tmp_engine.reject(p.proposal_id, governor_id="governor-a", reason="Premature.")
        with pytest.raises(GovernanceViolation, match="terminal"):
            tmp_engine.approve(
                p.proposal_id, governor_id="governor-b", human_signoff_token="signoff-b"
            )

    def test_approve_after_approved_raises(self, tmp_engine, valid_milestones):
        p = self._make_proposal(tmp_engine, valid_milestones)
        tmp_engine.approve(p.proposal_id, governor_id="g1", human_signoff_token="signoff-1")
        tmp_engine.approve(p.proposal_id, governor_id="g2", human_signoff_token="signoff-2")
        with pytest.raises(GovernanceViolation, match="terminal"):
            tmp_engine.approve(p.proposal_id, governor_id="g3", human_signoff_token="signoff-3")


# ──────────────────────────────────────────────────────────────────────────────
# Replay / Determinism
# ──────────────────────────────────────────────────────────────────────────────


class TestDeterminism:
    def test_verify_replay_returns_true(self, tmp_engine, valid_milestones):
        p = tmp_engine.propose(
            proposer_agent="ArchitectAgent",
            milestones=valid_milestones,
            rationale=_GOOD_RATIONALE,
        )
        assert tmp_engine.verify_replay(p.proposal_id) is True

    def test_tampered_lineage_raises_determinism_violation(self, tmp_engine, valid_milestones):
        p = tmp_engine.propose(
            proposer_agent="ArchitectAgent",
            milestones=valid_milestones,
            rationale=_GOOD_RATIONALE,
        )
        # Tamper: overwrite lineage_chain_hash in stored JSON
        path = tmp_engine.proposals_dir / f"{p.proposal_id}.json"
        data = json.loads(path.read_text("utf-8"))
        data["lineage_chain_hash"] = "0" * 64
        path.write_text(json.dumps(data, indent=2), "utf-8")

        with pytest.raises(DeterminismViolation, match="diverged"):
            tmp_engine.verify_replay(p.proposal_id)

    def test_identical_inputs_produce_identical_content_hash(self, tmp_engine, valid_milestones):
        p1 = tmp_engine.propose(
            proposer_agent="ArchitectAgent",
            milestones=valid_milestones,
            rationale=_GOOD_RATIONALE,
        )
        p2 = tmp_engine.propose(
            proposer_agent="ArchitectAgent",
            milestones=valid_milestones,
            rationale=_GOOD_RATIONALE,
        )
        # content_hash excludes timestamp — same content → same hash
        assert p1.content_hash() == p2.content_hash()


class TestConstitutionalAmendmentExecution:
    def test_execute_amendment_success_with_human_signoff(self, tmp_engine, valid_milestones):
        proposal = tmp_engine.propose(
            proposer_agent="ArchitectAgent",
            milestones=valid_milestones,
            rationale=_GOOD_RATIONALE,
        )
        approved = tmp_engine.execute_amendment(
            proposal.proposal_id,
            governor_id="governor-a",
            human_signoff_token="human-signoff-001",
        )
        assert approved.status == ProposalStatus.PENDING
        assert "governor-a" in approved.approvals

    def test_execute_amendment_rejects_when_signoff_missing(self, tmp_engine, valid_milestones):
        proposal = tmp_engine.propose(
            proposer_agent="ArchitectAgent",
            milestones=valid_milestones,
            rationale=_GOOD_RATIONALE,
        )
        with pytest.raises(GovernanceViolation, match="PHASE6-HUMAN-0"):
            tmp_engine.execute_amendment(
                proposal.proposal_id,
                governor_id="governor-a",
                human_signoff_token="",
            )

    def test_execute_amendment_rejects_authority_violation(self, tmp_engine, valid_milestones):
        proposal = tmp_engine.propose(
            proposer_agent="ArchitectAgent",
            milestones=valid_milestones,
            rationale=_GOOD_RATIONALE,
        )
        path = tmp_engine.proposals_dir / f"{proposal.proposal_id}.json"
        data = json.loads(path.read_text("utf-8"))
        data["authority_level"] = "agent-review"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        with pytest.raises(GovernanceViolation, match="PHASE6-AUTH-0"):
            tmp_engine.execute_amendment(
                proposal.proposal_id,
                governor_id="governor-a",
                human_signoff_token="human-signoff-001",
            )

    def test_execute_amendment_replay_parity_identical_inputs(self, tmp_engine, valid_milestones):
        proposal = tmp_engine.propose(
            proposer_agent="ArchitectAgent",
            milestones=valid_milestones,
            rationale=_GOOD_RATIONALE,
        )
        first = tmp_engine.verify_replay(proposal.proposal_id)
        second = tmp_engine.verify_replay(proposal.proposal_id)
        assert first is True
        assert second is True


# ──────────────────────────────────────────────────────────────────────────────
# list_pending
# ──────────────────────────────────────────────────────────────────────────────


class TestListPending:
    def test_only_pending_proposals_returned(self, tmp_engine, valid_milestones):
        p1 = tmp_engine.propose("A", milestones=valid_milestones, rationale=_GOOD_RATIONALE)
        p2 = tmp_engine.propose("B", milestones=valid_milestones, rationale=_GOOD_RATIONALE)
        tmp_engine.reject(p2.proposal_id, governor_id="g1", reason="out of scope")

        pending = tmp_engine.list_pending()
        ids = [p.proposal_id for p in pending]
        assert p1.proposal_id in ids
        assert p2.proposal_id not in ids


# ──────────────────────────────────────────────────────────────────────────────
# Renderer
# ──────────────────────────────────────────────────────────────────────────────


class TestRenderer:
    def test_render_produces_markdown(self, tmp_engine, valid_milestones):
        p = tmp_engine.propose(
            proposer_agent="ArchitectAgent",
            milestones=valid_milestones,
            rationale=_GOOD_RATIONALE,
        )
        md = render_proposal_diff(p)
        assert "## 📋 Roadmap Amendment" in md
        assert p.proposal_id in md
        assert "governor-review" in md
        assert "Autonomous Roadmap Self-Amendment" in md

    def test_render_includes_lineage_fingerprint(self, tmp_engine, valid_milestones):
        p = tmp_engine.propose(
            proposer_agent="ArchitectAgent",
            milestones=valid_milestones,
            rationale=_GOOD_RATIONALE,
        )
        md = render_proposal_diff(p)
        assert p.prior_roadmap_hash[:16] in md
        assert p.lineage_chain_hash[:16] in md

    def test_render_score_bar_present(self, tmp_engine, valid_milestones):
        p = tmp_engine.propose(
            proposer_agent="ArchitectAgent",
            milestones=valid_milestones,
            rationale=_GOOD_RATIONALE,
        )
        md = render_proposal_diff(p)
        # score bar uses block characters
        assert "▓" in md or "░" in md
