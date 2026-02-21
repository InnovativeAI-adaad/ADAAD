# SPDX-License-Identifier: Apache-2.0
"""Constitutional amendment proposal and approval workflow."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from runtime import ROOT_DIR
from runtime.constitution import CONSTITUTION_VERSION, reload_constitution_policy
from runtime.governance.deterministic_filesystem import read_file_deterministic
from runtime.governance.foundation import default_provider
from runtime.governance.review_quality import record_review_quality
from security.ledger import journal


@dataclass
class AmendmentProposal:
    proposal_id: str
    proposer: str
    timestamp: str
    old_policy_hash: str
    new_policy_text: str
    new_policy_hash: str
    rationale: str
    approvals: List[str]
    rejections: List[str]
    status: str


class AmendmentEngine:
    def __init__(self, proposals_dir: Path | None = None, required_approvals: int = 2):
        self.proposals_dir = proposals_dir or (ROOT_DIR / "runtime" / "governance" / "proposals")
        self.proposals_dir.mkdir(parents=True, exist_ok=True)
        self.required_approvals = required_approvals

    def propose_amendment(self, *, proposer: str, new_policy_text: str, rationale: str, old_policy_hash: str) -> AmendmentProposal:
        provider = default_provider()
        new_hash = hashlib.sha256(new_policy_text.encode("utf-8")).hexdigest()
        proposal_id = f"amendment-{provider.format_utc('%Y%m%dT%H%M%SZ')}"
        proposal = AmendmentProposal(
            proposal_id=proposal_id,
            proposer=proposer,
            timestamp=provider.iso_now(),
            old_policy_hash=old_policy_hash,
            new_policy_text=new_policy_text,
            new_policy_hash=new_hash,
            rationale=rationale,
            approvals=[],
            rejections=[],
            status="pending",
        )
        self._save_proposal(proposal)
        journal.write_entry(
            agent_id="system",
            action="constitutional_amendment_proposed",
            payload={
                "proposal_id": proposal_id,
                "proposer": proposer,
                "policy_hash_change": f"{old_policy_hash[:8]}→{new_hash[:8]}",
                "rationale": rationale,
            },
        )
        return proposal

    def approve_amendment(
        self,
        proposal_id: str,
        approver: str,
        *,
        comment_count: int = 0,
        overridden: bool = False,
    ) -> AmendmentProposal:
        proposal = self._load_proposal(proposal_id)
        if proposal.status != "pending":
            return proposal
        if approver not in proposal.approvals:
            proposal.approvals.append(approver)
        if len(proposal.approvals) >= self.required_approvals:
            proposal.status = "approved"
            self._apply_amendment(proposal)
        record_review_quality(
            {
                "mutation_id": proposal.proposal_id,
                "review_id": f"approve:{proposal.proposal_id}:{approver}",
                "reviewer": approver,
                "latency_seconds": self._review_latency_seconds(proposal.timestamp),
                "comment_count": comment_count,
                "decision": "approve",
                "overridden": overridden,
                "context": "constitutional_amendment",
            }
        )
        self._save_proposal(proposal)
        return proposal

    def reject_amendment(
        self,
        proposal_id: str,
        rejector: str,
        *,
        comment_count: int = 0,
        overridden: bool = False,
    ) -> AmendmentProposal:
        proposal = self._load_proposal(proposal_id)
        if rejector not in proposal.rejections:
            proposal.rejections.append(rejector)
        proposal.status = "rejected"
        self._save_proposal(proposal)
        record_review_quality(
            {
                "mutation_id": proposal.proposal_id,
                "review_id": f"reject:{proposal.proposal_id}:{rejector}",
                "reviewer": rejector,
                "latency_seconds": self._review_latency_seconds(proposal.timestamp),
                "comment_count": comment_count,
                "decision": "reject",
                "overridden": overridden,
                "context": "constitutional_amendment",
            }
        )
        journal.write_entry(
            agent_id="system",
            action="constitutional_amendment_rejected",
            payload={"proposal_id": proposal_id, "rejector": rejector},
        )
        return proposal

    def _apply_amendment(self, proposal: AmendmentProposal) -> None:
        staged_policy = self.proposals_dir / f"{proposal.proposal_id}.policy.json"
        staged_policy.write_text(proposal.new_policy_text, encoding="utf-8")
        try:
            new_hash = reload_constitution_policy(path=staged_policy)
        except TypeError:
            new_hash = reload_constitution_policy()
        if new_hash != proposal.new_policy_hash:
            raise RuntimeError("policy_hash_mismatch_after_apply")
        journal.write_entry(
            agent_id="system",
            action="constitutional_amendment_applied",
            payload={
                "proposal_id": proposal.proposal_id,
                "approvers": ",".join(proposal.approvals),
                "new_policy_hash": new_hash,
                "version": CONSTITUTION_VERSION,
            },
        )

    @staticmethod
    def _review_latency_seconds(submitted_ts: str) -> float:
        try:
            start = datetime.fromisoformat(submitted_ts.replace("Z", "+00:00"))
        except ValueError:
            return 0.0
        now = datetime.now(timezone.utc)
        delta = (now - start).total_seconds()
        return round(max(0.0, float(delta)), 6)

    def _load_proposal(self, proposal_id: str) -> AmendmentProposal:
        path = self.proposals_dir / f"{proposal_id}.json"
        data = json.loads(read_file_deterministic(path))
        return AmendmentProposal(**data)

    def _save_proposal(self, proposal: AmendmentProposal) -> None:
        path = self.proposals_dir / f"{proposal.proposal_id}.json"
        path.write_text(json.dumps(proposal.__dict__, indent=2), encoding="utf-8")


__all__ = ["AmendmentProposal", "AmendmentEngine"]
