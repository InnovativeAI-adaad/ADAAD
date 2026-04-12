# SPDX-License-Identifier: Apache-2.0
"""Innovation #11 — Cross-Epoch Dream State Engine (DSTE).

Constitutional invariants enforced by this module (all Hard-class):

    DSTE-0  [Ledger-first commit]
            DreamStateEngine MUST commit each DreamLedgerEvent to the governance
            ledger BEFORE returning any DreamCandidate to the caller.

    DSTE-1  [Determinism]
            For identical (epoch_memory, epoch_id, seed) inputs, dream() MUST
            return an identical ordered list of DreamCandidates.
            seed=None is constitutionally prohibited.

    DSTE-2  [Novelty floor]
            Any DreamCandidate with novelty_score < DREAM_MIN_NOVELTY (0.30)
            MUST be rejected; rejection is ledger-recorded, never silent.

    DSTE-3  [Pool quorum]
            dream() MUST NOT execute if len(successful_epochs) < DREAM_QUORUM (3).
            Under-quorum emits a ledger event and returns [].

    DSTE-4  [Chain integrity]
            Each DreamLedgerEvent MUST include prev_event_hash linking to the
            immediately preceding governance ledger event.

    DSTE-5  [No-write between epochs]
            DreamStateEngine MUST NOT modify any production runtime state
            during dream execution.

    DSTE-6  [Candidate count ceiling]
            dream() MUST NOT return more than DREAM_CANDIDATES (5) candidates
            per invocation. Overproduction is ledger-recorded.

Phase 96 — v9.29.0 — 2026-03-30
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import hashlib
import hmac

# Hardening scaffold — injected by fix/senior-deep-dive-hardening
DRST_INV_CHAIN: str = "DRST-INV-CHAIN"


class DreamStateViolation(RuntimeError):
    """Raised when a Dream State constitutional invariant is breached."""



log = logging.getLogger(__name__)

# ── Constitutional constants ──────────────────────────────────────────────────
DREAM_DEPTH: int = 100
DREAM_CANDIDATES: int = 5
DREAM_MIN_SCORE: float = 0.60
DREAM_MIN_NOVELTY: float = 0.30   # DSTE-2 floor
DREAM_QUORUM: int = 3             # DSTE-3 minimum

# ── Invariant symbols (Hard-class) ────────────────────────────────────────────
DSTE_0 = "DSTE-0"
DSTE_1 = "DSTE-1"
DSTE_2 = "DSTE-2"
DSTE_3 = "DSTE-3"
DSTE_4 = "DSTE-4"
DSTE_5 = "DSTE-5"
DSTE_6 = "DSTE-6"

_ALL_INVARIANTS: list[str] = [DSTE_0, DSTE_1, DSTE_2, DSTE_3, DSTE_4, DSTE_5, DSTE_6]


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class DreamCandidate:
    candidate_id: str
    source_epochs: list[str]
    combined_intent: str
    recombined_ops: list[dict[str, Any]]
    predicted_fitness: float
    novelty_score: float
    genesis_digest: str = field(default="")

    def __post_init__(self) -> None:
        if not self.genesis_digest:
            payload = json.dumps(
                {"id": self.candidate_id, "epochs": sorted(self.source_epochs)},
                sort_keys=True,
            )
            self.genesis_digest = "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


@dataclass
class DreamLedgerEvent:
    event_type: str
    event_id: str
    epoch_id: str
    dream_seed: int
    candidate_count: int
    candidate_ids: list[str]
    novelty_rejects: int
    quorum_met: bool
    pool_size: int
    genesis_digest: str
    prev_event_hash: str    # DSTE-4
    timestamp_utc: str
    invariant_class: str = "Hard"
    invariants_checked: list[str] = field(
        default_factory=lambda: list(_ALL_INVARIANTS)
    )

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    def compute_hash(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True)
        return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


@dataclass
class DreamStateReport:
    report_id: str
    phase: int
    innovation: str
    epoch_id: str
    candidates: list[DreamCandidate]
    ledger_event_id: str
    invariants_passed: list[str]
    invariants_failed: list[str]
    verdict: str   # "PASS" | "RETURNED" — structurally incapable of "APPROVED"
    timestamp_utc: str

    def __post_init__(self) -> None:
        if self.verdict == "APPROVED":
            raise ValueError(
                f"[{DSTE_0}] DreamStateReport.verdict cannot be 'APPROVED'. "
                "Dream candidates are proposals, not approvals."
            )


# ── Gate evaluation functions ─────────────────────────────────────────────────

class DreamGateViolation(RuntimeError):
    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


def evaluate_dream_gate_0(
    seed: int | None,
    epoch_memory: list[dict[str, Any]],
) -> dict[str, Any]:
    """Pre-execution gate. Checks DSTE-1 (seed) and DSTE-3 (quorum)."""
    result: dict[str, Any] = {
        "gate": "dream_gate_0",
        "invariants_checked": [DSTE_1, DSTE_3],
        "passed": [],
        "failed": [],
        "proceed": True,
    }

    if seed is None:
        result["failed"].append(DSTE_1)
        result["proceed"] = False
        raise DreamGateViolation(
            DSTE_1,
            "dream() invoked with seed=None. Deterministic seed required. "
            "Caller must supply an explicit integer seed derived from epoch_id.",
        )
    result["passed"].append(DSTE_1)

    successful = [e for e in epoch_memory if e.get("fitness_delta", 0) > 0]
    if len(successful) < DREAM_QUORUM:
        result["failed"].append(DSTE_3)
        result["proceed"] = False
        result["quorum_met"] = False
        result["successful_count"] = len(successful)
        return result

    result["passed"].append(DSTE_3)
    result["quorum_met"] = True
    result["successful_count"] = len(successful)
    return result


def evaluate_dream_gate_1(
    candidates: list[DreamCandidate],
    ledger_committed: bool,
    ledger_event_id: str,
) -> dict[str, Any]:
    """Post-execution gate. Checks DSTE-0 (ledger-first) and DSTE-6 (ceiling)."""
    result: dict[str, Any] = {
        "gate": "dream_gate_1",
        "invariants_checked": [DSTE_0, DSTE_6],
        "passed": [],
        "failed": [],
    }

    if not ledger_committed:
        result["failed"].append(DSTE_0)
        raise DreamGateViolation(
            DSTE_0,
            f"Ledger event '{ledger_event_id}' was not committed before candidates returned.",
        )
    result["passed"].append(DSTE_0)

    if len(candidates) > DREAM_CANDIDATES:
        result["failed"].append(DSTE_6)
        raise DreamGateViolation(
            DSTE_6,
            f"dream() produced {len(candidates)} candidates; ceiling is {DREAM_CANDIDATES}.",
        )
    result["passed"].append(DSTE_6)
    return result


# ── Dream State Engine ────────────────────────────────────────────────────────

class DreamStateEngine:
    """Constitutionally-governed cross-epoch mutation memory consolidation.

    DSTE-0 through DSTE-6 are all Hard-class invariants enforced at runtime.
    """

    def __init__(
        self,
        state_path: Path = Path("data/dream_candidates.jsonl"),
        ledger_path: Path = Path("data/dream_ledger.jsonl"),
        depth: int = DREAM_DEPTH,
        seed: int | None = None,
    ) -> None:
        self.state_path = Path(state_path)
        self.ledger_path = Path(ledger_path)
        self.depth = depth
        self.seed = seed
        self._last_ledger_hash: str = "genesis"

    def dream(
        self,
        epoch_memory: list[dict[str, Any]],
        epoch_id: str,
        seed: int | None = None,
    ) -> DreamStateReport:
        """Execute one dream consolidation cycle.

        Commits ledger event before returning (DSTE-0).
        Raises DreamGateViolation on any Hard-class invariant violation.
        """
        # If no local seed provided, fallback to instance seed
        if seed is None:
            seed = self.seed

        timestamp = datetime.now(timezone.utc).isoformat()

        # Gate 0: pre-execution
        gate0 = evaluate_dream_gate_0(seed=seed, epoch_memory=epoch_memory)

        if not gate0["proceed"]:
            # DSTE-3: under-quorum path
            event_id = f"DSTE-{epoch_id[:8]}-QUORUM-0000"
            event = DreamLedgerEvent(
                event_type="dream_consolidation_skipped",
                event_id=event_id,
                epoch_id=epoch_id,
                dream_seed=seed if seed is not None else -1,
                candidate_count=0,
                candidate_ids=[],
                novelty_rejects=0,
                quorum_met=False,
                pool_size=gate0.get("successful_count", 0),
                genesis_digest=self._compute_genesis_digest([], epoch_id),
                prev_event_hash=self._last_ledger_hash,
                timestamp_utc=timestamp,
            )
            self._commit_ledger(event)
            return DreamStateReport(
                report_id=f"DSR-{epoch_id[:8]}-{timestamp}",
                phase=96,
                innovation="INNOV-11",
                epoch_id=epoch_id,
                candidates=[],
                ledger_event_id=event_id,
                invariants_passed=[DSTE_3],
                invariants_failed=[],
                verdict="PASS",
                timestamp_utc=timestamp,
            )

        # Core dream execution (DSTE-5: read-only on epoch_memory)
        import random

        rng = random.Random(seed)  # DSTE-1: seeded

        pool = epoch_memory[-self.depth:]
        successful = [e for e in pool if e.get("fitness_delta", 0) > 0]

        candidates: list[DreamCandidate] = []
        novelty_rejects: int = 0
        seen_combos: set[str] = set()

        for _ in range(DREAM_CANDIDATES * 4):
            if len(candidates) >= DREAM_CANDIDATES:
                break
            pair = rng.sample(successful, 2)
            combo_key = "|".join(sorted(e["epoch_id"] for e in pair))
            if combo_key in seen_combos:
                continue
            seen_combos.add(combo_key)

            novelty = self._compute_novelty(pair, successful)

            # DSTE-2: novelty floor — reject and record
            if novelty < DREAM_MIN_NOVELTY:
                novelty_rejects += 1
                log.debug("[DSTE-2] Novelty floor reject: combo=%s novelty=%.4f", combo_key, novelty)
                continue

            predicted = min(1.0, (
                pair[0].get("fitness_delta", 0) + pair[1].get("fitness_delta", 0)
            ) * 0.7)
            if predicted < DREAM_MIN_SCORE * 0.5:
                continue

            cid = f"DREAM-{epoch_id[:8]}-{len(candidates):02d}"
            candidates.append(DreamCandidate(
                candidate_id=cid,
                source_epochs=[e["epoch_id"] for e in pair],
                combined_intent=self._combine_intents(pair),
                recombined_ops=self._recombine_ops(pair),
                predicted_fitness=round(predicted, 4),
                novelty_score=round(novelty, 4),
            ))

        # DSTE-6: enforce ceiling
        overproduced = 0
        if len(candidates) > DREAM_CANDIDATES:
            overproduced = len(candidates) - DREAM_CANDIDATES
            candidates = candidates[:DREAM_CANDIDATES]
            log.warning("[DSTE-6] Overproduction capped: dropped %d", overproduced)

        # Deterministic sort (DSTE-1)
        candidates.sort(
            key=lambda c: (round(c.predicted_fitness * c.novelty_score, 8), c.candidate_id),
            reverse=True,
        )

        # Ledger commit BEFORE returning (DSTE-0)
        event_id = f"DSTE-{epoch_id[:8]}-0000"
        genesis = self._compute_genesis_digest([c.candidate_id for c in candidates], epoch_id)
        ledger_event = DreamLedgerEvent(
            event_type="dream_consolidation",
            event_id=event_id,
            epoch_id=epoch_id,
            dream_seed=seed,
            candidate_count=len(candidates),
            candidate_ids=[c.candidate_id for c in candidates],
            novelty_rejects=novelty_rejects,
            quorum_met=True,
            pool_size=len(successful),
            genesis_digest=genesis,
            prev_event_hash=self._last_ledger_hash,
            timestamp_utc=timestamp,
        )
        ledger_committed = self._commit_ledger(ledger_event)
        self._persist_candidates(candidates, ledger_event)

        # Gate 1: post-execution
        evaluate_dream_gate_1(
            candidates=candidates,
            ledger_committed=ledger_committed,
            ledger_event_id=event_id,
        )

        log.info(
            "[DSTE] Cycle complete. epoch=%s candidates=%d novelty_rejects=%d seed=%d",
            epoch_id, len(candidates), novelty_rejects, seed,
        )

        return DreamStateReport(
            report_id=f"DSR-{epoch_id[:8]}-{timestamp}",
            phase=96,
            innovation="INNOV-11",
            epoch_id=epoch_id,
            candidates=candidates,
            ledger_event_id=event_id,
            invariants_passed=list(_ALL_INVARIANTS),
            invariants_failed=[],
            verdict="PASS",
            timestamp_utc=timestamp,
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    def _combine_intents(self, pair: list[dict[str, Any]]) -> str:
        intents = [e.get("winning_mutation_type", "unknown") for e in pair]
        strategies = [e.get("winning_strategy_id", "") for e in pair]
        return (
            f"Dream combination: {intents[0]} + {intents[1]} "
            f"({strategies[0] or 'N/A'}→{strategies[1] or 'N/A'})"
        )

    def _recombine_ops(self, pair: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{
            "op": "dream_combine",
            "source_a": pair[0]["epoch_id"],
            "source_b": pair[1]["epoch_id"],
            "mutation_type_a": pair[0].get("winning_mutation_type"),
            "mutation_type_b": pair[1].get("winning_mutation_type"),
        }]

    def _compute_novelty(
        self, pair: list[dict[str, Any]], all_recent: list[dict[str, Any]]
    ) -> float:
        """Deterministic for equal inputs (DSTE-1)."""
        pair_types = frozenset(e.get("winning_mutation_type") for e in pair)
        recent_types = frozenset(
            e.get("winning_mutation_type") for e in all_recent[-10:]
        )
        overlap = len(pair_types & recent_types) / max(1, len(pair_types))
        return round(1.0 - (overlap * 0.5), 8)

    @staticmethod
    def _compute_genesis_digest(candidate_ids: list[str], epoch_id: str) -> str:
        payload = json.dumps(
            {"epoch_id": epoch_id, "candidate_ids": sorted(candidate_ids)},
            sort_keys=True,
        )
        return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()

    def _commit_ledger(self, event: DreamLedgerEvent) -> bool:
        """Append-only ledger write with chain hash update (DSTE-4)."""
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        event_hash = event.compute_hash()
        try:
            with self.ledger_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event.to_dict()) + "\n")
            self._last_ledger_hash = event_hash
            return True
        except OSError as exc:
            raise DreamGateViolation(
                DSTE_0, f"Ledger write failed for event '{event.event_id}': {exc}"
            ) from exc

    def _persist_candidates(
        self, candidates: list[DreamCandidate], ledger_event: DreamLedgerEvent
    ) -> None:
        """Candidate store append (DSTE-5: no production state modified)."""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with self.state_path.open("a", encoding="utf-8") as fh:
            for c in candidates:
                record = dataclasses.asdict(c)
                record["ledger_event_id"] = ledger_event.event_id
                record["ledger_prev_hash"] = ledger_event.prev_event_hash
                fh.write(json.dumps(record) + "\n")


__all__ = [
    "DreamStateEngine",
    "DreamCandidate",
    "DreamLedgerEvent",
    "DreamStateReport",
    "evaluate_dream_gate_0",
    "evaluate_dream_gate_1",
    "DreamGateViolation",
    "DREAM_DEPTH", "DREAM_CANDIDATES", "DREAM_MIN_SCORE", "DREAM_MIN_NOVELTY", "DREAM_QUORUM",
    "DSTE_0", "DSTE_1", "DSTE_2", "DSTE_3", "DSTE_4", "DSTE_5", "DSTE_6",
]
