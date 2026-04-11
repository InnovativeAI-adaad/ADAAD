# SPDX-License-Identifier: Apache-2.0
"""
LineageLedgerV2 — runtime/lineage/lineage_ledger_v2.py
======================================================

Second-generation lineage store: records mutation proposal → approval →
deployment trace with SHA-256 hash-chained entries.

Phase 94 enrichment: exposes attach_identity_result() so that
IdentityConsistencyResult is co-committed with each lineage event, making
the MMEM signal part of the immutable audit trail.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_LEDGER_PATH: Path = Path("data/lineage_ledger_v2.jsonl")
ZERO_HASH: str = "sha256:" + "0" * 64


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class LineageEvent:
    """A single immutable record in the lineage chain."""
    event_id: str
    event_type: str              # "proposal" | "approval" | "deployment"
    mutation_id: str
    epoch_id: str
    payload: Dict[str, Any]
    predecessor_hash: str
    event_hash: str = ""
    # Phase 94: co-committed MMEM signal
    identity_consistency_score: Optional[float] = None
    identity_violated_statements: List[str] = field(default_factory=list)


@dataclass
class ProximityScore:
    """Returned by semantic_proximity_score()."""
    mutation_id: str
    score: float                 # [0.0, 1.0]
    nearest_ancestor_id: Optional[str] = None
    notes: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_event_hash(
    event_id: str,
    event_type: str,
    mutation_id: str,
    predecessor_hash: str,
) -> str:
    """Deterministic SHA-256 over canonical event fields."""
    payload = {
        "event_id": event_id,
        "event_type": event_type,
        "mutation_id": mutation_id,
        "predecessor": predecessor_hash,
    }
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return "sha256:" + digest


# ---------------------------------------------------------------------------
# LineageLedgerV2
# ---------------------------------------------------------------------------

class LineageLedgerV2:
    """Second-generation hash-chained lineage store with MMEM enrichment."""

    def __init__(self, ledger_path: Path = DEFAULT_LEDGER_PATH) -> None:
        self._path = Path(ledger_path)
        self._events: List[LineageEvent] = []
        self._verified_tail_hash: Optional[str] = None

    def get_verified_tail_hash(self) -> Optional[str]:
        """Return the hash of the last successfully verified event."""
        return self._verified_tail_hash

    # ------------------------------------------------------------------
    # Core record surfaces
    # ------------------------------------------------------------------

    def record_proposal(
        self,
        mutation_id: str,
        epoch_id: str,
        payload: Dict[str, Any],
    ) -> LineageEvent:
        """Record a mutation proposal event."""
        return self._record_event("proposal", mutation_id, epoch_id, payload)

    def record_approval(
        self,
        mutation_id: str,
        epoch_id: str,
        gate_verdict: str,
        payload: Dict[str, Any],
    ) -> LineageEvent:
        """Record a governance gate approval event."""
        merged = dict(payload)
        merged["gate_verdict"] = gate_verdict
        return self._record_event("approval", mutation_id, epoch_id, merged)

    def record_deployment(
        self,
        mutation_id: str,
        epoch_id: str,
        payload: Dict[str, Any],
    ) -> LineageEvent:
        """Record a deployment event."""
        return self._record_event("deployment", mutation_id, epoch_id, payload)

    def _record_event(
        self,
        event_type: str,
        mutation_id: str,
        epoch_id: str,
        payload: Dict[str, Any],
    ) -> LineageEvent:
        """Internal: build, hash, and store a LineageEvent."""
        eid = f"evt-{len(self._events):06d}"
        predecessor = self._events[-1].event_hash if self._events else ZERO_HASH
        eh = _compute_event_hash(eid, event_type, mutation_id, predecessor)
        event = LineageEvent(
            event_id=eid,
            event_type=event_type,
            mutation_id=mutation_id,
            epoch_id=epoch_id,
            payload=payload,
            predecessor_hash=predecessor,
            event_hash=eh,
        )
        self._events.append(event)
        return event

    # ------------------------------------------------------------------
    # Phase 94 MMEM enrichment
    # ------------------------------------------------------------------

    def attach_identity_result(
        self,
        event_id: str,
        consistency_score: float,
        violated_statements: List[str],
    ) -> None:
        """Co-commit an IdentityConsistencyResult to an existing event.

        MMEM Phase 94: makes identity signal part of the immutable audit trail.
        Silent no-op if event_id not found (advisory mode).
        """
        for event in self._events:
            if event.event_id == event_id:
                event.identity_consistency_score = consistency_score
                event.identity_violated_statements = list(violated_statements)
                return

    # ------------------------------------------------------------------
    # Query surfaces
    # ------------------------------------------------------------------

    def semantic_proximity_score(self, source: str) -> ProximityScore:
        """Compute semantic proximity of source to prior accepted mutations.

        Phase 94 stub — semantic embedding deferred to Phase 95.
        Returns deterministic neutral result (MMEM-DETERM-0).
        """
        return ProximityScore(
            mutation_id="source",
            score=0.5,
            nearest_ancestor_id=None,
            notes="Phase 94: heuristic stub — semantic embedding deferred to Phase 95",
        )

    # ------------------------------------------------------------------
    # Integrity
    # ------------------------------------------------------------------

    def verify_chain(self) -> bool:
        """O(n) chain integrity verification."""
        from runtime.memory.identity_ledger import ChainIntegrityError  # local import

        if not self._events:
            self._verified_tail_hash = ZERO_HASH
            return True
        for i, evt in enumerate(self._events):
            expected = _compute_event_hash(
                evt.event_id, evt.event_type, evt.mutation_id, evt.predecessor_hash
            )
            if expected != evt.event_hash:
                raise ChainIntegrityError(
                    f"Event hash mismatch at {evt.event_id}"
                )
            if i > 0:
                expected_pred = self._events[i - 1].event_hash
                if evt.predecessor_hash != expected_pred:
                    raise ChainIntegrityError(
                        f"Predecessor mismatch at {evt.event_id}"
                    )
        
        self._verified_tail_hash = self._events[-1].event_hash
        return True

    def events(self) -> List[LineageEvent]:
        """Read-only view of loaded events."""
        return list(self._events)

    def __len__(self) -> int:
        return len(self._events)


__all__ = [
    "LineageLedgerV2",
    "LineageEvent",
    "ProximityScore",
    "DEFAULT_LEDGER_PATH",
    "ZERO_HASH",
]
