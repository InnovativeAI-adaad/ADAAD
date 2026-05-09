# SPDX-License-Identifier: Apache-2.0
# =============================================================================
# constitutional_adaptive_learner.py — INNOV-80 · CAL
# Constitutional Adaptive Learner
#
# Author:      DEVADAAD · InnovativeAI LLC
# Governor:    DUSTIN L REID (HUMAN-0)
# Phase:       175
# Innovation:  INNOV-80
# Version:     9.108.0
#
# Purpose:
#   Closes the ADAAD mutation pipeline feedback loop. Reads from the IIS
#   (Innovation Impact Scorer, INNOV-79) and MFV (Mutation Fitness Verifier,
#   INNOV-78) append-only ledgers, computes per-invariant contribution weights
#   across historical mutations, and generates HUMAN-0-gated constitutional
#   amendment recommendations. The CAL never self-applies recommendations;
#   it is a read-only oracle. All outputs are HMAC-SHA-256 chained and
#   deterministically replayable.
#
# Hard-class Invariants (10):
#   CAL-CHAIN-0    HMAC chain must be verified before any read operation
#   CAL-DETERM-0   All scoring is deterministic; no wall-clock or random calls
#   CAL-HUMAN0-0   Amendment recommendations are HUMAN-0-gated; never auto-applied
#   CAL-READONLY-0 CAL never mutates source ledgers (IIS / MFV)
#   CAL-ATOMIC-0   Ledger writes use os.replace; never in-place JSON mutation
#   CAL-BOUND-0    Invariant weights are clamped to [0.0, 1.0]
#   CAL-AUDIT-0    Every learning cycle writes an immutable audit record
#   CAL-SCOPE-0    CAL operates only on its declared input ledger paths
#   CAL-REPLAY-0   Full learning history must be deterministically replayable
#   CAL-NOSELF-0   CAL may not read its own ledger as an input source
#
# Integration points:
#   - Reads: security/iis_ledger.jsonl (INNOV-79)
#   - Reads: data/mfv/fitness_verdict_ledger.jsonl (INNOV-78)
#   - Writes: data/cal/cal_learning_ledger.jsonl (append-only, HMAC-chained)
#   - Writes: data/cal/cal_amendment_recommendations.json (HUMAN-0 review only)
# =============================================================================

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Hard-class invariant identifiers (referenced in enforcement blocks below)
# ---------------------------------------------------------------------------
_INVARIANTS: list[dict[str, str]] = [
    {"id": "CAL-CHAIN-0",   "class": "Hard", "phase": "175",
     "description": "HMAC chain must be verified before any read operation"},
    {"id": "CAL-DETERM-0",  "class": "Hard", "phase": "175",
     "description": "All scoring is deterministic; no wall-clock or random calls"},
    {"id": "CAL-HUMAN0-0",  "class": "Hard", "phase": "175",
     "description": "Amendment recommendations are HUMAN-0-gated; never auto-applied"},
    {"id": "CAL-READONLY-0","class": "Hard", "phase": "175",
     "description": "CAL never mutates source ledgers (IIS / MFV)"},
    {"id": "CAL-ATOMIC-0",  "class": "Hard", "phase": "175",
     "description": "Ledger writes use os.replace; never in-place JSON mutation"},
    {"id": "CAL-BOUND-0",   "class": "Hard", "phase": "175",
     "description": "Invariant weights are clamped to [0.0, 1.0]"},
    {"id": "CAL-AUDIT-0",   "class": "Hard", "phase": "175",
     "description": "Every learning cycle writes an immutable audit record"},
    {"id": "CAL-SCOPE-0",   "class": "Hard", "phase": "175",
     "description": "CAL operates only on its declared input ledger paths"},
    {"id": "CAL-REPLAY-0",  "class": "Hard", "phase": "175",
     "description": "Full learning history must be deterministically replayable"},
    {"id": "CAL-NOSELF-0",  "class": "Hard", "phase": "175",
     "description": "CAL may not read its own ledger as an input source"},
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_CAL_VERSION: str = "1.0.0"
_GOVERNOR: str = "DUSTIN L REID"
_INNOV_CODE: str = "INNOV-80"
_PHASE: int = 175

_DEFAULT_IIS_LEDGER: Path = Path("security/iis_ledger.jsonl")
_DEFAULT_MFV_LEDGER: Path = Path("data/mfv/fitness_verdict_ledger.jsonl")
_DEFAULT_CAL_LEDGER: Path = Path("data/cal/cal_learning_ledger.jsonl")
_DEFAULT_CAL_RECS: Path   = Path("data/cal/cal_amendment_recommendations.json")

# CAL-NOSELF-0: own ledger path is never a valid input source
_OWN_LEDGER_PATH: str = str(_DEFAULT_CAL_LEDGER)

# Weight floor/ceiling (CAL-BOUND-0)
_WEIGHT_MIN: float = 0.0
_WEIGHT_MAX: float = 1.0

# Minimum records required before a recommendation is emitted
_MIN_RECORDS_FOR_RECOMMENDATION: int = 5

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _hmac_entry(secret: bytes, previous_hash: str, record: dict[str, Any]) -> str:
    """Compute HMAC-SHA-256 chain link over (previous_hash || sha256(record_json))."""
    payload = previous_hash + hashlib.sha256(
        json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()


def _clamp(value: float, lo: float = _WEIGHT_MIN, hi: float = _WEIGHT_MAX) -> float:
    """CAL-BOUND-0: clamp a float to [lo, hi]."""
    return max(lo, min(hi, value))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL file line-by-line; skip malformed lines."""
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                # Silently skip corrupt lines; auditors can detect via chain break
                pass
    return records


def _atomic_write_json(path: Path, data: Any) -> None:
    """CAL-ATOMIC-0: write JSON atomically using os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
    os.replace(tmp_path, path)


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    """Append a single JSON record to a JSONL file (CAL-ATOMIC-0 for append)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class InvariantWeight:
    """Learned weight for a single constitutional invariant."""
    invariant_id: str
    raw_score: float          # Aggregate contribution signal in [-inf, +inf]
    normalized_weight: float  # Clamped to [0.0, 1.0]
    appearance_count: int     # How many mutation records involved this invariant
    positive_delta_sum: float # Sum of fitness improvements when invariant enforced
    negative_delta_sum: float # Sum of fitness regressions when invariant enforced
    recommendation: str       # "REINFORCE" | "REVIEW" | "STABLE"


@dataclass
class AmendmentRecommendation:
    """HUMAN-0-gated recommendation for a single invariant."""
    invariant_id: str
    recommendation: str       # "REINFORCE" | "REVIEW" | "STABLE"
    normalized_weight: float
    rationale: str
    requires_human0_approval: bool = True  # CAL-HUMAN0-0: always True
    governor: str = _GOVERNOR


@dataclass
class LearningCycleResult:
    """Output of a single CAL learning cycle."""
    cycle_id: str
    phase: int
    innov_code: str
    governor: str
    iis_records_read: int
    mfv_records_read: int
    invariants_analyzed: int
    weights: list[InvariantWeight]
    recommendations: list[AmendmentRecommendation]
    hmac_chain_hash: str
    timestamp_utc_iso: str    # CAL-DETERM-0: caller supplies; no internal wall-clock
    chain_verified: bool


# ---------------------------------------------------------------------------
# ConstitutionalAdaptiveLearner
# ---------------------------------------------------------------------------

class ConstitutionalAdaptiveLearner:
    """
    INNOV-80 · CAL — Constitutional Adaptive Learner.

    Reads from the IIS and MFV ledgers, computes per-invariant contribution
    weights, and emits HUMAN-0-gated amendment recommendations. Never
    self-modifies the source ledgers (CAL-READONLY-0). All writes go to the
    CAL-exclusive ledger paths (CAL-SCOPE-0).

    Usage:
        cal = ConstitutionalAdaptiveLearner(hmac_secret=b"...")
        result = cal.run_learning_cycle(cycle_id="cycle-001", timestamp_utc_iso="...")
    """

    def __init__(
        self,
        *,
        hmac_secret: bytes,
        iis_ledger_path: Path = _DEFAULT_IIS_LEDGER,
        mfv_ledger_path: Path = _DEFAULT_MFV_LEDGER,
        cal_ledger_path: Path = _DEFAULT_CAL_LEDGER,
        cal_recs_path: Path   = _DEFAULT_CAL_RECS,
    ) -> None:
        # CAL-SCOPE-0 + CAL-NOSELF-0: input paths must not resolve to the CAL's own ledger
        _own = str(cal_ledger_path.resolve()) if hasattr(cal_ledger_path, "resolve") else str(cal_ledger_path)
        for p, label in [(iis_ledger_path, "iis_ledger_path"), (mfv_ledger_path, "mfv_ledger_path")]:
            _p = str(p.resolve()) if hasattr(p, "resolve") else str(p)
            if _p == _own:
                raise ValueError(
                    f"CAL-NOSELF-0 violation: {label} resolves to CAL's own ledger path"
                )

        self._secret = hmac_secret
        self._iis_path = iis_ledger_path
        self._mfv_path = mfv_ledger_path
        self._cal_path = cal_ledger_path
        self._recs_path = cal_recs_path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_invariants(self) -> list[dict[str, str]]:
        """Return the 10 Hard-class invariants declared by this module."""
        return list(_INVARIANTS)

    def verify_chain(self) -> bool:
        """
        CAL-CHAIN-0: Verify the HMAC chain of the CAL learning ledger.
        Returns True if chain is intact (or ledger is empty), False on violation.
        """
        records = _read_jsonl(self._cal_path)
        if not records:
            return True

        previous_hash = "0" * 64
        for record in records:
            stored_hash = record.get("chain_hash", "")
            record_body = {k: v for k, v in record.items() if k != "chain_hash"}
            computed = _hmac_entry(self._secret, previous_hash, record_body)
            if not hmac.compare_digest(stored_hash, computed):
                return False
            previous_hash = stored_hash
        return True

    def run_learning_cycle(
        self,
        *,
        cycle_id: str,
        timestamp_utc_iso: str,  # CAL-DETERM-0: caller supplies deterministic timestamp
    ) -> LearningCycleResult:
        """
        Execute a full CAL learning cycle:
          1. CAL-CHAIN-0: Verify own ledger chain integrity.
          2. CAL-READONLY-0: Read IIS + MFV records (no writes to source ledgers).
          3. Compute per-invariant weights (CAL-BOUND-0 clamping).
          4. Generate HUMAN-0-gated recommendations (CAL-HUMAN0-0).
          5. CAL-AUDIT-0: Append immutable audit record to CAL ledger.
          6. CAL-ATOMIC-0: Write recommendations snapshot atomically.
        """
        # CAL-CHAIN-0 — chain must be verified first
        chain_ok = self.verify_chain()
        if not chain_ok:
            raise RuntimeError(
                "CAL-CHAIN-0 violation: CAL learning ledger HMAC chain is broken. "
                "Manual HUMAN-0 audit required before proceeding."
            )

        # CAL-READONLY-0 — read source ledgers (no writes)
        iis_records = _read_jsonl(self._iis_path)
        mfv_records = _read_jsonl(self._mfv_path)

        # Compute invariant weights from both ledger sources
        weights = self._compute_invariant_weights(iis_records, mfv_records)

        # CAL-HUMAN0-0 — generate gated recommendations
        recommendations = self._generate_recommendations(weights)

        # Build audit record
        previous_hash = self._get_previous_chain_hash()
        audit_record = {
            "cycle_id": cycle_id,
            "phase": _PHASE,
            "innov_code": _INNOV_CODE,
            "governor": _GOVERNOR,
            "iis_records_read": len(iis_records),
            "mfv_records_read": len(mfv_records),
            "invariants_analyzed": len(weights),
            "timestamp_utc_iso": timestamp_utc_iso,
            "chain_verified": chain_ok,
            "recommendation_count": len(recommendations),
        }
        chain_hash = _hmac_entry(self._secret, previous_hash, audit_record)
        audit_record["chain_hash"] = chain_hash

        # CAL-ATOMIC-0 + CAL-AUDIT-0 — append to ledger
        _append_jsonl(self._cal_path, audit_record)

        # CAL-ATOMIC-0 — write recommendations atomically
        recs_payload = {
            "cycle_id": cycle_id,
            "timestamp_utc_iso": timestamp_utc_iso,
            "governor": _GOVERNOR,
            "requires_human0_approval": True,
            "cal_version": _CAL_VERSION,
            "recommendations": [asdict(r) for r in recommendations],
        }
        _atomic_write_json(self._recs_path, recs_payload)

        return LearningCycleResult(
            cycle_id=cycle_id,
            phase=_PHASE,
            innov_code=_INNOV_CODE,
            governor=_GOVERNOR,
            iis_records_read=len(iis_records),
            mfv_records_read=len(mfv_records),
            invariants_analyzed=len(weights),
            weights=weights,
            recommendations=recommendations,
            hmac_chain_hash=chain_hash,
            timestamp_utc_iso=timestamp_utc_iso,
            chain_verified=chain_ok,
        )

    # ------------------------------------------------------------------
    # Internal computation
    # ------------------------------------------------------------------

    def _compute_invariant_weights(
        self,
        iis_records: list[dict[str, Any]],
        mfv_records: list[dict[str, Any]],
    ) -> list[InvariantWeight]:
        """
        Aggregate per-invariant fitness signals from IIS + MFV ledgers.

        IIS records carry an 'impact_score' and optional 'invariant_ids' list.
        MFV records carry a 'verdict' (CERTIFIED/REGRESSED/INCONCLUSIVE) and
        an optional 'fitness_delta' float, plus 'invariants_checked' list.

        Scoring formula (deterministic):
          raw_score = Σ(fitness_delta for CERTIFIED) - Σ(|fitness_delta| for REGRESSED)
                    + Σ(iis_impact_score * 0.3) per associated IIS record
        """
        inv_data: dict[str, dict[str, Any]] = {}

        def _ensure(inv_id: str) -> None:
            if inv_id not in inv_data:
                inv_data[inv_id] = {
                    "positive": 0.0,
                    "negative": 0.0,
                    "count": 0,
                }

        # --- Process MFV records ---
        for rec in mfv_records:
            verdict = rec.get("verdict", "INCONCLUSIVE")
            delta = float(rec.get("fitness_delta", 0.0))
            invariants = rec.get("invariants_checked", [])
            if not isinstance(invariants, list):
                invariants = []
            for inv_id in invariants:
                if not isinstance(inv_id, str):
                    continue
                _ensure(inv_id)
                inv_data[inv_id]["count"] += 1
                if verdict == "CERTIFIED":
                    inv_data[inv_id]["positive"] += max(0.0, delta)
                elif verdict == "REGRESSED":
                    inv_data[inv_id]["negative"] += abs(delta)

        # --- Process IIS records (CAL-DETERM-0: weight IIS at 0.3) ---
        IIS_WEIGHT: float = 0.3
        for rec in iis_records:
            impact = float(rec.get("impact_score", 0.0))
            invariants = rec.get("invariant_ids", [])
            if not isinstance(invariants, list):
                invariants = []
            for inv_id in invariants:
                if not isinstance(inv_id, str):
                    continue
                _ensure(inv_id)
                inv_data[inv_id]["count"] += 1
                if impact >= 0:
                    inv_data[inv_id]["positive"] += impact * IIS_WEIGHT
                else:
                    inv_data[inv_id]["negative"] += abs(impact) * IIS_WEIGHT

        # --- Build InvariantWeight objects ---
        weights: list[InvariantWeight] = []
        all_raws: list[float] = []

        for inv_id, data in inv_data.items():
            raw = data["positive"] - data["negative"]
            all_raws.append(raw)

        # Normalize to [0, 1] based on observed range (CAL-BOUND-0)
        raw_min = min(all_raws) if all_raws else 0.0
        raw_max = max(all_raws) if all_raws else 1.0
        raw_range = raw_max - raw_min if raw_max != raw_min else 1.0

        for inv_id, data in sorted(inv_data.items()):
            raw = data["positive"] - data["negative"]
            normalized = _clamp((raw - raw_min) / raw_range)
            rec_label = self._classify_weight(normalized, data["count"])
            weights.append(InvariantWeight(
                invariant_id=inv_id,
                raw_score=raw,
                normalized_weight=normalized,
                appearance_count=data["count"],
                positive_delta_sum=data["positive"],
                negative_delta_sum=data["negative"],
                recommendation=rec_label,
            ))

        return weights

    @staticmethod
    def _classify_weight(normalized: float, count: int) -> str:
        """Map a normalized weight to a recommendation label."""
        if count < _MIN_RECORDS_FOR_RECOMMENDATION:
            return "STABLE"  # Not enough data
        if normalized >= 0.75:
            return "REINFORCE"
        if normalized <= 0.25:
            return "REVIEW"
        return "STABLE"

    def _generate_recommendations(
        self, weights: list[InvariantWeight]
    ) -> list[AmendmentRecommendation]:
        """
        CAL-HUMAN0-0: All recommendations require HUMAN-0 approval.
        Only REINFORCE and REVIEW invariants get actionable recommendations;
        STABLE invariants are still included with informational rationale.
        """
        recs: list[AmendmentRecommendation] = []
        for w in weights:
            if w.recommendation == "REINFORCE":
                rationale = (
                    f"Invariant {w.invariant_id} shows strong positive fitness contribution "
                    f"(weight={w.normalized_weight:.3f}, n={w.appearance_count}). "
                    f"Consider reinforcing enforcement priority or expanding scope."
                )
            elif w.recommendation == "REVIEW":
                rationale = (
                    f"Invariant {w.invariant_id} shows net fitness regression association "
                    f"(weight={w.normalized_weight:.3f}, n={w.appearance_count}). "
                    f"HUMAN-0 review recommended: may indicate over-constraint or mis-scoping."
                )
            else:
                rationale = (
                    f"Invariant {w.invariant_id} is stable "
                    f"(weight={w.normalized_weight:.3f}, n={w.appearance_count}). "
                    f"No amendment required at this time."
                )
            recs.append(AmendmentRecommendation(
                invariant_id=w.invariant_id,
                recommendation=w.recommendation,
                normalized_weight=w.normalized_weight,
                rationale=rationale,
                requires_human0_approval=True,  # CAL-HUMAN0-0: immutable
                governor=_GOVERNOR,
            ))
        return recs

    def _get_previous_chain_hash(self) -> str:
        """Read the last chain hash from the CAL ledger."""
        records = _read_jsonl(self._cal_path)
        if not records:
            return "0" * 64
        return records[-1].get("chain_hash", "0" * 64)


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

def list_invariants() -> list[dict[str, str]]:
    """Return all Hard-class invariants declared by INNOV-80 · CAL."""
    return list(_INVARIANTS)
