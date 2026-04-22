# SPDX-License-Identifier: Apache-2.0
"""Phase 82 — ParetoCompetitionOrchestrator.

Extends Phase 80 SeedCompetitionOrchestrator with multi-objective Pareto
frontier evaluation. Replaces scalar rank with Pareto dominance; promotes
all frontier candidates (one per niche via GovernanceGate).

Constitutional Invariants
─────────────────────────
  PARETO-0       Scalar fitness preserved as advisory signal only.
  PARETO-DET-0   Frontier computation is deterministic.
  PARETO-NONDEG-0 Non-empty input → non-empty frontier.
  PARETO-GOV-0   GovernanceGate evaluates every frontier candidate independently.
  COMP-LEDGER-0  ParetoCompetitionEpochEvent written to LineageLedgerV2 before
                 any candidate is promoted (inherited from Phase 80).
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from runtime.evolution.pareto_frontier import (
    PARETO_OBJECTIVES,
    ParetoFrontier,
    ParetoFrontierResult,
    ParetoObjectiveVector,
    build_objective_vector_from_fitness_context,
)
from runtime.seed_competition import GateEvaluateFn, SeedCandidate, _default_gate_fn

log = logging.getLogger(__name__)

_PHASE = 82
_VERSION_FILE = "VERSION"


def _read_version() -> str:
    try:
        from pathlib import Path
        return (Path(__file__).parent.parent / _VERSION_FILE).read_text().strip()
    except Exception:  # noqa: BLE001
        return "unknown"


# ---------------------------------------------------------------------------
# Data contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParetoCompetitionResult:
    """Outcome of one Pareto competitive epoch.

    Attributes
    ----------
    epoch_id:          Unique epoch identifier.
    frontier_ids:      Pareto-optimal candidate IDs (all eligible for promotion).
    dominated_ids:     Dominated candidate IDs (not eligible).
    passed_gate_ids:   Frontier candidates that passed GovernanceGate.
    failed_gate_ids:   Frontier candidates that failed GovernanceGate.
    scalar_ranking:    Advisory scalar ranking within frontier (PARETO-0).
    pareto_result:     Full ParetoFrontierResult for audit purposes.
    ledger_entry:      Raw dict written to LineageLedgerV2.
    gate_verdict:      Overall verdict: 'pass' | 'fail'.
    epoch_digest:      SHA-256 of canonical epoch inputs.
    """

    epoch_id: str
    frontier_ids: Tuple[str, ...]
    dominated_ids: Tuple[str, ...]
    passed_gate_ids: Tuple[str, ...]
    failed_gate_ids: Tuple[str, ...]
    scalar_ranking: List[Tuple[str, float]]
    pareto_result: ParetoFrontierResult
    ledger_entry: Dict[str, Any]
    gate_verdict: str
    epoch_digest: str

    @property
    def winner_id(self) -> Optional[str]:
        """Primary winner: top-ranked gate-passing frontier member (advisory). PARETO-0."""
        for cid, _ in self.scalar_ranking:
            if cid in self.passed_gate_ids:
                return cid
        return None

    @property
    def promoted_ids(self) -> Tuple[str, ...]:
        """All gate-passing frontier members eligible for promotion."""
        return self.passed_gate_ids


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _epoch_digest(candidate_ids: Sequence[str], vectors: Sequence[ParetoObjectiveVector]) -> str:
    payload = json.dumps(
        {
            "candidate_ids": sorted(candidate_ids),
            "vectors": sorted(
                [{"id": v.candidate_id, "objs": {k: v.objectives[k] for k in sorted(v.objectives)}} for v in vectors],
                key=lambda x: x["id"],
            ),
        },
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


# ---------------------------------------------------------------------------
# ParetoCompetitionOrchestrator
# ---------------------------------------------------------------------------


class ParetoCompetitionOrchestrator:
    """Phase 82 multi-objective competitive epoch runner.

    Lifecycle per epoch
    ───────────────────
    1. Score all candidates on PARETO_OBJECTIVES via FitnessOrchestrator.
    2. Build ParetoObjectiveVectors.
    3. Compute Pareto frontier (PARETO-DET-0, PARETO-NONDEG-0).
    4. Evaluate ALL frontier candidates through GovernanceGate (PARETO-GOV-0).
    5. Write ParetoCompetitionEpochEvent to LineageLedgerV2 (COMP-LEDGER-0).
    6. Return ParetoCompetitionResult with promoted_ids (all gate-passing frontier).

    Differences from Phase 80 SeedCompetitionOrchestrator
    ─────────────────────────────────────────────────────
    - Ranking replaced by Pareto dominance (scalar preserved as advisory).
    - Multiple candidates may be promoted (one per niche).
    - Dominated candidates are tracked but not gated (saves gate budget).
    """

    def __init__(
        self,
        *,
        fitness_orchestrator: Optional[Any] = None,
        ledger: Optional[Any] = None,
        gate_fn: Optional[GateEvaluateFn] = None,
        pareto_objectives: Sequence[str] = PARETO_OBJECTIVES,
        epoch_id_factory: Optional[Callable[[], str]] = None,
    ) -> None:
        if fitness_orchestrator is None:
            from runtime.evolution.fitness_orchestrator import FitnessOrchestrator
            fitness_orchestrator = FitnessOrchestrator()
        if ledger is None:
            from runtime.evolution.lineage_v2 import LineageLedgerV2
            ledger = LineageLedgerV2()

        self._orchestrator = fitness_orchestrator
        self._ledger = ledger
        self._gate_fn: GateEvaluateFn = gate_fn or _default_gate_fn
        self._pareto = ParetoFrontier(objectives=pareto_objectives)
        self._epoch_id_factory = epoch_id_factory or (lambda: str(uuid.uuid4()))

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run_epoch(self, candidates: Sequence[SeedCandidate]) -> ParetoCompetitionResult:
        """Execute one Pareto competitive epoch.

        Invariants enforced:
          PARETO-DET-0    Deterministic frontier given identical inputs.
          PARETO-NONDEG-0 Non-empty candidates → non-empty frontier.
          PARETO-GOV-0    Gate evaluates all frontier candidates.
          COMP-LEDGER-0   Ledger written before any result returned.
          PARETO-0        Scalar preserved advisory; dominance drives promotion.
        """
        if not candidates:
            raise ValueError("PARETO-NONDEG-0: candidates list must not be empty")

        epoch_id = self._epoch_id_factory()
        log.info("PARETO: starting epoch %s with %d candidates", epoch_id, len(candidates))

        # ── Step 1: Score all candidates on Pareto objectives ───────────────
        vectors: List[ParetoObjectiveVector] = []
        for c in candidates:
            result = self._orchestrator.score(c.fitness_context)
            scalar = float(result.total_score)
            vec = build_objective_vector_from_fitness_context(
                c.candidate_id, c.fitness_context, scalar_score=scalar,
            )
            vectors.append(vec)
            log.debug("PARETO: candidate %s scalar=%.4f", c.candidate_id, scalar)

        # ── Step 2: Compute Pareto frontier (PARETO-DET-0) ──────────────────
        pareto_result = self._pareto.compute(vectors)
        log.info(
            "PARETO: frontier=%d dominated=%d",
            pareto_result.frontier_size, pareto_result.dominated_size,
        )

        # ── Step 3: Gate ALL frontier candidates (PARETO-GOV-0) ─────────────
        meta_map = {c.candidate_id: c.metadata for c in candidates}
        passed: List[str] = []
        failed: List[str] = []
        for cid in pareto_result.frontier_ids:  # sorted for determinism
            verdict = self._gate_fn(cid, meta_map.get(cid, {}))
            if verdict == "pass":
                passed.append(cid)
            elif verdict == "fail":
                failed.append(cid)
            else:
                raise ValueError(
                    "PARETO-GOV-0: unsupported gate verdict "
                    f"{verdict!r} for ParetoCompetitionOrchestrator; "
                    "expected 'pass' or 'fail'."
                )
            log.debug("PARETO: gate verdict for %s: %s", cid, verdict)

        if passed:
            overall_verdict = "pass"
        elif failed:
            overall_verdict = "fail"
        else:
            raise RuntimeError(
                "PARETO-NONDEG-0: frontier evaluation produced no gate outcomes."
            )

        # ── Step 4: Advisory scalar ranking within frontier (PARETO-0) ──────
        scalar_ranking = self._pareto.rank_frontier(pareto_result, vectors)

        # ── Step 5: Write ledger (COMP-LEDGER-0) ────────────────────────────
        digest = _epoch_digest([c.candidate_id for c in candidates], vectors)
        ledger_payload = {
            "epoch_id": epoch_id,
            "frontier_ids": list(pareto_result.frontier_ids),
            "dominated_ids": list(pareto_result.dominated_ids),
            "passed_gate_ids": passed,
            "failed_gate_ids": failed,
            "gate_verdict": overall_verdict,
            "frontier_digest": pareto_result.frontier_digest,
            "epoch_digest": digest,
            "phase": _PHASE,
            "version": _read_version(),
        }
        ledger_entry = self._ledger.append_event("ParetoCompetitionEpochEvent", ledger_payload)
        log.info(
            "PARETO COMP-LEDGER-0: wrote ParetoCompetitionEpochEvent epoch=%s frontier=%d passed=%d",
            epoch_id, pareto_result.frontier_size, len(passed),
        )

        # ── Step 6: Raise if all frontier candidates failed gate ─────────────
        if overall_verdict == "fail":
            raise RuntimeError(
                f"PARETO-GOV-0: all frontier candidates failed GovernanceGate "
                f"in epoch {epoch_id}. Ledger entry written."
            )

        return ParetoCompetitionResult(
            epoch_id=epoch_id,
            frontier_ids=pareto_result.frontier_ids,
            dominated_ids=pareto_result.dominated_ids,
            passed_gate_ids=tuple(passed),
            failed_gate_ids=tuple(failed),
            scalar_ranking=scalar_ranking,
            pareto_result=pareto_result,
            ledger_entry=ledger_entry,
            gate_verdict=overall_verdict,
            epoch_digest=digest,
        )
