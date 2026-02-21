# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
from pathlib import Path

from runtime.constitution import POLICY_HASH
from runtime.governance.amendment import AmendmentEngine


def test_amendment_lifecycle_propose_approve_reject(tmp_path: Path, monkeypatch) -> None:
    from runtime.governance import amendment

    writes = []
    review_events = []
    monkeypatch.setattr(amendment.journal, "write_entry", lambda **kwargs: writes.append(kwargs))
    monkeypatch.setattr(amendment, "record_review_quality", lambda payload: review_events.append(payload))

    policy = Path("runtime/governance/constitution.yaml").read_text(encoding="utf-8")
    policy = policy.replace('"SANDBOX": "advisory"', '"SANDBOX": "warning"', 1)
    expected_hash = hashlib.sha256(policy.encode("utf-8")).hexdigest()
    monkeypatch.setattr(amendment, "reload_constitution_policy", lambda: expected_hash)

    engine = AmendmentEngine(proposals_dir=tmp_path / "proposals", required_approvals=2)
    proposal = engine.propose_amendment(
        proposer="alice",
        new_policy_text=policy,
        rationale="test rationale",
        old_policy_hash=POLICY_HASH,
    )
    assert proposal.status == "pending"

    proposal = engine.approve_amendment(proposal.proposal_id, "bob", comment_count=2)
    assert proposal.status == "pending"

    proposal = engine.approve_amendment(proposal.proposal_id, "carol", comment_count=1)
    assert proposal.status == "approved"

    proposal = engine.reject_amendment(proposal.proposal_id, "dave", comment_count=3, overridden=True)
    assert proposal.status == "rejected"

    assert writes
    assert len(review_events) == 3
    assert review_events[0]["decision"] == "approve"
    assert review_events[-1]["decision"] == "reject"
    assert review_events[-1]["overridden"] is True
