# SPDX-License-Identifier: Apache-2.0
"""INNOV-59 · Adaptive Mutation Throttle (AMT) — Phase 153 / v9.86.0

Feedback-control governor that reads Constitutional Pressure Index (CPI)
snapshots from the HMAC-chained ledger and continuously adjusts a
throttle multiplier (0.0–1.0) governing mutation pipeline admission rate.

When CPI domain pressure rises the throttle tightens — reducing mutation
throughput proportionally — before the Governance Circuit Breaker (GCB)
needs to trip.  This closes the control loop:

    CPI (sense) → AMT (govern) → GCB (last resort) → GRB (recover)

Hard-class invariants
---------------------
AMT-DETERM-0  : Throttle multiplier is a pure deterministic function of
                (pressure_snapshot, weights, floor); identical inputs always
                produce identical output.  Timestamps and entropy are
                excluded from the throttle algorithm.

AMT-LEDGER-0  : Every ThrottleEngine.compute() call writes a
                THROTTLE_EVENT to the HMAC-chained ledger *before* the
                multiplier is returned.  A ledger-write failure raises
                AMTLedgerError; no multiplier is returned on failure.

AMT-FLOOR-0   : The throttle multiplier never falls below AMT_FLOOR
                (default 0.05) during normal operation.  Only an explicit
                HUMAN-0-authorised emergency override may set multiplier
                to 0.0 (full-stop).  Violation raises AMTFloorError.

AMT-HUMAN0-0  : Emergency override (multiplier = 0.0) and throttle-weight
                reconfiguration both require a non-empty HUMAN-0 operator
                identity.  Empty / None operator raises AMTAuthError before
                any state change occurs.

AMT-FEEDBACK-0: AMT reads *only* THROTTLE_EVENT and PRESSURE_SNAPSHOT
                records from the HMAC-chained ledger.  It never reads live
                system state, process memory, or external APIs.
                Violations raise AMTScopeError.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Sequence

# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

AMT_VERSION: str = "1.0.0"
INNOV_ID: str = "INNOV-59"

# ---------------------------------------------------------------------------
# HMAC key
# ---------------------------------------------------------------------------

_HMAC_KEY: bytes = os.getenv(
    "ADAAD_AMT_HMAC_KEY", "amt-default-key-change-in-prod"
).encode()

# ---------------------------------------------------------------------------
# Constitutional floor
# ---------------------------------------------------------------------------

AMT_FLOOR: float = 0.05        # minimum throttle multiplier (AMT-FLOOR-0)
AMT_FULL_STOP: float = 0.0     # only reachable via HUMAN-0 override

# Ledger event types
EVENT_THROTTLE_EVENT = "THROTTLE_EVENT"
EVENT_EMERGENCY_OVERRIDE = "EMERGENCY_OVERRIDE"
EVENT_WEIGHT_CONFIG = "WEIGHT_CONFIG"

# Ledger record types consumed by AMT (AMT-FEEDBACK-0)
_ALLOWED_INGEST_TYPES: frozenset[str] = frozenset(
    {"THROTTLE_EVENT", "PRESSURE_SNAPSHOT"}
)

# ---------------------------------------------------------------------------
# Typed exceptions — one per Hard-class invariant
# ---------------------------------------------------------------------------


class AMTDeterminismError(RuntimeError):
    """AMT-DETERM-0: throttle computation is non-deterministic."""


class AMTLedgerError(RuntimeError):
    """AMT-LEDGER-0: ledger write failed before multiplier was returned."""


class AMTFloorError(RuntimeError):
    """AMT-FLOOR-0: multiplier would fall below constitutional floor."""


class AMTAuthError(RuntimeError):
    """AMT-HUMAN0-0: operation requires non-empty HUMAN-0 operator."""


class AMTScopeError(RuntimeError):
    """AMT-FEEDBACK-0: AMT attempted to read disallowed ledger record type."""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


class ThrottleRegime(str, Enum):
    OPEN = "OPEN"          # 0.8–1.0: normal operation
    CAUTION = "CAUTION"   # 0.4–0.8: elevated pressure
    RESTRICT = "RESTRICT"  # 0.05–0.4: high pressure
    OVERRIDE = "OVERRIDE"  # 0.0: HUMAN-0 emergency stop


@dataclass(frozen=True)
class DomainWeight:
    """Weight assigned to each CPI domain for throttle computation."""
    domain: str
    weight: float  # 0.0–1.0; weights must sum to 1.0 across all domains


@dataclass(frozen=True)
class ThrottleSnapshot:
    """Immutable throttle computation result (AMT-DETERM-0)."""
    multiplier: float
    regime: ThrottleRegime
    domain_contributions: Dict[str, float]
    composite_pressure: float
    ledger_seq: int
    ledger_digest: str
    innov_id: str = INNOV_ID
    amt_version: str = AMT_VERSION


@dataclass
class AMTConfig:
    """Mutable configuration (weight changes require HUMAN-0)."""
    domain_weights: Dict[str, float] = field(default_factory=dict)
    floor: float = AMT_FLOOR
    caution_threshold: float = 0.40   # composite pressure → CAUTION regime
    restrict_threshold: float = 0.70  # composite pressure → RESTRICT regime

    def total_weight(self) -> float:
        return sum(self.domain_weights.values())

    @classmethod
    def default(cls) -> "AMTConfig":
        return cls(
            domain_weights={
                "SECURITY": 0.25,
                "DETERMINISM": 0.20,
                "REPLAY": 0.15,
                "HUMAN0": 0.20,
                "MUTATION": 0.10,
                "LEDGER": 0.10,
            }
        )


# ---------------------------------------------------------------------------
# HMAC chain helpers
# ---------------------------------------------------------------------------

def _hmac_digest(payload: str, prev_digest: str) -> str:
    chain_input = f"{prev_digest}:{payload}".encode()
    return hmac.new(_HMAC_KEY, chain_input, hashlib.sha256).hexdigest()


def _build_event(
    event_type: str,
    payload: dict,
    prev_digest: str,
    seq: int,
) -> tuple[dict, str]:
    body = json.dumps(
        {"seq": seq, "event_type": event_type, **payload},
        sort_keys=True,
    )
    digest = _hmac_digest(body, prev_digest)
    record = json.loads(body)
    record["digest"] = digest
    return record, digest


# ---------------------------------------------------------------------------
# Ledger writer
# ---------------------------------------------------------------------------

class AMTLedger:
    """Append-only HMAC-chained ledger for AMT events (AMT-LEDGER-0)."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = path
        self._chain: List[dict] = []
        self._prev_digest: str = "0" * 64
        self._seq: int = 0

    # ------------------------------------------------------------------
    def append(self, event_type: str, payload: dict) -> tuple[int, str]:
        """Write a chained event.  Returns (seq, digest)."""
        self._seq += 1
        record, digest = _build_event(
            event_type, payload, self._prev_digest, self._seq
        )
        self._chain.append(record)
        self._prev_digest = digest
        if self._path is not None:
            try:
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record) + "\n")
            except OSError as exc:
                raise AMTLedgerError(
                    f"AMT-LEDGER-0 violated: ledger write failed — {exc}"
                ) from exc
        return self._seq, digest

    # ------------------------------------------------------------------
    def records(self) -> List[dict]:
        return list(self._chain)

    # ------------------------------------------------------------------
    def verify_chain(self) -> bool:
        """Return True if every record's digest is consistent."""
        prev = "0" * 64
        for rec in self._chain:
            body = json.dumps(
                {k: v for k, v in rec.items() if k != "digest"},
                sort_keys=True,
            )
            expected = _hmac_digest(body, prev)
            if not hmac.compare_digest(expected, rec["digest"]):
                return False
            prev = rec["digest"]
        return True

    # ------------------------------------------------------------------
    def filter_allowed(self, records: Sequence[dict]) -> List[dict]:
        """AMT-FEEDBACK-0: reject any record whose event_type is not in
        the allowed ingestion set."""
        out: List[dict] = []
        for rec in records:
            evt = rec.get("event_type", "")
            if evt not in _ALLOWED_INGEST_TYPES:
                raise AMTScopeError(
                    f"AMT-FEEDBACK-0 violated: AMT may not ingest "
                    f"record type '{evt}'"
                )
            out.append(rec)
        return out


# ---------------------------------------------------------------------------
# Throttle engine
# ---------------------------------------------------------------------------

class ThrottleEngine:
    """Core AMT engine — computes throttle multiplier from CPI pressure.

    Every compute() call:
    1. Validates inputs deterministically (AMT-DETERM-0).
    2. Computes composite pressure from domain scores × weights.
    3. Derives multiplier via monotone piecewise-linear mapping.
    4. Writes THROTTLE_EVENT to ledger *before* returning (AMT-LEDGER-0).
    5. Enforces constitutional floor (AMT-FLOOR-0).
    """

    def __init__(
        self,
        config: Optional[AMTConfig] = None,
        ledger: Optional[AMTLedger] = None,
    ) -> None:
        self._config = config or AMTConfig.default()
        self._ledger = ledger or AMTLedger()
        self._override_active: bool = False
        self._override_operator: Optional[str] = None

    # ------------------------------------------------------------------
    # Private: deterministic pressure → multiplier mapping (AMT-DETERM-0)
    # ------------------------------------------------------------------

    @staticmethod
    def _pressure_to_multiplier(
        composite: float,
        floor: float,
        caution_threshold: float,
        restrict_threshold: float,
    ) -> float:
        """Pure function: composite pressure [0,1] → multiplier [floor,1].

        Piecewise linear:
          0.0                     → 1.0  (no restriction)
          caution_threshold       → 0.70 (light restriction)
          restrict_threshold      → floor (heavy restriction)
          above restrict_threshold→ floor (clamp at floor)
        """
        composite = max(0.0, min(1.0, composite))
        if composite <= caution_threshold:
            # linear 0→caution: 1.0 → 0.70
            ratio = composite / caution_threshold if caution_threshold > 0 else 0.0
            return round(1.0 - ratio * 0.30, 6)
        elif composite <= restrict_threshold:
            # linear caution→restrict: 0.70 → floor
            span = restrict_threshold - caution_threshold
            ratio = (composite - caution_threshold) / span if span > 0 else 1.0
            return round(0.70 - ratio * (0.70 - floor), 6)
        else:
            return round(floor, 6)

    @staticmethod
    def _classify_regime(
        multiplier: float,
        caution_threshold: float,
        restrict_threshold: float,
        floor: float,
        override: bool,
    ) -> ThrottleRegime:
        if override:
            return ThrottleRegime.OVERRIDE
        if multiplier >= 0.80:
            return ThrottleRegime.OPEN
        if multiplier >= 0.40:
            return ThrottleRegime.CAUTION
        return ThrottleRegime.RESTRICT

    # ------------------------------------------------------------------
    # Public: compute throttle snapshot
    # ------------------------------------------------------------------

    def compute(self, domain_scores: Dict[str, float]) -> ThrottleSnapshot:
        """Compute throttle multiplier from CPI domain pressure scores.

        Parameters
        ----------
        domain_scores : mapping of domain name → pressure score [0.0, 1.0]

        Returns
        -------
        ThrottleSnapshot (immutable)

        Raises
        ------
        AMTLedgerError   if ledger write fails (AMT-LEDGER-0)
        AMTFloorError    if computed multiplier would undercut floor
        """
        cfg = self._config

        # Validate weights sum (AMT-DETERM-0)
        total_w = cfg.total_weight()
        if total_w == 0:
            raise AMTDeterminismError(
                "AMT-DETERM-0: domain weights sum to zero — undefined behaviour"
            )

        # Compute weighted composite pressure (deterministic)
        contributions: Dict[str, float] = {}
        composite: float = 0.0
        for domain, weight in cfg.domain_weights.items():
            score = float(domain_scores.get(domain, 0.0))
            contrib = score * weight / total_w
            contributions[domain] = round(contrib, 8)
            composite += contrib
        composite = round(composite, 8)

        # If emergency override is active, multiplier = 0.0
        if self._override_active:
            multiplier = AMT_FULL_STOP
        else:
            multiplier = self._pressure_to_multiplier(
                composite,
                cfg.floor,
                cfg.caution_threshold,
                cfg.restrict_threshold,
            )
            # AMT-FLOOR-0: enforce floor
            if multiplier < cfg.floor and not self._override_active:
                raise AMTFloorError(
                    f"AMT-FLOOR-0: computed multiplier {multiplier} < "
                    f"constitutional floor {cfg.floor}"
                )

        regime = self._classify_regime(
            multiplier,
            cfg.caution_threshold,
            cfg.restrict_threshold,
            cfg.floor,
            self._override_active,
        )

        # AMT-LEDGER-0: write before returning
        payload = {
            "multiplier": multiplier,
            "composite_pressure": composite,
            "regime": regime.value,
            "domain_contributions": contributions,
            "domain_scores_input": domain_scores,
            "override_active": self._override_active,
        }
        seq, digest = self._ledger.append(EVENT_THROTTLE_EVENT, payload)

        return ThrottleSnapshot(
            multiplier=multiplier,
            regime=regime,
            domain_contributions=contributions,
            composite_pressure=composite,
            ledger_seq=seq,
            ledger_digest=digest,
        )

    # ------------------------------------------------------------------
    # Emergency override (AMT-HUMAN0-0)
    # ------------------------------------------------------------------

    def engage_emergency_override(self, operator: str) -> tuple[int, str]:
        """Set multiplier to 0.0 (full stop). Requires HUMAN-0 identity."""
        if not operator or not operator.strip():
            raise AMTAuthError(
                "AMT-HUMAN0-0: emergency override requires non-empty operator"
            )
        self._override_active = True
        self._override_operator = operator.strip()
        return self._ledger.append(
            EVENT_EMERGENCY_OVERRIDE,
            {"operator": self._override_operator, "action": "ENGAGE"},
        )

    def release_emergency_override(self, operator: str) -> tuple[int, str]:
        """Release emergency full-stop. Requires HUMAN-0 identity."""
        if not operator or not operator.strip():
            raise AMTAuthError(
                "AMT-HUMAN0-0: override release requires non-empty operator"
            )
        self._override_active = False
        self._override_operator = None
        return self._ledger.append(
            EVENT_EMERGENCY_OVERRIDE,
            {"operator": operator.strip(), "action": "RELEASE"},
        )

    def override_active(self) -> bool:
        return self._override_active

    # ------------------------------------------------------------------
    # Weight reconfiguration (AMT-HUMAN0-0)
    # ------------------------------------------------------------------

    def reconfigure_weights(
        self,
        new_weights: Dict[str, float],
        operator: str,
    ) -> tuple[int, str]:
        """Update domain weights. Requires HUMAN-0 operator identity."""
        if not operator or not operator.strip():
            raise AMTAuthError(
                "AMT-HUMAN0-0: weight reconfiguration requires non-empty operator"
            )
        total = sum(new_weights.values())
        if total == 0:
            raise AMTDeterminismError(
                "AMT-DETERM-0: new weights sum to zero"
            )
        self._config.domain_weights = dict(new_weights)
        return self._ledger.append(
            EVENT_WEIGHT_CONFIG,
            {
                "operator": operator.strip(),
                "new_weights": new_weights,
                "total": total,
            },
        )

    # ------------------------------------------------------------------
    # Ledger access
    # ------------------------------------------------------------------

    def ledger(self) -> AMTLedger:
        return self._ledger

    def verify_ledger(self) -> bool:
        return self._ledger.verify_chain()

    def throttle_history(self) -> List[ThrottleSnapshot]:
        """Return all THROTTLE_EVENT records as ThrottleSnapshot instances."""
        out: List[ThrottleSnapshot] = []
        for rec in self._ledger.records():
            if rec.get("event_type") != EVENT_THROTTLE_EVENT:
                continue
            out.append(
                ThrottleSnapshot(
                    multiplier=rec["multiplier"],
                    regime=ThrottleRegime(rec["regime"]),
                    domain_contributions=rec["domain_contributions"],
                    composite_pressure=rec["composite_pressure"],
                    ledger_seq=rec["seq"],
                    ledger_digest=rec["digest"],
                )
            )
        return out
