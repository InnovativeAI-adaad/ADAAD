# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
import hashlib

from runtime.constitution import POLICY_HASH
from runtime.governance.amendment import AmendmentEngine


def test_amendment_lifecycle_propose_approve_reject(tmp_path: Path, monkeypatch) -> None:
    from runtime.governance import amendment

    writes = []
    monkeypatch.setattr(amendment.journal, "write_entry", lambda **kwargs: writes.append(kwargs))
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

    proposal = engine.approve_amendment(proposal.proposal_id, "bob")
    assert proposal.status == "pending"

    proposal = engine.approve_amendment(proposal.proposal_id, "carol")
    assert proposal.status == "approved"

    proposal = engine.reject_amendment(proposal.proposal_id, "dave")
    assert proposal.status == "rejected"
    assert writes
