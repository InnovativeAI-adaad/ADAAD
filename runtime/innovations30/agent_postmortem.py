# SPDX-License-Identifier: Apache-2.0
"""Innovation #17 — Agent Post-Mortem Interviews.
After governance rejection, agents explain their reasoning.
Entries become feedback and credibility signals.
"""
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import hashlib
import hmac

# Hardening scaffold — injected by fix/senior-deep-dive-hardening
AGPO_INV_CHAIN: str = "AGPO-INV-CHAIN"
AGPO_LEDGER_DEFAULT: str = "data/agent_postmortem_events.jsonl"


class AgentPostmortemViolation(RuntimeError):
    """Raised when a Agent Postmortem constitutional invariant is breached."""



@dataclass
class AgentReasoningEntry:
    agent_id: str
    mutation_id: str
    epoch_id: str
    rejection_reasons: list[str]
    agent_self_assessment: str    # why the agent thought it was a good proposal
    identified_gap: str           # what the agent thinks it missed
    proposed_correction: str      # what it would do differently
    entry_digest: str = ""

    def __post_init__(self):
        if not self.entry_digest:
            payload = f"{self.agent_id}:{self.mutation_id}:{self.identified_gap}"
            self.entry_digest = "sha256:" + hashlib.sha256(payload.encode()).hexdigest()[:16]


class AgentPostMortemSystem:
    """Records agent reasoning after governance failures."""

    def __init__(self, ledger_path: Path = Path("data/agent_postmortems.jsonl")):
        self.ledger_path = Path(ledger_path)

    def conduct_interview(self, agent_id: str, mutation_id: str,
                           epoch_id: str, rejection_reasons: list[str],
                           mutation_intent: str,
                           mutation_strategy: str) -> AgentReasoningEntry:
        """Generate a structured post-mortem from rejection context."""
        # Synthesize self-assessment based on intent + strategy
        self_assessment = (
            f"Proposed '{mutation_intent}' using strategy '{mutation_strategy}'. "
            f"Expected this would pass governance based on prior similar mutations."
        )

        # Identify gap from rejection reasons
        gaps = []
        for reason in rejection_reasons:
            if "lineage" in reason.lower():
                gaps.append("Insufficient lineage chain verification")
            elif "entropy" in reason.lower():
                gaps.append("Entropy budget miscalculated")
            elif "scope" in reason.lower():
                gaps.append("Mutation scope exceeded single-file boundary")
            elif "ast" in reason.lower():
                gaps.append("AST validity issues not caught pre-submission")
            elif "replay" in reason.lower():
                gaps.append("Replay determinism requirements not met")
            else:
                gaps.append(f"Constitutional rule violated: {reason}")

        identified_gap = "; ".join(gaps) if gaps else "Unknown — requires deeper analysis"
        correction = (
            f"Next time: verify {', '.join(rejection_reasons[:2])} "
            f"conditions before submitting. Consider increasing pre-submission "
            f"invariant checks for this mutation type."
        )

        entry = AgentReasoningEntry(
            agent_id=agent_id, mutation_id=mutation_id, epoch_id=epoch_id,
            rejection_reasons=rejection_reasons,
            agent_self_assessment=self_assessment,
            identified_gap=identified_gap,
            proposed_correction=correction,
        )
        self._persist(entry)
        return entry

    def agent_recurring_gaps(self, agent_id: str,
                               last_n: int = 20) -> dict[str, int]:
        """Find the most common gaps for an agent — calibration signal."""
        gaps: dict[str, int] = {}
        if not self.ledger_path.exists():
            return gaps
        for line in self.ledger_path.read_text().splitlines():
            try:
                d = json.loads(line)
                if d.get("agent_id") == agent_id:
                    gap = d.get("identified_gap", "")
                    gaps[gap] = gaps.get(gap, 0) + 1
            except Exception:
                pass
        return dict(sorted(gaps.items(), key=lambda x: x[1], reverse=True))

    def _persist(self, entry: AgentReasoningEntry) -> None:
        import dataclasses
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger_path.open("a") as f:
            f.write(json.dumps(dataclasses.asdict(entry)) + "\n")


# ── Chain-linkage scaffold (hardening pass — prev_digest + _append_event) ─────
import hashlib as _hashlib
import json as _json


_MODULE_PREV_DIGEST: str = "genesis"   # prev_digest chain head for this module


def _append_event(event: dict, ledger_path: str = "") -> None:
    """Module-level append-only JSONL event stub [CED-INV-AUDIT, CED-INV-CHAIN].

    Writes a chain-linked record to ledger_path (or discards if empty).
    Full integration deferred to per-module deep-dive phase.
    """
    global _MODULE_PREV_DIGEST
    if not ledger_path:
        return
    import dataclasses as _dc
    from pathlib import Path as _Path
    row = event if isinstance(event, dict) else (
        _dc.asdict(event) if hasattr(event, '__dataclass_fields__') else {}
    )
    row["prev_digest"] = _MODULE_PREV_DIGEST
    digest_payload = _json.dumps(row, sort_keys=True).encode()
    row["event_digest"] = "sha256:" + _hashlib.sha256(digest_payload).hexdigest()
    p = _Path(ledger_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(_json.dumps(row, sort_keys=True) + "\n")
    _MODULE_PREV_DIGEST = row["event_digest"]


__all__ = ["AgentPostMortemSystem", "AgentReasoningEntry"]
