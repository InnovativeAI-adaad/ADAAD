# SPDX-License-Identifier: Apache-2.0
"""Innovation #6 — Counterfactual Fitness Simulation.

Before scoring a mutation, simulate what the system would look like
if the last N accepted mutations had never happened.
Score the proposal against that counterfactual baseline.
"""
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import hashlib
import hmac

# Hardening scaffold — injected by fix/senior-deep-dive-hardening
COFI_INV_CHAIN: str = "COFI-INV-CHAIN"
COFI_LEDGER_DEFAULT: str = "data/counterfactual_fitness_events.jsonl"


class CounterfactualFitnessViolation(RuntimeError):
    """Raised when a Counterfactual Fitness constitutional invariant is breached."""



COUNTERFACTUAL_DEPTH: int = 5  # how many recent mutations to undo

@dataclass
class CounterfactualResult:
    mutation_id: str
    actual_baseline_fitness: float
    counterfactual_baseline_fitness: float
    delta: float          # counterfactual - actual (positive = inflated baseline)
    adjusted_proposal_score: float
    inflation_detected: bool
    digest: str = ""

    def __post_init__(self):
        if not self.digest:
            payload = f"{self.mutation_id}:{self.delta:.4f}"
            self.digest = "sha256:" + hashlib.sha256(payload.encode()).hexdigest()[:16]


class CounterfactualFitnessSimulator:
    """Scores proposals relative to counterfactual baselines."""

    def __init__(self, depth: int = COUNTERFACTUAL_DEPTH,
                 inflation_threshold: float = 0.10):
        self.depth = depth
        self.inflation_threshold = inflation_threshold

    def evaluate(self, mutation_id: str,
                 proposal_score: float,
                 actual_baseline: float,
                 recent_accepted_deltas: list[float]) -> CounterfactualResult:
        """
        recent_accepted_deltas: fitness_deltas of last N accepted mutations.
        Counterfactual baseline = actual_baseline - sum(recent deltas).
        """
        recent = recent_accepted_deltas[-self.depth:] if recent_accepted_deltas else []
        cumulative_recent_gain = sum(recent)
        counterfactual_baseline = max(0.0, actual_baseline - cumulative_recent_gain)

        # Proposal looks better in context of inflated baseline
        baseline_inflation = actual_baseline - counterfactual_baseline
        inflation_detected = baseline_inflation > self.inflation_threshold

        # Adjust proposal score: penalize if baseline is inflated
        adjusted = proposal_score
        if inflation_detected:
            # Scale down by inflation ratio
            ratio = counterfactual_baseline / max(0.01, actual_baseline)
            adjusted = round(proposal_score * (0.85 + 0.15 * ratio), 4)

        return CounterfactualResult(
            mutation_id=mutation_id,
            actual_baseline_fitness=round(actual_baseline, 4),
            counterfactual_baseline_fitness=round(counterfactual_baseline, 4),
            delta=round(baseline_inflation, 4),
            adjusted_proposal_score=adjusted,
            inflation_detected=inflation_detected,
        )


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


__all__ = ["CounterfactualFitnessSimulator", "CounterfactualResult",
           "COUNTERFACTUAL_DEPTH"]
