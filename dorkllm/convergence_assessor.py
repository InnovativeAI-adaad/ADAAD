# SPDX-License-Identifier: Apache-2.0
"""Phase 165 · INNOV-71 · V10 Convergence Assessor (V10CA).

Evaluates all seven V10.0.0 convergence criteria and produces a
deterministic, HMAC-chained ConvergenceSnapshot that answers:
"How close is this ADAAD instance to v10.0.0?"

Key capabilities
----------------
* assess()          — evaluate all 7 criteria; produce a ConvergenceSnapshot
* score()           — return a single float convergence score [0.0, 1.0]
* history()         — return the full HMAC-chained snapshot ledger
* verify_chain()    — verify chain integrity of all snapshots

The Seven V10 Convergence Criteria
------------------------------------
1. INVARIANT_DENSITY    — cumulative hard-class invariants ≥ V10_MIN_INVARIANTS
2. INNOVATION_DEPTH     — shipped innovations ≥ V10_MIN_INNOVATIONS
3. GENOME_INTEGRITY     — CGE genome chain verifiable; no orphaned genomes
4. SELF_REPAIR_ACTIVE   — CSR module healthy; repair actions > 0
5. FORECAST_COVERAGE    — CFE forecast window ≥ V10_MIN_FORECAST_PHASES
6. DORK_INTELLIGENCE    — DORK fleet size ≥ V10_MIN_DORK_FLEET and query router live
7. GA_ALIGNMENT         — PyPI GA version published and repo version aligned

Constitutional invariants enforced
------------------------------------
V10CA-DETERM-0  assess() is a pure deterministic function of its inputs;
                no wall-clock time, randomness, or external I/O influences
                the ConvergenceSnapshot value fields.
V10CA-CHAIN-0   Every snapshot is HMAC-chained to its predecessor;
                orphaned or tampered snapshots raise V10CAChainError.
V10CA-HUMAN0-0  When overall convergence_score >= V10_PROMOTION_GATE,
                a HUMAN-0 ratification requirement is recorded in the snapshot
                and must be acknowledged before any v10 promotion action.
V10CA-SCOPE-0   Exactly the seven canonical criteria are evaluated per call;
                no criterion may be added, removed, or reordered without a
                constitutional amendment authored by HUMAN-0.
V10CA-AUDIT-0   Every assess() call appends a complete snapshot to the
                append-only ledger; ledger entries are never modified or deleted.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
GOVERNOR: str = "DUSTIN L REID"
CHAIN_ROOT: str = "0" * 64
HMAC_KEY: bytes = b"v10ca-chain-key-v1"

# V10 threshold constants (constitutional — changes require HUMAN-0 amendment)
V10_MIN_INVARIANTS: int = 350
V10_MIN_INNOVATIONS: int = 75
V10_MIN_FORECAST_PHASES: int = 5
V10_MIN_DORK_FLEET: int = 3
V10_PROMOTION_GATE: float = 0.90   # convergence_score ≥ this → HUMAN-0 required

CANONICAL_CRITERIA: tuple[str, ...] = (
    "INVARIANT_DENSITY",
    "INNOVATION_DEPTH",
    "GENOME_INTEGRITY",
    "SELF_REPAIR_ACTIVE",
    "FORECAST_COVERAGE",
    "DORK_INTELLIGENCE",
    "GA_ALIGNMENT",
)

_ASSESSOR_VERSION: str = "1.0"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class V10CAChainError(RuntimeError):
    """Raised when the snapshot chain is broken or tampered."""


class V10CAHuman0Gate(RuntimeError):
    """Raised when convergence_score exceeds the v10 promotion gate."""


class V10CAScopeError(RuntimeError):
    """Raised when an illegal criterion mutation is detected."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
class CriterionStatus(str, Enum):
    MET = "MET"
    PARTIAL = "PARTIAL"
    UNMET = "UNMET"


@dataclass
class CriterionResult:
    criterion: str
    status: CriterionStatus
    score: float           # [0.0, 1.0]
    actual: Any
    threshold: Any
    note: str


@dataclass
class ConvergenceSnapshot:
    snapshot_id: str
    assessor_version: str
    epoch_id: str
    criteria: List[CriterionResult]
    convergence_score: float        # weighted mean [0.0, 1.0]
    human0_required: bool
    governor: str
    prev_digest: str
    digest: str = ""                # filled after chain computation

    def to_dict(self) -> dict:
        d = asdict(self)
        d["criteria"] = [asdict(c) for c in self.criteria]
        return d


# ---------------------------------------------------------------------------
# Convergence Assessor
# ---------------------------------------------------------------------------
class V10ConvergenceAssessor:
    """Deterministic assessor for ADAAD v10.0.0 convergence criteria.

    Parameters
    ----------
    ledger_path : Path | None
        Path to the JSON-lines ledger file.  Defaults to
        ``data/v10ca_ledger.jsonl``.
    hmac_key : bytes
        HMAC key for chain digests.  Change requires a constitutional amendment.
    """

    def __init__(
        self,
        ledger_path: Path | None = None,
        hmac_key: bytes = HMAC_KEY,
    ) -> None:
        self._ledger_path = Path(ledger_path) if ledger_path else Path("data/v10ca_ledger.jsonl")
        self._hmac_key = hmac_key
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self._snapshots: List[ConvergenceSnapshot] = []
        self._load_ledger()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def assess(self, epoch_id: str, inputs: Dict[str, Any]) -> ConvergenceSnapshot:
        """Evaluate all seven convergence criteria and return a chained snapshot.

        Parameters
        ----------
        epoch_id : str
            Caller-supplied epoch identifier (e.g. ``"phase165"``).
        inputs : dict
            Runtime measurements.  Keys (all optional; defaults are safe-fail):

            * ``hard_invariant_count`` (int)
            * ``innovation_count``     (int)
            * ``genome_chain_valid``   (bool)
            * ``genome_entry_count``   (int)
            * ``self_repair_actions``  (int)
            * ``forecast_window``      (int)  phases forward
            * ``dork_fleet_size``      (int)
            * ``dork_router_live``     (bool)
            * ``ga_version_published`` (str | None)
            * ``repo_version``         (str | None)

        Returns
        -------
        ConvergenceSnapshot
            Deterministic, HMAC-chained snapshot.

        Raises
        ------
        V10CAHuman0Gate
            If convergence_score >= V10_PROMOTION_GATE.
        V10CAScopeError
            If canonical criteria list has been tampered.
        V10CAChainError
            If chain integrity is violated.
        """
        # V10CA-SCOPE-0 — canonical criteria must remain unchanged
        if CANONICAL_CRITERIA != (
            "INVARIANT_DENSITY", "INNOVATION_DEPTH", "GENOME_INTEGRITY",
            "SELF_REPAIR_ACTIVE", "FORECAST_COVERAGE", "DORK_INTELLIGENCE",
            "GA_ALIGNMENT",
        ):
            raise V10CAScopeError("CANONICAL_CRITERIA tampered — constitutional amendment required")

        criteria = self._evaluate_all(inputs)

        # Weighted score — all criteria equal weight (1/7 each)  [V10CA-DETERM-0]
        convergence_score = round(sum(c.score for c in criteria) / len(criteria), 6)

        prev_digest = self._snapshots[-1].digest if self._snapshots else CHAIN_ROOT

        import uuid as _uuid
        snapshot_id = f"v10ca-{epoch_id}-{_uuid.uuid5(_uuid.NAMESPACE_DNS, f'{epoch_id}-{prev_digest}')}"

        snap = ConvergenceSnapshot(
            snapshot_id=snapshot_id,
            assessor_version=_ASSESSOR_VERSION,
            epoch_id=epoch_id,
            criteria=criteria,
            convergence_score=convergence_score,
            human0_required=(convergence_score >= V10_PROMOTION_GATE),
            governor=GOVERNOR,
            prev_digest=prev_digest,
        )

        # V10CA-CHAIN-0 — compute HMAC-chained digest
        snap.digest = self._chain_digest(snap)

        # V10CA-AUDIT-0 — append to ledger before returning
        self._append_ledger(snap)
        self._snapshots.append(snap)

        # V10CA-HUMAN0-0 — gate after ledger write so the gate event is recorded
        if snap.human0_required:
            raise V10CAHuman0Gate(
                f"Convergence score {convergence_score:.4f} >= {V10_PROMOTION_GATE} "
                f"— HUMAN-0 ratification required before any v10 promotion action. "
                f"snapshot_id={snap.snapshot_id}"
            )

        return snap

    def score(self, inputs: Dict[str, Any], epoch_id: str = "score-query") -> float:
        """Return the convergence score without raising V10CAHuman0Gate.

        Useful for monitoring.  Still chains and ledgers the snapshot.
        """
        try:
            snap = self.assess(epoch_id=epoch_id, inputs=inputs)
            return snap.convergence_score
        except V10CAHuman0Gate as exc:
            # Extract score from the ledger entry written before the gate fired
            return self._snapshots[-1].convergence_score if self._snapshots else 0.0

    def history(self) -> List[ConvergenceSnapshot]:
        """Return the full ordered snapshot history."""
        return list(self._snapshots)

    def verify_chain(self) -> bool:
        """Verify HMAC chain integrity of all stored snapshots.

        Returns
        -------
        bool
            True if chain is intact.

        Raises
        ------
        V10CAChainError
            On first broken link.
        """
        prev = CHAIN_ROOT
        for snap in self._snapshots:
            if snap.prev_digest != prev:
                raise V10CAChainError(
                    f"Chain broken at snapshot {snap.snapshot_id}: "
                    f"expected prev_digest={prev!r}, got {snap.prev_digest!r}"
                )
            expected = self._chain_digest(snap)
            if not hmac.compare_digest(snap.digest, expected):
                raise V10CAChainError(
                    f"Digest mismatch at snapshot {snap.snapshot_id}"
                )
            prev = snap.digest
        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evaluate_all(self, inputs: Dict[str, Any]) -> List[CriterionResult]:
        """Evaluate each of the seven canonical criteria deterministically."""
        return [
            self._eval_invariant_density(inputs),
            self._eval_innovation_depth(inputs),
            self._eval_genome_integrity(inputs),
            self._eval_self_repair(inputs),
            self._eval_forecast_coverage(inputs),
            self._eval_dork_intelligence(inputs),
            self._eval_ga_alignment(inputs),
        ]

    def _eval_invariant_density(self, inp: Dict[str, Any]) -> CriterionResult:
        actual = int(inp.get("hard_invariant_count", 0))
        threshold = V10_MIN_INVARIANTS
        ratio = min(actual / threshold, 1.0)
        status = CriterionStatus.MET if actual >= threshold else (
            CriterionStatus.PARTIAL if actual >= threshold * 0.7 else CriterionStatus.UNMET
        )
        return CriterionResult(
            criterion="INVARIANT_DENSITY",
            status=status,
            score=round(ratio, 6),
            actual=actual,
            threshold=threshold,
            note=f"{actual}/{threshold} hard-class invariants ({ratio*100:.1f}%)",
        )

    def _eval_innovation_depth(self, inp: Dict[str, Any]) -> CriterionResult:
        actual = int(inp.get("innovation_count", 0))
        threshold = V10_MIN_INNOVATIONS
        ratio = min(actual / threshold, 1.0)
        status = CriterionStatus.MET if actual >= threshold else (
            CriterionStatus.PARTIAL if actual >= threshold * 0.7 else CriterionStatus.UNMET
        )
        return CriterionResult(
            criterion="INNOVATION_DEPTH",
            status=status,
            score=round(ratio, 6),
            actual=actual,
            threshold=threshold,
            note=f"{actual}/{threshold} innovations shipped",
        )

    def _eval_genome_integrity(self, inp: Dict[str, Any]) -> CriterionResult:
        chain_valid = bool(inp.get("genome_chain_valid", False))
        entry_count = int(inp.get("genome_entry_count", 0))
        score = 1.0 if (chain_valid and entry_count > 0) else (0.5 if entry_count > 0 else 0.0)
        status = CriterionStatus.MET if score == 1.0 else (
            CriterionStatus.PARTIAL if score > 0 else CriterionStatus.UNMET
        )
        return CriterionResult(
            criterion="GENOME_INTEGRITY",
            status=status,
            score=round(score, 6),
            actual={"chain_valid": chain_valid, "entry_count": entry_count},
            threshold={"chain_valid": True, "entry_count": ">0"},
            note=f"CGE chain valid={chain_valid}, genomes={entry_count}",
        )

    def _eval_self_repair(self, inp: Dict[str, Any]) -> CriterionResult:
        actions = int(inp.get("self_repair_actions", 0))
        score = 1.0 if actions > 0 else 0.0
        status = CriterionStatus.MET if actions > 0 else CriterionStatus.UNMET
        return CriterionResult(
            criterion="SELF_REPAIR_ACTIVE",
            status=status,
            score=score,
            actual=actions,
            threshold=">0",
            note=f"CSR repair_actions={actions}",
        )

    def _eval_forecast_coverage(self, inp: Dict[str, Any]) -> CriterionResult:
        window = int(inp.get("forecast_window", 0))
        threshold = V10_MIN_FORECAST_PHASES
        ratio = min(window / threshold, 1.0)
        status = CriterionStatus.MET if window >= threshold else (
            CriterionStatus.PARTIAL if window > 0 else CriterionStatus.UNMET
        )
        return CriterionResult(
            criterion="FORECAST_COVERAGE",
            status=status,
            score=round(ratio, 6),
            actual=window,
            threshold=threshold,
            note=f"CFE forecast_window={window} phases (need {threshold})",
        )

    def _eval_dork_intelligence(self, inp: Dict[str, Any]) -> CriterionResult:
        fleet = int(inp.get("dork_fleet_size", 0))
        router_live = bool(inp.get("dork_router_live", False))
        fleet_ok = fleet >= V10_MIN_DORK_FLEET
        score = (0.6 if fleet_ok else min(fleet / V10_MIN_DORK_FLEET, 0.6)) + (0.4 if router_live else 0.0)
        score = round(min(score, 1.0), 6)
        status = CriterionStatus.MET if (fleet_ok and router_live) else (
            CriterionStatus.PARTIAL if score > 0 else CriterionStatus.UNMET
        )
        return CriterionResult(
            criterion="DORK_INTELLIGENCE",
            status=status,
            score=score,
            actual={"fleet_size": fleet, "router_live": router_live},
            threshold={"fleet_size": V10_MIN_DORK_FLEET, "router_live": True},
            note=f"DORK fleet={fleet}/{V10_MIN_DORK_FLEET}, router_live={router_live}",
        )

    def _eval_ga_alignment(self, inp: Dict[str, Any]) -> CriterionResult:
        ga_version = inp.get("ga_version_published")
        repo_version = inp.get("repo_version")
        published = ga_version is not None
        aligned = published and (ga_version == repo_version)
        score = 1.0 if aligned else (0.5 if published else 0.0)
        status = CriterionStatus.MET if aligned else (
            CriterionStatus.PARTIAL if published else CriterionStatus.UNMET
        )
        return CriterionResult(
            criterion="GA_ALIGNMENT",
            status=status,
            score=round(score, 6),
            actual={"ga_version": ga_version, "repo_version": repo_version},
            threshold="ga_version == repo_version",
            note=f"PyPI GA={ga_version!r} aligned with repo={repo_version!r}: {aligned}",
        )

    def _chain_digest(self, snap: ConvergenceSnapshot) -> str:
        """Compute HMAC-SHA256 digest for chaining.  V10CA-CHAIN-0."""
        payload = json.dumps(
            {
                "snapshot_id": snap.snapshot_id,
                "epoch_id": snap.epoch_id,
                "convergence_score": snap.convergence_score,
                "human0_required": snap.human0_required,
                "prev_digest": snap.prev_digest,
                "criteria": [
                    {"criterion": c.criterion, "score": c.score, "status": c.status}
                    for c in snap.criteria
                ],
            },
            sort_keys=True,
        )
        return hmac.new(self._hmac_key, payload.encode(), hashlib.sha256).hexdigest()

    def _append_ledger(self, snap: ConvergenceSnapshot) -> None:
        """Append snapshot to append-only JSONL ledger.  V10CA-AUDIT-0."""
        with self._ledger_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(snap.to_dict(), default=str) + "\n")

    def _load_ledger(self) -> None:
        """Load and verify existing ledger on startup.  V10CA-CHAIN-0."""
        if not self._ledger_path.exists():
            return
        prev = CHAIN_ROOT
        with self._ledger_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                raw = json.loads(line)
                criteria = [
                    CriterionResult(
                        criterion=c["criterion"],
                        status=CriterionStatus(c["status"]),
                        score=c["score"],
                        actual=c["actual"],
                        threshold=c["threshold"],
                        note=c["note"],
                    )
                    for c in raw["criteria"]
                ]
                snap = ConvergenceSnapshot(
                    snapshot_id=raw["snapshot_id"],
                    assessor_version=raw.get("assessor_version", "1.0"),
                    epoch_id=raw["epoch_id"],
                    criteria=criteria,
                    convergence_score=raw["convergence_score"],
                    human0_required=raw["human0_required"],
                    governor=raw["governor"],
                    prev_digest=raw["prev_digest"],
                    digest=raw["digest"],
                )
                if snap.prev_digest != prev:
                    raise V10CAChainError(f"Ledger chain broken at {snap.snapshot_id}")
                # Re-verify stored digest matches recomputed digest  [V10CA-CHAIN-0]
                expected = self._chain_digest(snap)
                if not hmac.compare_digest(snap.digest, expected):
                    raise V10CAChainError(
                        f"Digest mismatch at snapshot {snap.snapshot_id} — ledger tampered"
                    )
                prev = snap.digest
                self._snapshots.append(snap)
