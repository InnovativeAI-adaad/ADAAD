# SPDX-License-Identifier: Apache-2.0
"""CLI for constitutional amendment workflow."""

from __future__ import annotations

import argparse
from pathlib import Path

from runtime.constitution import POLICY_HASH
from runtime.governance.amendment import AmendmentEngine
from runtime.governance.policy_validator import PolicyValidator


def main() -> None:
    parser = argparse.ArgumentParser(description="Constitution amendment workflow")
    subparsers = parser.add_subparsers(dest="command", required=True)

    propose = subparsers.add_parser("propose")
    propose.add_argument("--policy-file", type=Path, required=True)
    propose.add_argument("--rationale", required=True)
    propose.add_argument("--proposer", default="human")

    approve = subparsers.add_parser("approve")
    approve.add_argument("proposal_id")
    approve.add_argument("--approver", required=True)

    reject = subparsers.add_parser("reject")
    reject.add_argument("proposal_id")
    reject.add_argument("--rejector", required=True)

    args = parser.parse_args()
    engine = AmendmentEngine()

    if args.command == "propose":
        policy_text = args.policy_file.read_text(encoding="utf-8")
        validation = PolicyValidator().validate(policy_text)
        if not validation.valid:
            print("Policy validation failed:")
            for err in validation.errors:
                print(f"- {err}")
            raise SystemExit(1)
        proposal = engine.propose_amendment(
            proposer=args.proposer,
            new_policy_text=policy_text,
            rationale=args.rationale,
            old_policy_hash=POLICY_HASH,
        )
        print(f"Proposal created: {proposal.proposal_id}")
    elif args.command == "approve":
        proposal = engine.approve_amendment(args.proposal_id, args.approver)
        print(f"Status: {proposal.status}")
    elif args.command == "reject":
        proposal = engine.reject_amendment(args.proposal_id, args.rejector)
        print(f"Status: {proposal.status}")


if __name__ == "__main__":
    main()
