# SPDX-License-Identifier: Apache-2.0
"""INNOV-60 · Constitutional Pre-Admission Gate (CPAG) — Phase 154 / v9.87.0

First line of constitutional defence: evaluates every proposed mutation
against the active Hard-class invariant set *before* it enters the
execution pipeline.  CPAG produces a deterministic AdmissionVerdict
(ADMIT / DEFER / REJECT) with full per-invariant rationale, writes the
result to the HMAC-chained ledger, and integrates with the AMT throttle
multiplier so admission thresholds tighten as system pressure rises.

Pipeline position
-----------------

  [Proposer] → CPAG (score + gate) → [CEL Pipeline]
                     ↑                      ↓
                 AMT throttle           GCB / GRB

Hard-class invariants
---------------------
CPAG-DETERM-0  : AdmissionVerdict is a pure deterministic function of
                 (mutation_spec, invariant_set, throttle_multiplier,
                  thresholds).  Timestamps and entropy are excluded from
                 the scoring algorithm.  Identical inputs always produce
                 identical verdicts.

CPAG-LEDGER-0  : Every gate() call writes an ADMISSION_VERDICT record to
                 the HMAC-chained ledger *before* the verdict is returned.
                 A ledger-write failure raises CPAGLedgerError; no verdict
                 is returned on failure.

CPAG-FAILCLOSE-0: When the gate verdict is REJECT or when the admission
                 score falls below the HUMAN-0-configurable reject_floor,
                 the gate raises CPAGRejectionError — it never silently
                 passes a rejected mutation.  The caller must explicitly
                 catch and handle rejections.

CPAG-HUMAN0-0  : Threshold configuration (admit_min, defer_min,
                 reject_floor) requires a non-empty HUMAN-0 operator
                 identity.  Empty / None operator raises CPAGAuthError
                 before any config change occurs.

CPAG-SCOPE-0   : CPAG evaluates only the mutation_spec dict and the
                 invariant_set provided by the caller.  It never reads
                 live file system state, process memory, external APIs,
                 or the ledger during scoring.  Scope violations raise
                 CPAGScopeError.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

CPAG_VERSION: str = "1.0.0"
INNOV_ID: str = "INNOV-60"

# ---------------------------------------------------------------------------
# HMAC key
# ---------------------------------------------------------------------------

_HMAC_KEY: bytes = os.getenv(
    "ADAAD_CPAG_HMAC_KEY", "cpag-default-key-change-in-prod"
).encode()

# ---------------------------------------------------------------------------
# Verdict constants
# ---------------------------------------------------------------------------

EVENT_ADMISSION_VERDICT = "ADMISSION_VERDICT"
EVENT_THRESHOLD_CONFIG = "THRESHOLD_CONFIG"

# ---------------------------------------------------------------------------
# Typed exceptions — one per Hard-class invariant
# ---------------------------------------------------------------------------


class CPAGDeterminismError(RuntimeError):
    """CPAG-DETERM-0: verdict computation is non-deterministic."""


class CPAGLedgerError(RuntimeError):
    """CPAG-LEDGER-0: ledger write failed before verdict was returned."""


class CPAGRejectionError(RuntimeError):
    """CPAG-FAILCLOSE-0: mutation rejected by constitutional gate."""

    def __init__(self, message: str, verdict: "AdmissionVerdict") -> None:
        super().__init__(message)
        self.verdict = verdict


class CPAGAuthError(RuntimeError):
    """CPAG-HUMAN0-0: threshold config requires non-empty HUMAN-0 operator."""


class CPAGScopeError(RuntimeError):
    """CPAG-SCOPE-0: CPAG attempted to read disallowed external state."""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


class VerdictResult(str, Enum):
    ADMIT = "ADMIT"    # score ≥ admit_min: cleared for pipeline entry
    DEFER = "DEFER"   # defer_min ≤ score < admit_min: hold for review
    REJECT = "REJECT"  # score < reject_floor OR hard violation detected


@dataclass(frozen=True)
class InvariantEval:
    """Per-invariant evaluation result (immutable)."""
    invariant_id: str
    tier: str            # "Hard" | "Soft"
    passed: bool
    rationale: str
    weight: float        # contribution to score


@dataclass(frozen=True)
class AdmissionVerdict:
    """Immutable gate result (CPAG-DETERM-0)."""
    result: VerdictResult
    score: float                          # 0.0–1.0 constitutional fitness
    hard_violations: int
    soft_violations: int
    evaluations: tuple[InvariantEval, ...]
    mutation_id: str
    throttle_multiplier: float
    effective_admit_min: float            # admit_min adjusted by throttle
    ledger_seq: int
    ledger_digest: str
    innov_id: str = INNOV_ID
    cpag_version: str = CPAG_VERSION


@dataclass
class CPAGConfig:
    """Mutable threshold config (changes require HUMAN-0)."""
    admit_min: float = 0.80    # score ≥ admit_min → ADMIT
    defer_min: float = 0.50    # score ≥ defer_min → DEFER, else REJECT
    reject_floor: float = 0.50 # score below this always → REJECT (failclose)

    @classmethod
    def default(cls) -> "CPAGConfig":
        return cls()

    @classmethod
    def strict(cls) -> "CPAGConfig":
        """High-pressure preset: tighter gates."""
        return cls(admit_min=0.90, defer_min=0.70, reject_floor=0.70)


# ---------------------------------------------------------------------------
# Invariant set representation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ConstitutionalInvariant:
    """Represents one invariant in the evaluation set."""
    id: str
    tier: str           # "Hard" | "Soft"
    description: str
    weight: float = 1.0
    check_keys: tuple[str, ...] = field(default_factory=tuple)
    forbidden_values: tuple[Any, ...] = field(default_factory=tuple)


def default_invariant_set() -> list[ConstitutionalInvariant]:
    """Minimal default invariant set for mutation pre-admission checks.

    In production this would be loaded from the canonical invariant registry.
    The set here covers the structural properties most commonly violated by
    malformed mutations.
    """
    return [
        ConstitutionalInvariant(
            id="INV-LEDGER-FIRST",
            tier="Hard",
            description="Mutation spec must declare ledger_first=True",
            weight=2.0,
            check_keys=("ledger_first",),
            forbidden_values=(False, None),
        ),
        ConstitutionalInvariant(
            id="INV-HUMAN0-PRESENT",
            tier="Hard",
            description="Mutation spec must carry a non-empty operator field",
            weight=2.0,
            check_keys=("operator",),
            forbidden_values=("", None),
        ),
        ConstitutionalInvariant(
            id="INV-DETERM",
            tier="Hard",
            description="Mutation spec must declare deterministic=True",
            weight=1.5,
            check_keys=("deterministic",),
            forbidden_values=(False, None),
        ),
        ConstitutionalInvariant(
            id="INV-REPLAY-SAFE",
            tier="Hard",
            description="Mutation spec must not contain entropy_source",
            weight=1.5,
            check_keys=("entropy_source",),
            forbidden_values=("random", "uuid", "time"),
        ),
        ConstitutionalInvariant(
            id="INV-SCOPE",
            tier="Soft",
            description="Mutation spec should declare affected_modules",
            weight=0.5,
            check_keys=("affected_modules",),
            forbidden_values=(None, []),
        ),
        ConstitutionalInvariant(
            id="INV-INNOV-ID",
            tier="Soft",
            description="Mutation spec should carry an innovation_id reference",
            weight=0.5,
            check_keys=("innovation_id",),
            forbidden_values=(None, ""),
        ),
    ]


# ---------------------------------------------------------------------------
# HMAC chain helpers
# ---------------------------------------------------------------------------

def _hmac_digest(payload: str, prev_digest: str) -> str:
    chain_input = f"{prev_digest}:{payload}".encode()
    return hmac.new(_HMAC_KEY, chain_input, hashlib.sha256).hexdigest()


def _build_event(
    event_type: str, payload: dict, prev_digest: str, seq: int
) -> tuple[dict, str]:
    body = json.dumps(
        {"seq": seq, "event_type": event_type, **payload}, sort_keys=True
    )
    digest = _hmac_digest(body, prev_digest)
    record = json.loads(body)
    record["digest"] = digest
    return record, digest


# ---------------------------------------------------------------------------
# CPAG Ledger
# ---------------------------------------------------------------------------

class CPAGLedger:
    """Append-only HMAC-chained ledger for CPAG admission events."""

    def __init__(self, path: Optional[str] = None) -> None:
        self._path = path
        self._chain: List[dict] = []
        self._prev_digest: str = "0" * 64
        self._seq: int = 0

    def append(self, event_type: str, payload: dict) -> tuple[int, str]:
        self._seq += 1
        record, digest = _build_event(
            event_type, payload, self._prev_digest, self._seq
        )
        self._chain.append(record)
        self._prev_digest = digest
        if self._path is not None:
            try:
                with open(self._path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record) + "\n")
            except OSError as exc:
                raise CPAGLedgerError(
                    f"CPAG-LEDGER-0 violated: ledger write failed — {exc}"
                ) from exc
        return self._seq, digest

    def records(self) -> List[dict]:
        return list(self._chain)

    def verify_chain(self) -> bool:
        prev = "0" * 64
        for rec in self._chain:
            body = json.dumps(
                {k: v for k, v in rec.items() if k != "digest"}, sort_keys=True
            )
            expected = _hmac_digest(body, prev)
            if not hmac.compare_digest(expected, rec["digest"]):
                return False
            prev = rec["digest"]
        return True


# ---------------------------------------------------------------------------
# Scorer — pure deterministic evaluation (CPAG-DETERM-0)
# ---------------------------------------------------------------------------

def _score_invariant(
    inv: ConstitutionalInvariant,
    spec: Dict[str, Any],
) -> InvariantEval:
    """Evaluate one invariant against a mutation spec.  Pure function.

    CPAG-SCOPE-0: reads only `spec` — no I/O, no imports, no side effects.
    """
    for key in inv.check_keys:
        value = spec.get(key)
        if value in inv.forbidden_values:
            return InvariantEval(
                invariant_id=inv.id,
                tier=inv.tier,
                passed=False,
                rationale=(
                    f"Field '{key}' has forbidden value {value!r}. "
                    f"Invariant: {inv.description}"
                ),
                weight=inv.weight,
            )
    return InvariantEval(
        invariant_id=inv.id,
        tier=inv.tier,
        passed=True,
        rationale=f"All checks passed for '{inv.id}'.",
        weight=inv.weight,
    )


def _compute_score(
    evals: Sequence[InvariantEval],
) -> float:
    """Weighted constitutional fitness score [0.0, 1.0].  Pure function."""
    total_weight = sum(e.weight for e in evals)
    if total_weight == 0:
        raise CPAGDeterminismError(
            "CPAG-DETERM-0: invariant weights sum to zero — undefined score"
        )
    passed_weight = sum(e.weight for e in evals if e.passed)
    return round(passed_weight / total_weight, 6)


def _effective_admit_min(admit_min: float, throttle: float) -> float:
    """Raise the admission bar when the system is throttled (AMT integration).

    As throttle multiplier drops toward AMT_FLOOR the admit_min tightens
    toward 1.0, making it harder to enter the pipeline under pressure.
    """
    # When throttle=1.0 → no change.  When throttle=0.05 → admit_min raised by ~0.15
    tightening = (1.0 - throttle) * 0.15
    return round(min(1.0, admit_min + tightening), 6)


def _classify_verdict(
    score: float,
    hard_violations: int,
    eff_admit_min: float,
    defer_min: float,
    reject_floor: float,
) -> VerdictResult:
    """Deterministic verdict from score + violation counts."""
    if hard_violations > 0 or score < reject_floor:
        return VerdictResult.REJECT
    if score >= eff_admit_min:
        return VerdictResult.ADMIT
    if score >= defer_min:
        return VerdictResult.DEFER
    return VerdictResult.REJECT


# ---------------------------------------------------------------------------
# Gate engine
# ---------------------------------------------------------------------------

class ConstitutionalGate:
    """CPAG engine — evaluates and gates mutation proposals.

    Usage
    -----
    gate = ConstitutionalGate()
    try:
        verdict = gate.gate(mutation_spec, throttle_multiplier=0.85)
    except CPAGRejectionError as exc:
        handle_rejection(exc.verdict)
    """

    def __init__(
        self,
        config: Optional[CPAGConfig] = None,
        invariant_set: Optional[List[ConstitutionalInvariant]] = None,
        ledger: Optional[CPAGLedger] = None,
    ) -> None:
        self._config = config or CPAGConfig.default()
        self._invariants = invariant_set or default_invariant_set()
        self._ledger = ledger or CPAGLedger()

    # ------------------------------------------------------------------
    def gate(
        self,
        mutation_spec: Dict[str, Any],
        throttle_multiplier: float = 1.0,
        mutation_id: Optional[str] = None,
    ) -> AdmissionVerdict:
        """Evaluate mutation_spec and return AdmissionVerdict.

        Parameters
        ----------
        mutation_spec       : proposer-supplied dict describing the mutation
        throttle_multiplier : current AMT multiplier [0.0, 1.0]; tightens
                              admission thresholds under system pressure
        mutation_id         : optional stable ID for the proposal

        Returns
        -------
        AdmissionVerdict with result ADMIT or DEFER

        Raises
        ------
        CPAGRejectionError   on REJECT (CPAG-FAILCLOSE-0)
        CPAGLedgerError      if ledger write fails (CPAG-LEDGER-0)
        CPAGScopeError       if a scope violation is detected
        """
        # CPAG-SCOPE-0: spec must be a plain dict
        if not isinstance(mutation_spec, dict):
            raise CPAGScopeError(
                "CPAG-SCOPE-0: mutation_spec must be a plain dict; "
                f"got {type(mutation_spec).__name__}"
            )

        mut_id = mutation_id or _stable_id(mutation_spec)

        # Deterministic per-invariant evaluation (CPAG-DETERM-0, CPAG-SCOPE-0)
        evals: List[InvariantEval] = [
            _score_invariant(inv, mutation_spec)
            for inv in self._invariants
        ]

        score = _compute_score(evals)
        hard_violations = sum(
            1 for e in evals if not e.passed and e.tier == "Hard"
        )
        soft_violations = sum(
            1 for e in evals if not e.passed and e.tier == "Soft"
        )

        cfg = self._config
        eff_admit = _effective_admit_min(cfg.admit_min, throttle_multiplier)
        result = _classify_verdict(
            score, hard_violations, eff_admit, cfg.defer_min, cfg.reject_floor
        )

        # CPAG-LEDGER-0: write before returning
        eval_payload = [
            {
                "id": e.invariant_id,
                "tier": e.tier,
                "passed": e.passed,
                "rationale": e.rationale,
                "weight": e.weight,
            }
            for e in evals
        ]
        payload = {
            "mutation_id": mut_id,
            "result": result.value,
            "score": score,
            "hard_violations": hard_violations,
            "soft_violations": soft_violations,
            "throttle_multiplier": throttle_multiplier,
            "effective_admit_min": eff_admit,
            "evaluations": eval_payload,
        }
        seq, digest = self._ledger.append(EVENT_ADMISSION_VERDICT, payload)

        verdict = AdmissionVerdict(
            result=result,
            score=score,
            hard_violations=hard_violations,
            soft_violations=soft_violations,
            evaluations=tuple(evals),
            mutation_id=mut_id,
            throttle_multiplier=throttle_multiplier,
            effective_admit_min=eff_admit,
            ledger_seq=seq,
            ledger_digest=digest,
        )

        # CPAG-FAILCLOSE-0: raise on REJECT — never silently pass
        if result == VerdictResult.REJECT:
            raise CPAGRejectionError(
                f"CPAG-FAILCLOSE-0: mutation '{mut_id}' REJECTED "
                f"(score={score:.3f}, hard_violations={hard_violations})",
                verdict=verdict,
            )

        return verdict

    # ------------------------------------------------------------------
    # Threshold configuration (CPAG-HUMAN0-0)
    # ------------------------------------------------------------------

    def reconfigure_thresholds(
        self,
        admit_min: float,
        defer_min: float,
        reject_floor: float,
        operator: str,
    ) -> tuple[int, str]:
        """Update admission thresholds. Requires HUMAN-0 operator."""
        if not operator or not operator.strip():
            raise CPAGAuthError(
                "CPAG-HUMAN0-0: threshold reconfiguration requires "
                "non-empty HUMAN-0 operator identity"
            )
        self._config.admit_min = admit_min
        self._config.defer_min = defer_min
        self._config.reject_floor = reject_floor
        return self._ledger.append(
            EVENT_THRESHOLD_CONFIG,
            {
                "operator": operator.strip(),
                "admit_min": admit_min,
                "defer_min": defer_min,
                "reject_floor": reject_floor,
            },
        )

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def ledger(self) -> CPAGLedger:
        return self._ledger

    def verify_ledger(self) -> bool:
        return self._ledger.verify_chain()

    def admission_history(self) -> List[AdmissionVerdict]:
        """Reconstruct verdict history from ledger records."""
        out: List[AdmissionVerdict] = []
        for rec in self._ledger.records():
            if rec.get("event_type") != EVENT_ADMISSION_VERDICT:
                continue
            evals = tuple(
                InvariantEval(
                    invariant_id=e["id"],
                    tier=e["tier"],
                    passed=e["passed"],
                    rationale=e["rationale"],
                    weight=e["weight"],
                )
                for e in rec.get("evaluations", [])
            )
            out.append(
                AdmissionVerdict(
                    result=VerdictResult(rec["result"]),
                    score=rec["score"],
                    hard_violations=rec["hard_violations"],
                    soft_violations=rec["soft_violations"],
                    evaluations=evals,
                    mutation_id=rec["mutation_id"],
                    throttle_multiplier=rec["throttle_multiplier"],
                    effective_admit_min=rec["effective_admit_min"],
                    ledger_seq=rec["seq"],
                    ledger_digest=rec["digest"],
                )
            )
        return out

    def config(self) -> CPAGConfig:
        return self._config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stable_id(spec: dict) -> str:
    """Deterministic mutation ID from spec content (CPAG-DETERM-0)."""
    canonical = json.dumps(spec, sort_keys=True).encode()
    return hashlib.sha256(canonical).hexdigest()[:16]
