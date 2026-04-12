# SPDX-License-Identifier: Apache-2.0
"""Innovation #12 — Mutation Genealogy Visualization.
Property inheritance vectors on lineage graph edges.
Reveals evolutionary dead-ends vs. productive lineages.
"""
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import hashlib
import hmac

# Hardening scaffold — injected by fix/senior-deep-dive-hardening
MUGE_INV_CHAIN: str = "MUGE-INV-CHAIN"
MUGE_LEDGER_DEFAULT: str = "data/mutation_genealogy_events.jsonl"


class MutationGenealogyViolation(RuntimeError):
    """Raised when a Mutation Genealogy constitutional invariant is breached."""



@dataclass
class PropertyInheritanceVector:
    parent_epoch: str
    child_epoch: str
    correctness_delta: float
    efficiency_delta: float
    governance_delta: float
    fitness_delta: float
    introduced_capabilities: list[str] = field(default_factory=list)
    regressed_capabilities: list[str] = field(default_factory=list)

    @property
    def net_improvement(self) -> float:
        return (self.correctness_delta + self.efficiency_delta +
                self.governance_delta + self.fitness_delta) / 4.0

    @property
    def is_dead_end(self) -> bool:
        return self.net_improvement < -0.05

    @property
    def digest(self) -> str:
        payload = f"{self.parent_epoch}:{self.child_epoch}:{self.net_improvement:.4f}"
        return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()[:16]


class MutationGenealogyAnalyzer:
    """Tracks property inheritance across mutation lineage."""

    def __init__(self, ledger_path: Path = Path("data/genealogy_vectors.jsonl")):
        self.ledger_path = Path(ledger_path)
        self._vectors: list[PropertyInheritanceVector] = []
        self._load()

    def record_inheritance(self, parent_epoch: str, child_epoch: str,
                            parent_scores: dict[str, float],
                            child_scores: dict[str, float]) -> PropertyInheritanceVector:
        v = PropertyInheritanceVector(
            parent_epoch=parent_epoch, child_epoch=child_epoch,
            correctness_delta=child_scores.get("correctness", 0) - parent_scores.get("correctness", 0),
            efficiency_delta=child_scores.get("efficiency", 0) - parent_scores.get("efficiency", 0),
            governance_delta=child_scores.get("governance", 0) - parent_scores.get("governance", 0),
            fitness_delta=child_scores.get("fitness_delta", 0),
        )
        self._vectors.append(v)
        self._persist(v)
        return v

    def productive_lineages(self, min_improvement: float = 0.05) -> list[str]:
        """Epoch IDs that consistently produced improving offspring."""
        parent_improvements: dict[str, list[float]] = {}
        for v in self._vectors:
            parent_improvements.setdefault(v.parent_epoch, []).append(v.net_improvement)
        return [epoch for epoch, improvements in parent_improvements.items()
                if sum(improvements) / len(improvements) >= min_improvement]

    def dead_end_epochs(self) -> list[str]:
        """Epochs that produced no accepted descendants."""
        has_children = {v.parent_epoch for v in self._vectors}
        all_children = {v.child_epoch for v in self._vectors}
        # Dead ends: are children but never became parents
        return list(all_children - has_children)

    def evolutionary_direction(self, epoch_id: str) -> dict[str, float]:
        """Cumulative property deltas along lineage path to epoch_id."""
        path_vectors = [v for v in self._vectors if v.child_epoch == epoch_id]
        if not path_vectors:
            return {}
        totals: dict[str, float] = {"correctness": 0, "efficiency": 0,
                                     "governance": 0, "fitness": 0}
        for v in path_vectors:
            totals["correctness"] += v.correctness_delta
            totals["efficiency"] += v.efficiency_delta
            totals["governance"] += v.governance_delta
            totals["fitness"] += v.fitness_delta
        return {k: round(v, 4) for k, v in totals.items()}

    def _load(self) -> None:
        if not self.ledger_path.exists():
            return
        for line in self.ledger_path.read_text().splitlines():
            try:
                d = json.loads(line)
                self._vectors.append(PropertyInheritanceVector(**d))
            except Exception:
                pass

    def _persist(self, v: PropertyInheritanceVector) -> None:
        import dataclasses

        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger_path.open("a") as f:
            f.write(json.dumps(dataclasses.asdict(v)) + "\n")


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


__all__ = ["MutationGenealogyAnalyzer", "PropertyInheritanceVector"]
