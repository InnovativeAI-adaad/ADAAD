# SPDX-License-Identifier: Apache-2.0
"""Innovation #2 — Constitutional Tension Resolver.

Detects when two constitutional rules disagree on the same mutation.
Records contradictions. When a rule is consistently overridden 20+ epochs,
proposes formal resolution or retirement.
"""
from __future__ import annotations
import hashlib, json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import hashlib
import hmac

# Hardening scaffold — injected by fix/senior-deep-dive-hardening
COTE_INV_CHAIN: str = "COTE-INV-CHAIN"
COTE_LEDGER_DEFAULT: str = "data/constitutional_tension_events.jsonl"


class ConstitutionalTensionViolation(RuntimeError):
    """Raised when a Constitutional Tension constitutional invariant is breached."""



TENSION_THRESHOLD: int = 20  # epochs of consistent disagreement triggers proposal
OVERRIDE_RATIO: float = 0.80  # rule_A overrides rule_B this fraction of the time

@dataclass
class RuleTension:
    rule_a: str       # winning (blocking) rule
    rule_b: str       # losing (advisory/warning) rule
    conflict_count: int = 0
    first_seen_epoch: str = ""
    last_seen_epoch: str = ""
    example_mutation_ids: list[str] = field(default_factory=list)

    @property
    def digest(self) -> str:
        payload = f"{self.rule_a}:{self.rule_b}:{self.conflict_count}"
        return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()[:16]


@dataclass
class TensionResolutionProposal:
    proposal_id: str
    rule_a: str
    rule_b: str
    tension_count: int
    proposed_action: str   # "retire_rule_b" | "merge_rules" | "adjust_thresholds"
    rationale: str
    status: str = "pending_human_review"


class ConstitutionalTensionResolver:
    """Tracks rule disagreements and proposes formal constitutional resolution."""

    def __init__(self, ledger_path: Path = Path("data/constitutional_tensions.jsonl")):
        self.ledger_path = Path(ledger_path)
        self._tensions: dict[str, RuleTension] = {}

    def record_verdict(self, mutation_id: str, epoch_id: str,
                       blocking_rules: list[str],
                       overridden_rules: list[str]) -> list[RuleTension]:
        """Record rules that disagreed on this mutation."""
        new_tensions = []
        for blocker in blocking_rules:
            for overridden in overridden_rules:
                key = f"{blocker}>{overridden}"
                if key not in self._tensions:
                    self._tensions[key] = RuleTension(
                        rule_a=blocker, rule_b=overridden,
                        first_seen_epoch=epoch_id)
                t = self._tensions[key]
                t.conflict_count += 1
                t.last_seen_epoch = epoch_id
                if mutation_id not in t.example_mutation_ids:
                    t.example_mutation_ids = (t.example_mutation_ids + [mutation_id])[-5:]
                new_tensions.append(t)
        self._persist_tensions(new_tensions)
        return new_tensions

    def check_for_proposals(self) -> list[TensionResolutionProposal]:
        """Return resolution proposals for tensions exceeding threshold."""
        proposals = []
        for key, tension in self._tensions.items():
            if tension.conflict_count >= TENSION_THRESHOLD:
                p = TensionResolutionProposal(
                    proposal_id=f"TENSION-{tension.digest}",
                    rule_a=tension.rule_a,
                    rule_b=tension.rule_b,
                    tension_count=tension.conflict_count,
                    proposed_action="adjust_thresholds",
                    rationale=(
                        f"Rule '{tension.rule_a}' has overridden '{tension.rule_b}' "
                        f"{tension.conflict_count} times since epoch "
                        f"{tension.first_seen_epoch}. Consider merging or retiring "
                        f"'{tension.rule_b}' to resolve constitutional tension."
                    ),
                )
                proposals.append(p)
        return proposals

    def summary(self) -> dict[str, Any]:
        return {
            "total_tensions_tracked": len(self._tensions),
            "above_threshold": sum(1 for t in self._tensions.values()
                                    if t.conflict_count >= TENSION_THRESHOLD),
            "top_tensions": [
                {"key": k, "count": t.conflict_count}
                for k, t in sorted(self._tensions.items(),
                                    key=lambda x: x[1].conflict_count, reverse=True)[:5]
            ],
        }

    def _persist_tensions(self, tensions: list[RuleTension]) -> None:
        if not tensions:
            return
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        import dataclasses
        with self.ledger_path.open("a") as f:
            for t in tensions:
                f.write(json.dumps(dataclasses.asdict(t)) + "\n")


__all__ = ["ConstitutionalTensionResolver", "RuleTension",
           "TensionResolutionProposal", "TENSION_THRESHOLD"]
