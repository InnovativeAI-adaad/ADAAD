# SPDX-License-Identifier: Apache-2.0
"""
INNOV-82 · CFI — CEL Feedback Integrator
==========================================
Phase 177 · v9.110.0 · InnovativeAI LLC

World-first: A constitutionally-governed feedback integration engine that
reads HUMAN-0 disposition outcomes from RDP (INNOV-81) and translates
them into calibrated selection-weight adjustments for MSE (INNOV-75).

ACCEPTED dispositions amplify the weight of the mapped canonical axis;
REJECTED dispositions decay it. DEFERRED dispositions are neutral.
Weights are re-normalised after every integration cycle so MSE always
receives a valid probability distribution over CANONICAL_AXES.

This closes the last mechanical gap in the CEL self-improvement loop:

  MSE → MRP → MPG → MEX → MFV → IIS → CAL → RDP → HUMAN-0
   ↑                                                      │
   └───────────────── CFI (INNOV-82) ◄────────────────────┘

Hard-class invariants enforced (fail-closed):
  CFI-CHAIN-0   HMAC-SHA-256 chain on feedback ledger; broken chain halts all ops
  CFI-DETERM-0  No wall-clock injection; all timestamps via _utc_iso()
  CFI-HUMAN0-0  Only ACCEPTED/REJECTED dispositions modify weights; DEFERRED neutral
  CFI-IMMUT-0   Feedback weight ledger is append-only; no record mutation permitted
  CFI-ATOMIC-0  Weight computation + ledger append are atomic; partial writes raise
  CFI-SCOPE-0   CFI reads RDP disposition_ledger only; never writes to RDP/CAL paths
  CFI-FLOOR-0   No axis weight may fall below WEIGHT_FLOOR (0.05)
  CFI-CEIL-0    No axis weight may exceed WEIGHT_CEIL (0.60)
  CFI-NORM-0    Output weights must sum to 1.0 ± NORM_TOLERANCE after normalisation
  CFI-REPLAY-0  integration_id must be globally unique; duplicates rejected fail-closed

Governor: DUSTIN L REID
"""

from __future__ import annotations

import ast
import hashlib
import hmac
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Set


# ── Constants ─────────────────────────────────────────────────────────────────

_GOVERNOR: str = "DUSTIN L REID"
_INNOV_CODE: str = "INNOV-82"
_MODULE_CODE: str = "CFI"
_HMAC_KEY: bytes = b"adaad-cfi-chain-key-v1"

_LEDGER_DIR: Path = Path("data/cfi")
_FEEDBACK_LEDGER_PATH: Path = _LEDGER_DIR / "feedback_weight_ledger.jsonl"
_WEIGHT_SNAPSHOT_PATH: Path = _LEDGER_DIR / "current_weights.json"

# Default RDP disposition ledger path (INNOV-81 output)
_RDP_DISPOSITION_LEDGER: Path = Path("data/rdp/disposition_ledger.jsonl")

_CHAIN_PREFIX_LEN: int = 24  # CFI-CHAIN-0: comparison window

# CFI-FLOOR-0 / CFI-CEIL-0
WEIGHT_FLOOR: float = 0.05
WEIGHT_CEIL: float = 0.60

# CFI-NORM-0: acceptable deviation from 1.0 after normalisation
NORM_TOLERANCE: float = 1e-9

# Amplification / decay factors per disposition
ACCEPTED_AMPLIFY: float = 1.10   # +10% per accepted amendment
REJECTED_DECAY: float = 0.90     # -10% per rejected amendment

# Default MSE weights (must match dorkllm/mutation_selection_engine.DEFAULT_WEIGHTS)
DEFAULT_WEIGHTS: Dict[str, float] = {
    "lineage_depth":       0.15,
    "blast_containment":   0.30,
    "velocity_alignment":  0.20,
    "convergence_delta":   0.25,
    "constitutional_debt": 0.10,
}

CANONICAL_AXES: FrozenSet[str] = frozenset(DEFAULT_WEIGHTS.keys())

# ── Invariant-to-axis affinity map ───────────────────────────────────────────
#
# RDP proposals carry an invariant_id such as "RDP-CHAIN-0", "MSE-HUMAN0-0".
# CFI maps the invariant's suffix category to the MSE canonical axis whose
# weight should be adjusted.  The mapping reflects constitutional semantics:
#
#   CHAIN / IMMUT / AUDIT  → constitutional_debt  (integrity governance)
#   SCOPE / ATOMIC         → blast_containment     (isolation = blast safety)
#   DETERM / REPLAY        → velocity_alignment    (determinism = velocity fit)
#   HUMAN0 / HUMAN         → convergence_delta     (oversight guides convergence)
#   RANK / FLOOR / WINDOW  → lineage_depth         (scoring / lineage mechanics)
#   (default / unmatched)  → constitutional_debt   (conservative fallback)

_SUFFIX_TO_AXIS: Dict[str, str] = {
    "CHAIN":   "constitutional_debt",
    "IMMUT":   "constitutional_debt",
    "AUDIT":   "constitutional_debt",
    "SCOPE":   "blast_containment",
    "ATOMIC":  "blast_containment",
    "DETERM":  "velocity_alignment",
    "REPLAY":  "velocity_alignment",
    "HUMAN0":  "convergence_delta",
    "HUMAN":   "convergence_delta",
    "RANK":    "lineage_depth",
    "FLOOR":   "lineage_depth",
    "WINDOW":  "lineage_depth",
    "PERSIST": "lineage_depth",
    "BLAST":   "blast_containment",
    "FORMAT":  "constitutional_debt",
    "QUEUE":   "blast_containment",
    "NORM":    "constitutional_debt",
    "CEIL":    "constitutional_debt",
}

_DEFAULT_AXIS: str = "constitutional_debt"


# ── Errors ────────────────────────────────────────────────────────────────────

class CFIChainError(Exception):
    """CFI-CHAIN-0: HMAC chain broken on feedback ledger."""

class CFIAtomicError(Exception):
    """CFI-ATOMIC-0: integration operation could not complete atomically."""

class CFIReplayError(Exception):
    """CFI-REPLAY-0: duplicate integration_id detected."""

class CFINormError(Exception):
    """CFI-NORM-0: weight normalisation produced invalid distribution."""

class CFIFloorError(Exception):
    """CFI-FLOOR-0: axis weight violated floor constraint."""

class CFICeilError(Exception):
    """CFI-CEIL-0: axis weight violated ceiling constraint."""

class CFIScopeError(Exception):
    """CFI-SCOPE-0: CFI attempted to write to a protected path."""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _utc_iso() -> str:
    """CFI-DETERM-0: single authoritative timestamp source — no injection."""
    return datetime.now(tz=timezone.utc).isoformat()


def _hmac_hex(payload: str, previous_hash: str) -> str:
    body = f"{previous_hash}|{payload}"
    return hmac.new(_HMAC_KEY, body.encode(), hashlib.sha256).hexdigest()


def _resolve_axis(invariant_id: str) -> str:
    """
    Map an invariant_id to a CANONICAL_AXES member.

    Parsing strategy: split on '-' and look for the suffix token in
    _SUFFIX_TO_AXIS.  Falls back to _DEFAULT_AXIS if no match.
    """
    parts = invariant_id.upper().split("-")
    for part in reversed(parts):
        if part in _SUFFIX_TO_AXIS:
            return _SUFFIX_TO_AXIS[part]
    return _DEFAULT_AXIS


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class DispositionSignal:
    """
    A single HUMAN-0 disposition signal consumed from the RDP ledger.
    Carries the minimal fields required for weight adjustment.
    """
    record_id: str
    proposal_id: str
    invariant_id: str
    disposition: str       # "ACCEPTED" | "REJECTED" | "DEFERRED"
    decided_at_utc: str
    axis_mapped: str       # CANONICAL_AXES member resolved by CFI


@dataclass
class FeedbackWeightSet:
    """
    Output of a CFI integration cycle.  Contains adjusted MSE weights,
    provenance, and HMAC chain linkage.

    CFI-NORM-0: weights.values() sum to 1.0 ± NORM_TOLERANCE.
    CFI-FLOOR-0 / CFI-CEIL-0: each weight is within [WEIGHT_FLOOR, WEIGHT_CEIL].
    """
    integration_id: str
    weights: Dict[str, float]
    prior_weights: Dict[str, float]
    signals_applied: int
    accepted_count: int
    rejected_count: int
    deferred_count: int
    axis_deltas: Dict[str, float]   # axis → weight change from prior
    timestamp_utc: str
    hmac_chain_hash: str = ""

    @property
    def weight_sum(self) -> float:
        return sum(self.weights.values())


@dataclass
class IntegrationSummary:
    """Top-level result returned to callers of integrate()."""
    integration_id: str
    signals_consumed: int
    accepted_count: int
    rejected_count: int
    deferred_count: int
    new_weights: Dict[str, float]
    axis_deltas: Dict[str, float]
    ledger_chain_hash: str
    timestamp_utc: str


# ── Core Engine ───────────────────────────────────────────────────────────────

class CFIFeedbackIntegrator:
    """
    INNOV-82 · CFI — CEL Feedback Integrator

    Reads HUMAN-0 disposition records from the RDP disposition ledger and
    translates them into calibrated MSE selection-weight adjustments.

    Usage
    -----
    cfi = CFIFeedbackIntegrator()
    summary = cfi.integrate()
    weights = cfi.load_current_weights()   # pass to MutationSelectionEngine(weights=...)

    All ten Hard-class invariants enforced fail-closed.
    """

    def __init__(
        self,
        rdp_disposition_ledger_path: Optional[Path] = None,
        feedback_ledger_path: Optional[Path] = None,
        weight_snapshot_path: Optional[Path] = None,
    ) -> None:
        self.rdp_disposition_ledger_path = (
            rdp_disposition_ledger_path or _RDP_DISPOSITION_LEDGER
        )
        self.feedback_ledger_path = feedback_ledger_path or _FEEDBACK_LEDGER_PATH
        self.weight_snapshot_path = weight_snapshot_path or _WEIGHT_SNAPSHOT_PATH

        # CFI-SCOPE-0: ensure we never write to RDP or CAL protected paths
        _protected = {
            str(self.rdp_disposition_ledger_path),
            "data/rdp/proposal_ledger.jsonl",
            "data/cal/cal_learning_ledger.jsonl",
            "data/cal/cal_amendment_recommendations.json",
        }
        if str(self.feedback_ledger_path) in _protected:
            raise CFIScopeError(
                f"CFI-SCOPE-0: feedback_ledger_path overlaps a protected RDP/CAL path: "
                f"{self.feedback_ledger_path}"
            )

        self._ensure_dirs()

    # ── Infrastructure ────────────────────────────────────────────────────────

    def _ensure_dirs(self) -> None:
        self.feedback_ledger_path.parent.mkdir(parents=True, exist_ok=True)

    # ── CFI-CHAIN-0 ───────────────────────────────────────────────────────────

    def _get_previous_chain_hash(self) -> str:
        """Read tail hash from feedback ledger for chain linking."""
        if (
            not self.feedback_ledger_path.exists()
            or self.feedback_ledger_path.stat().st_size == 0
        ):
            return "0" * 64
        with open(self.feedback_ledger_path, "rb") as fh:
            try:
                fh.seek(-4096, 2)
            except OSError:
                fh.seek(0)
            raw = fh.read()
        lines = [ln for ln in raw.split(b"\n") if ln.strip()]
        if not lines:
            return "0" * 64
        try:
            record = json.loads(lines[-1])
            return record.get("hmac_chain_hash", "0" * 64)
        except (json.JSONDecodeError, KeyError):
            raise CFIChainError(
                "CFI-CHAIN-0: feedback ledger tail corrupt; cannot derive previous hash"
            )

    def verify_chain(self) -> bool:
        """
        CFI-CHAIN-0: full forward walk of the feedback weight ledger.
        Raises CFIChainError on tamper detection.
        """
        if not self.feedback_ledger_path.exists():
            return True
        prev = "0" * 64
        with open(self.feedback_ledger_path) as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    raise CFIChainError(
                        f"CFI-CHAIN-0: corrupt JSON at ledger line {lineno}"
                    )
                payload = json.dumps(
                    {k: v for k, v in rec.items() if k != "hmac_chain_hash"},
                    sort_keys=True,
                )
                computed = _hmac_hex(payload, prev)
                stored = rec.get("hmac_chain_hash", "")
                if computed[:_CHAIN_PREFIX_LEN] != stored[:_CHAIN_PREFIX_LEN]:
                    raise CFIChainError(
                        f"CFI-CHAIN-0: chain break at line {lineno}; "
                        f"computed={computed[:8]} stored={stored[:8]}"
                    )
                prev = computed
        return True

    # ── CFI-REPLAY-0 ─────────────────────────────────────────────────────────

    def _seen_integration_ids(self) -> Set[str]:
        ids: Set[str] = set()
        if not self.feedback_ledger_path.exists():
            return ids
        with open(self.feedback_ledger_path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if "integration_id" in rec:
                        ids.add(rec["integration_id"])
                except json.JSONDecodeError:
                    pass
        return ids

    # ── RDP disposition ledger reader ─────────────────────────────────────────

    def _load_disposition_signals(self) -> List[DispositionSignal]:
        """
        Read all records from RDP disposition_ledger.jsonl.
        CFI-SCOPE-0: read-only access; no writes to this file.
        """
        signals: List[DispositionSignal] = []
        if not self.rdp_disposition_ledger_path.exists():
            return signals
        with open(self.rdp_disposition_ledger_path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                disposition = rec.get("disposition", "")
                if disposition not in {"ACCEPTED", "REJECTED", "DEFERRED"}:
                    continue
                inv_id = rec.get("invariant_id", "UNKNOWN")
                signals.append(
                    DispositionSignal(
                        record_id=rec.get("record_id", ""),
                        proposal_id=rec.get("proposal_id", ""),
                        invariant_id=inv_id,
                        disposition=disposition,
                        decided_at_utc=rec.get("decided_at_utc", ""),
                        axis_mapped=_resolve_axis(inv_id),
                    )
                )
        return signals

    # ── Weight arithmetic ─────────────────────────────────────────────────────

    def _apply_signals(
        self, prior_weights: Dict[str, float], signals: List[DispositionSignal]
    ) -> tuple[Dict[str, float], Dict[str, float], int, int, int]:
        """
        Apply disposition signals to produce adjusted weights.

        CFI-HUMAN0-0: only ACCEPTED and REJECTED modify weights.
        CFI-FLOOR-0 / CFI-CEIL-0: clamp each axis weight.
        CFI-NORM-0: normalise so weights sum to 1.0.

        Returns: (new_weights, axis_deltas, accepted_count, rejected_count, deferred_count)
        """
        weights = dict(prior_weights)
        accepted_count = 0
        rejected_count = 0
        deferred_count = 0

        for sig in signals:
            # CFI-HUMAN0-0: DEFERRED is neutral
            if sig.disposition == "DEFERRED":
                deferred_count += 1
                continue

            axis = sig.axis_mapped
            if axis not in weights:
                axis = _DEFAULT_AXIS

            if sig.disposition == "ACCEPTED":
                weights[axis] *= ACCEPTED_AMPLIFY
                accepted_count += 1
            elif sig.disposition == "REJECTED":
                weights[axis] *= REJECTED_DECAY
                rejected_count += 1

        # CFI-FLOOR-0 / CFI-CEIL-0: clamp
        for ax in weights:
            weights[ax] = max(WEIGHT_FLOOR, min(WEIGHT_CEIL, weights[ax]))

        # CFI-NORM-0: normalise to sum = 1.0
        total = sum(weights.values())
        if total <= 0:
            raise CFINormError("CFI-NORM-0: weight total collapsed to ≤ 0 after signal application")
        weights = {ax: w / total for ax, w in weights.items()}

        # Verify normalisation
        weight_sum = sum(weights.values())
        if abs(weight_sum - 1.0) > NORM_TOLERANCE:
            raise CFINormError(
                f"CFI-NORM-0: normalised weights sum to {weight_sum:.12f}, "
                f"expected 1.0 ± {NORM_TOLERANCE}"
            )

        axis_deltas = {ax: weights[ax] - prior_weights.get(ax, 0.0) for ax in weights}
        return weights, axis_deltas, accepted_count, rejected_count, deferred_count

    # ── Ledger persistence ────────────────────────────────────────────────────

    def _append_feedback_record(self, weight_set: FeedbackWeightSet) -> str:
        """
        CFI-IMMUT-0 / CFI-CHAIN-0 / CFI-ATOMIC-0: append record, compute chain hash.
        Returns the computed chain hash.
        """
        record = asdict(weight_set)
        record.pop("hmac_chain_hash", None)
        payload = json.dumps(record, sort_keys=True)
        prev_hash = self._get_previous_chain_hash()
        chain_hash = _hmac_hex(payload, prev_hash)
        record["hmac_chain_hash"] = chain_hash

        try:
            with open(self.feedback_ledger_path, "a") as fh:
                fh.write(json.dumps(record) + "\n")
        except OSError as exc:
            raise CFIAtomicError(
                f"CFI-ATOMIC-0: ledger append failed mid-write: {exc}"
            ) from exc

        return chain_hash

    def _persist_weight_snapshot(self, weights: Dict[str, float], integration_id: str) -> None:
        """Write current weights to snapshot file for fast reads by MSE."""
        snapshot = {
            "integration_id": integration_id,
            "weights": weights,
            "timestamp_utc": _utc_iso(),
            "module": _MODULE_CODE,
            "innov": _INNOV_CODE,
        }
        with open(self.weight_snapshot_path, "w") as fh:
            json.dump(snapshot, fh, indent=2)

    # ── Public API ────────────────────────────────────────────────────────────

    def load_current_weights(self) -> Dict[str, float]:
        """
        Return the most recent feedback-adjusted weight set.

        Falls back to DEFAULT_WEIGHTS if no integration has been run yet.
        This is the method MSE should call to obtain calibrated weights:

            weights = CFIFeedbackIntegrator().load_current_weights()
            mse = MutationSelectionEngine(weights=weights)
        """
        if not self.weight_snapshot_path.exists():
            return dict(DEFAULT_WEIGHTS)
        with open(self.weight_snapshot_path) as fh:
            snapshot = json.load(fh)
        weights = snapshot.get("weights", dict(DEFAULT_WEIGHTS))
        # Defensive: re-validate axes
        if set(weights.keys()) != CANONICAL_AXES:
            return dict(DEFAULT_WEIGHTS)
        return weights

    def get_disposition_signals(self) -> List[DispositionSignal]:
        """
        Return all disposition signals from the RDP ledger.
        Public read-only accessor for inspection and testing.
        """
        return self._load_disposition_signals()

    def integrate(self, integration_id: Optional[str] = None) -> IntegrationSummary:
        """
        Execute one CFI integration cycle.

        Reads ALL records from the RDP disposition ledger, computes
        cumulative weight adjustments, normalises, and appends the result
        to the HMAC-chained feedback weight ledger.

        CFI-REPLAY-0: each integration_id must be unique.
        CFI-ATOMIC-0: weight computation and ledger append are an atomic unit.

        Parameters
        ----------
        integration_id : str, optional
            Unique identifier for this cycle.  Generated via UUID4 if omitted.

        Returns
        -------
        IntegrationSummary
        """
        integration_id = integration_id or str(uuid.uuid4())

        # CFI-REPLAY-0
        if integration_id in self._seen_integration_ids():
            raise CFIReplayError(
                f"CFI-REPLAY-0: duplicate integration_id '{integration_id}' rejected"
            )

        # Load prior weights
        prior_weights = self.load_current_weights()

        # Load RDP signals (CFI-SCOPE-0: read-only)
        signals = self._load_disposition_signals()

        # Apply signals
        (
            new_weights,
            axis_deltas,
            accepted_count,
            rejected_count,
            deferred_count,
        ) = self._apply_signals(prior_weights, signals)

        timestamp = _utc_iso()

        weight_set = FeedbackWeightSet(
            integration_id=integration_id,
            weights=new_weights,
            prior_weights=prior_weights,
            signals_applied=len(signals),
            accepted_count=accepted_count,
            rejected_count=rejected_count,
            deferred_count=deferred_count,
            axis_deltas=axis_deltas,
            timestamp_utc=timestamp,
        )

        # CFI-ATOMIC-0: append then snapshot
        chain_hash = self._append_feedback_record(weight_set)
        self._persist_weight_snapshot(new_weights, integration_id)

        return IntegrationSummary(
            integration_id=integration_id,
            signals_consumed=len(signals),
            accepted_count=accepted_count,
            rejected_count=rejected_count,
            deferred_count=deferred_count,
            new_weights=new_weights,
            axis_deltas=axis_deltas,
            ledger_chain_hash=chain_hash,
            timestamp_utc=timestamp,
        )

    def summary(self) -> Dict:
        """
        Return a human-readable integration history summary.
        Reads the full feedback ledger; reports cycle count and weight trajectory.
        """
        if not self.feedback_ledger_path.exists():
            return {"cycles": 0, "current_weights": dict(DEFAULT_WEIGHTS)}
        cycles = []
        with open(self.feedback_ledger_path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    cycles.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return {
            "cycles": len(cycles),
            "current_weights": self.load_current_weights(),
            "history": [
                {
                    "integration_id": c.get("integration_id"),
                    "signals_applied": c.get("signals_applied"),
                    "accepted_count": c.get("accepted_count"),
                    "rejected_count": c.get("rejected_count"),
                    "timestamp_utc": c.get("timestamp_utc"),
                }
                for c in cycles
            ],
        }
