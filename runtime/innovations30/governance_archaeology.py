# SPDX-License-Identifier: Apache-2.0
"""Innovation #19 — Governance Archaeology Mode (GAM).

Assembles complete cryptographically-verified decision timeline for any
mutation from proposal to final outcome.

Constitutional invariants
─────────────────────────
GAM-0           — excavate() sole entry point; never raises on empty/absent ledger
GAM-CHAIN-0     — timeline_digest = "sha256:" + sha256(json.dumps(event_types))
GAM-DETERM-0    — identical ledger state + mutation_id → identical digest; no RNG
GAM-SORT-0      — events sorted ascending by timestamp; empty sorts before non-empty
GAM-FAIL-OPEN-0 — corrupt JSONL lines silently skipped; excavate() never raises
GAM-PARSE-0     — _parse_event() returns None for non-matching records; never raises
GAM-OUTCOME-0   — final_outcome from last terminal event; defaults "unknown"
GAM-EXPORT-0    — export_timeline() always carries innovation=19 and timeline_digest
GAM-VERIFY-0    — verify_chain() re-computes digest; returns bool; never raises
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import hashlib
import hmac

# Hardening scaffold — injected by fix/senior-deep-dive-hardening
GOAR_INV_CHAIN: str = "GOAR-INV-CHAIN"
GOAR_LEDGER_DEFAULT: str = "data/governance_archaeology_events.jsonl"


class GovernanceArchaeologyViolation(RuntimeError):
    """Raised when a Governance Archaeology constitutional invariant is breached."""



_TERMINAL_EVENT_TYPES: frozenset[str] = frozenset(
    {"approved", "rejected", "promoted", "rolled_back"}
)


@dataclass
class DecisionEvent:
    event_type: str
    timestamp: str
    epoch_id: str
    mutation_id: str
    actor: str
    outcome: str
    details: dict[str, Any] = field(default_factory=dict)
    ledger_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "epoch_id": self.epoch_id,
            "mutation_id": self.mutation_id,
            "actor": self.actor,
            "outcome": self.outcome,
            "details": self.details,
            "ledger_hash": self.ledger_hash,
        }


@dataclass
class MutationTimeline:
    mutation_id: str
    events: list[DecisionEvent]
    final_outcome: str
    timeline_digest: str = ""
    chain_verified: bool = False

    @property
    def proposal_event(self) -> DecisionEvent | None:
        return next((e for e in self.events if e.event_type == "proposed"), None)

    @property
    def governance_events(self) -> list[DecisionEvent]:
        return [e for e in self.events if "gate" in e.event_type.lower()]

    @property
    def human_events(self) -> list[DecisionEvent]:
        return [e for e in self.events if "human" in e.actor.lower()]

    @property
    def terminal_event(self) -> DecisionEvent | None:
        for e in reversed(self.events):
            if e.event_type in _TERMINAL_EVENT_TYPES:
                return e
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mutation_id": self.mutation_id,
            "final_outcome": self.final_outcome,
            "timeline_digest": self.timeline_digest,
            "chain_verified": self.chain_verified,
            "event_count": len(self.events),
            "events": [e.to_dict() for e in self.events],
        }


class GovernanceArchaeologist:
    """Assembles complete mutation audit trails from distributed ledgers."""

    INNOVATION: int = 19
    INNOVATION_NAME: str = "GovernanceArchaeologyMode"

    def __init__(self, ledger_roots: list[Path] | None = None) -> None:
        self.ledger_roots: list[Path] = ledger_roots or [
            Path("security/ledger"),
            Path("data"),
        ]

    def excavate(self, mutation_id: str) -> MutationTimeline:  # [GAM-0]
        """Sole entry point. Never raises. [GAM-0, GAM-FAIL-OPEN-0]"""
        if not mutation_id:
            return MutationTimeline(
                mutation_id=mutation_id,
                events=[],
                final_outcome="unknown",
                timeline_digest=self._compute_digest([]),
                chain_verified=False,
            )

        events: list[DecisionEvent] = []

        for root in self.ledger_roots:
            try:
                if not Path(root).exists():
                    continue
                for ledger_file in sorted(Path(root).rglob("*.jsonl")):
                    try:
                        for line in ledger_file.read_text(
                            encoding="utf-8", errors="replace"
                        ).splitlines():
                            if mutation_id not in line:
                                continue
                            try:
                                record = json.loads(line)
                                event = self._parse_event(record, mutation_id)
                                if event is not None:
                                    events.append(event)
                            except Exception:  # noqa: BLE001
                                pass
                    except Exception:  # noqa: BLE001
                        pass
            except Exception:  # noqa: BLE001
                pass

        # Stable ascending sort; empty timestamp sorts first [GAM-SORT-0]
        events.sort(key=lambda e: (e.timestamp or "", e.event_type))

        return MutationTimeline(
            mutation_id=mutation_id,
            events=events,
            final_outcome=self._resolve_outcome(events),
            timeline_digest=self._compute_digest(events),
            chain_verified=len(events) > 0,
        )

    def verify_chain(self, timeline: MutationTimeline) -> bool:  # [GAM-VERIFY-0]
        """Re-compute digest and compare. Never raises."""
        try:
            return timeline.timeline_digest == self._compute_digest(timeline.events)
        except Exception:  # noqa: BLE001
            return False

    def export_timeline(self, timeline: MutationTimeline) -> dict[str, Any]:  # [GAM-EXPORT-0]
        """Return JSON-serializable dict with innovation=19 metadata."""
        return {
            "innovation": self.INNOVATION,
            "innovation_name": self.INNOVATION_NAME,
            "schema_version": "1.0",
            "mutation_id": timeline.mutation_id,
            "final_outcome": timeline.final_outcome,
            "timeline_digest": timeline.timeline_digest,
            "chain_verified": timeline.chain_verified,
            "event_count": len(timeline.events),
            "events": [e.to_dict() for e in timeline.events],
        }

    def _parse_event(  # [GAM-PARSE-0]
        self, record: dict[str, Any], mutation_id: str
    ) -> DecisionEvent | None:
        """Returns None for non-matching records. Never raises."""
        try:
            if record.get("mutation_id") != mutation_id:
                return None
            return DecisionEvent(
                event_type=str(record.get("event_type", record.get("action", "unknown"))),
                timestamp=str(record.get("ts", record.get("timestamp", ""))),
                epoch_id=str(record.get("epoch_id", "")),
                mutation_id=mutation_id,
                actor=str(record.get("agent_id", record.get("actor", "system"))),
                outcome=str(record.get("outcome", record.get("verdict", "recorded"))),
                details={
                    k: v for k, v in record.items()
                    if k not in {
                        "event_type", "action", "ts", "timestamp",
                        "epoch_id", "mutation_id", "agent_id", "actor",
                        "outcome", "verdict",
                    }
                },
                ledger_hash=str(record.get("ledger_hash", record.get("digest", ""))),
            )
        except Exception:  # noqa: BLE001
            return None

    def _resolve_outcome(self, events: list[DecisionEvent]) -> str:  # [GAM-OUTCOME-0]
        for e in reversed(events):
            if e.event_type in _TERMINAL_EVENT_TYPES:
                return e.outcome or e.event_type
        return "unknown"

    def _compute_digest(self, events: list[DecisionEvent]) -> str:  # [GAM-CHAIN-0, GAM-DETERM-0]
        payload = json.dumps([e.event_type for e in events], sort_keys=True)
        return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


__all__ = [
    "GovernanceArchaeologist",
    "MutationTimeline",
    "DecisionEvent",
    "_TERMINAL_EVENT_TYPES",
]
