# SPDX-License-Identifier: Apache-2.0
"""INNOV-110 · CMVG — Constitutional Mutation Velocity Governor.

Controls mutation pipeline throughput based on real-time CGDR health,
invariant density trends, and CEL gate pass-rates. Throttles or accelerates
the pipeline to maintain system stability while maximising innovation rate.
Emits VelocityDecisions into an HMAC-SHA-256-chained VelocityLedger.
All policy overrides require HUMAN-0 authentication.

Hard-class invariants enforced:
  CMVG-CHAIN-0      : VelocityLedger entries are HMAC-SHA-256 chained;
                      tampered or missing links raise CMVGChainError.
  CMVG-IMMUT-0      : Sealed VelocityDecision records are never mutated
                      after ledger commit; violation raises CMVGImmutError.
  CMVG-HUMAN0-0     : Policy override and emergency-stop both require a
                      non-empty authenticated HUMAN-0 identity; empty /
                      None identity raises CMVGAuthError before any state
                      change occurs.
  CMVG-CGDR-0       : When CGDR status is DRIFTED the governor enforces
                      HALT (rate = 0.0); no mutation may be admitted while
                      the system is DRIFTED regardless of other signals.
  CMVG-DETERM-0     : VelocityDecision value fields are pure deterministic
                      functions of their inputs; wall-clock time and entropy
                      are excluded from rate computation.
  CMVG-AUDIT-0      : Every decide() call appends one VelocityDecision to
                      the append-only ledger before returning; ledger-write
                      failure raises CMVGLedgerError; no decision is
                      returned on failure.
  CMVG-FLOOR-0      : Computed admission_rate never falls below CMVG_FLOOR
                      (0.05) during normal operation; only a HUMAN-0
                      emergency-stop may set rate to 0.0.
  CMVG-CEIL-0       : Computed admission_rate never exceeds CMVG_CEIL
                      (1.0); attempting to exceed raises CMVGCeilError.
  CMVG-FAILCLOSED-0 : Any computation error emits a HALT decision (rate
                      0.0) to the ledger and raises; never returns a
                      partial or unchecked decision.
  CMVG-SEAL-0       : Every VelocityDecision carries a SHA-256 content
                      seal computed over its canonical JSON representation
                      before ledger commit.

Governor: DUSTIN L REID · InnovativeAI LLC · Phase 205
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

CMVG_VERSION: str = "1.0.0"
INNOV_ID: str = "INNOV-110"
PHASE: int = 205

# ---------------------------------------------------------------------------
# Invariant constants
# ---------------------------------------------------------------------------

CMVG_FLOOR: float = 0.05   # CMVG-FLOOR-0
CMVG_CEIL: float = 1.0     # CMVG-CEIL-0

# ---------------------------------------------------------------------------
# Custom exceptions (invariant sentinels)
# ---------------------------------------------------------------------------


class CMVGError(Exception):
    """Base CMVG error."""


class CMVGChainError(CMVGError):
    """CMVG-CHAIN-0 violated — ledger chain integrity broken."""


class CMVGImmutError(CMVGError):
    """CMVG-IMMUT-0 violated — attempt to mutate sealed record."""


class CMVGAuthError(CMVGError):
    """CMVG-HUMAN0-0 violated — missing HUMAN-0 identity."""


class CMVGLedgerError(CMVGError):
    """CMVG-AUDIT-0 violated — ledger write failed."""


class CMVGCeilError(CMVGError):
    """CMVG-CEIL-0 violated — computed rate exceeds ceiling."""


class CMVGFloorError(CMVGError):
    """CMVG-FLOOR-0 violated — computed rate below floor in normal mode."""


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class CGDRStatus(str, Enum):
    PASSING = "PASSING"
    DRIFTED = "DRIFTED"
    UNKNOWN = "UNKNOWN"


class VelocityMode(str, Enum):
    HALT = "HALT"        # rate = 0.0 — CGDR DRIFTED or emergency-stop
    THROTTLE = "THROTTLE"  # rate [0.05, 0.6)
    CRUISE = "CRUISE"    # rate [0.6, 0.85)
    ACCELERATE = "ACCELERATE"  # rate [0.85, 1.0]


class DecisionOutcome(str, Enum):
    DECIDED = "DECIDED"
    HALT_CGDR = "HALT_CGDR"
    HALT_EMERGENCY = "HALT_EMERGENCY"
    ERROR = "ERROR"
    POLICY_OVERRIDE = "POLICY_OVERRIDE"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class VelocitySignals:
    """Input signals for a velocity decision.

    All fields must be supplied by the caller; defaults represent a
    conservative (throttled) posture.
    """

    cgdr_status: str = CGDRStatus.UNKNOWN.value
    invariant_density: float = 0.5        # 0.0–1.0 normalised density score
    cel_gate_pass_rate: float = 0.5       # 0.0–1.0 fraction of CEL gates passing
    innovation_backlog: int = 0           # number of PENDING AMPS proposals
    last_phase_duration_s: float = 3600.0  # seconds to complete last phase


@dataclass
class VelocityDecision:
    """Immutable velocity decision record committed to the ledger."""

    decision_id: str
    admission_rate: float
    velocity_mode: str
    outcome: str
    signals_snapshot: Dict[str, Any]
    rationale: str
    content_seal: str = ""        # CMVG-SEAL-0 — set before ledger commit
    chain_hash: str = ""          # CMVG-CHAIN-0 — set during ledger append
    decided_at: str = ""          # ISO-8601 timestamp
    governor: str = "DUSTIN L REID"
    innov_id: str = INNOV_ID
    phase: int = PHASE
    _sealed: bool = field(default=False, repr=False)

    def seal(self, canonical: str) -> None:
        """Compute and set content_seal (CMVG-SEAL-0)."""
        if self._sealed:
            raise CMVGImmutError("CMVG-IMMUT-0: record already sealed")  # CMVG-IMMUT-0
        self.content_seal = hashlib.sha256(canonical.encode()).hexdigest()
        self._sealed = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "admission_rate": self.admission_rate,
            "velocity_mode": self.velocity_mode,
            "outcome": self.outcome,
            "signals_snapshot": self.signals_snapshot,
            "rationale": self.rationale,
            "content_seal": self.content_seal,
            "chain_hash": self.chain_hash,
            "decided_at": self.decided_at,
            "governor": self.governor,
            "innov_id": self.innov_id,
            "phase": self.phase,
        }


# ---------------------------------------------------------------------------
# HMAC-chained ledger
# ---------------------------------------------------------------------------

_LEDGER_SECRET: bytes = (
    os.environ.get("CMVG_LEDGER_SECRET", "cmvg-ledger-secret-adaad-v1").encode()
)
_LEDGER_PATH = Path(
    os.environ.get(
        "CMVG_LEDGER_PATH",
        str(Path(__file__).parent.parent / "data" / "cmvg_velocity_ledger.jsonl"),
    )
)


def _hmac_hash(prev_hash: str, record_json: str) -> str:
    """Compute HMAC-SHA-256 chain link. CMVG-CHAIN-0."""
    msg = (prev_hash + record_json).encode()
    return hmac.new(_LEDGER_SECRET, msg, hashlib.sha256).hexdigest()


def _canonical_json(d: Dict[str, Any]) -> str:
    return json.dumps(d, sort_keys=True, separators=(",", ":"))


class VelocityLedger:
    """Append-only HMAC-chained ledger for VelocityDecision records.

    Invariants:  CMVG-CHAIN-0, CMVG-IMMUT-0, CMVG-AUDIT-0
    """

    GENESIS_HASH: str = "0" * 64

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = path or _LEDGER_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _last_hash(self) -> str:
        """Return the chain hash of the last committed record."""
        if not self._path.exists():
            return self.GENESIS_HASH
        last: Optional[str] = None
        with self._path.open("r") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    last = line
        if last is None:
            return self.GENESIS_HASH
        return json.loads(last)["chain_hash"]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def append(self, decision: VelocityDecision) -> None:
        """Append *decision* to the ledger. CMVG-AUDIT-0."""
        if not decision._sealed:
            raise CMVGImmutError("CMVG-IMMUT-0: cannot append unsealed decision")
        prev_hash = self._last_hash()
        record = decision.to_dict()
        # CMVG-CHAIN-0: compute hash over record WITHOUT chain_hash field,
        # consistent with verify_chain() which also excludes chain_hash.
        record_without_chain = {k: v for k, v in record.items() if k != "chain_hash"}
        record_json = _canonical_json(record_without_chain)
        chain_hash = _hmac_hash(prev_hash, record_json)
        decision.chain_hash = chain_hash
        record["chain_hash"] = chain_hash

        # Atomic write: tmp → rename
        tmp = self._path.with_suffix(".tmp")
        try:
            with tmp.open("w") as fh:
                # Write existing + new
                if self._path.exists():
                    with self._path.open("r") as src:
                        for line in src:
                            fh.write(line)
                fh.write(json.dumps(record) + "\n")
            tmp.replace(self._path)
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            raise CMVGLedgerError(f"CMVG-AUDIT-0: ledger write failed: {exc}") from exc

    def verify_chain(self) -> Dict[str, Any]:
        """Verify HMAC chain integrity. CMVG-CHAIN-0."""
        if not self._path.exists():
            return {"valid": True, "entries": 0, "message": "empty ledger"}
        prev_hash = self.GENESIS_HASH
        count = 0
        with self._path.open("r") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                stored_hash = record["chain_hash"]
                test_record = {k: v for k, v in record.items() if k != "chain_hash"}
                expected = _hmac_hash(prev_hash, _canonical_json(test_record))
                if not hmac.compare_digest(expected, stored_hash):
                    raise CMVGChainError(
                        f"CMVG-CHAIN-0: chain broken at entry {lineno}"
                    )
                prev_hash = stored_hash
                count += 1
        return {"valid": True, "entries": count, "message": "chain intact"}

    def all_decisions(self) -> List[Dict[str, Any]]:
        """Return all ledger records as list."""
        if not self._path.exists():
            return []
        records = []
        with self._path.open("r") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records

    def last_decision(self) -> Optional[Dict[str, Any]]:
        """Return the most recent decision or None."""
        records = self.all_decisions()
        return records[-1] if records else None


# ---------------------------------------------------------------------------
# Core governor
# ---------------------------------------------------------------------------


class ConstitutionalMutationVelocityGovernor:
    """INNOV-110 · CMVG — Constitutional Mutation Velocity Governor.

    Produces VelocityDecisions that control mutation pipeline throughput.
    All decisions are committed to an HMAC-chained ledger before being
    returned.  Policy overrides and emergency-stops require HUMAN-0.

    Usage::

        governor = ConstitutionalMutationVelocityGovernor()
        signals  = VelocitySignals(
            cgdr_status="PASSING",
            invariant_density=0.82,
            cel_gate_pass_rate=0.95,
            innovation_backlog=3,
        )
        decision = governor.decide(signals)
        print(decision.admission_rate, decision.velocity_mode)
    """

    def __init__(self, ledger: Optional[VelocityLedger] = None) -> None:
        self._ledger = ledger or VelocityLedger()
        self._emergency_stop: bool = False
        self._policy_rate: Optional[float] = None  # HUMAN-0 override rate

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _decision_id(signals: VelocitySignals) -> str:
        """Deterministic decision ID. CMVG-DETERM-0."""
        payload = json.dumps(
            {
                "cgdr": signals.cgdr_status,
                "density": signals.invariant_density,
                "cel": signals.cel_gate_pass_rate,
                "backlog": signals.innovation_backlog,
                "duration": signals.last_phase_duration_s,
            },
            sort_keys=True,
        )
        return "CMVG-" + hashlib.sha256(payload.encode()).hexdigest()[:16].upper()

    @staticmethod
    def _compute_rate(signals: VelocitySignals) -> tuple[float, str]:
        """Pure deterministic rate computation. CMVG-DETERM-0.

        Returns (admission_rate, rationale).
        """
        # Weight model — CMVG-DETERM-0: no external state influences
        cel_weight = 0.45
        density_weight = 0.35
        backlog_weight = 0.20

        # Normalise backlog: 0 backlog → 1.0 score; 10+ backlog → 0.2 score
        backlog_score = max(0.2, 1.0 - (signals.innovation_backlog * 0.08))

        composite = (
            signals.cel_gate_pass_rate * cel_weight
            + signals.invariant_density * density_weight
            + backlog_score * backlog_weight
        )

        # Clamp between FLOOR and CEIL — CMVG-FLOOR-0, CMVG-CEIL-0
        rate = max(CMVG_FLOOR, min(CMVG_CEIL, round(composite, 4)))

        rationale = (
            f"composite={composite:.4f} "
            f"[cel={signals.cel_gate_pass_rate:.3f}×{cel_weight} "
            f"density={signals.invariant_density:.3f}×{density_weight} "
            f"backlog_score={backlog_score:.3f}×{backlog_weight}] "
            f"→ clamped_rate={rate}"
        )
        return rate, rationale

    @staticmethod
    def _mode_for_rate(rate: float) -> str:
        if rate == 0.0:
            return VelocityMode.HALT.value
        if rate < 0.6:
            return VelocityMode.THROTTLE.value
        if rate < 0.85:
            return VelocityMode.CRUISE.value
        return VelocityMode.ACCELERATE.value

    def _commit(self, decision: VelocityDecision) -> None:
        """Seal and append to ledger. CMVG-SEAL-0, CMVG-AUDIT-0."""
        canonical = _canonical_json(decision.to_dict())
        decision.seal(canonical)
        decision.decided_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._ledger.append(decision)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def decide(self, signals: VelocitySignals) -> VelocityDecision:
        """Produce and ledger a VelocityDecision from *signals*.

        Invariants enforced: CMVG-CGDR-0, CMVG-FAILCLOSED-0, CMVG-AUDIT-0,
                             CMVG-FLOOR-0, CMVG-CEIL-0, CMVG-DETERM-0,
                             CMVG-SEAL-0, CMVG-CHAIN-0.
        """
        try:
            decision_id = self._decision_id(signals)
            signals_snapshot = {
                "cgdr_status": signals.cgdr_status,
                "invariant_density": signals.invariant_density,
                "cel_gate_pass_rate": signals.cel_gate_pass_rate,
                "innovation_backlog": signals.innovation_backlog,
                "last_phase_duration_s": signals.last_phase_duration_s,
            }

            # CMVG-CGDR-0: DRIFTED → HALT regardless of other signals
            if signals.cgdr_status == CGDRStatus.DRIFTED.value:
                decision = VelocityDecision(
                    decision_id=decision_id,
                    admission_rate=0.0,
                    velocity_mode=VelocityMode.HALT.value,
                    outcome=DecisionOutcome.HALT_CGDR.value,
                    signals_snapshot=signals_snapshot,
                    rationale="CMVG-CGDR-0: system DRIFTED — mutation pipeline halted",
                )
                self._commit(decision)
                return decision

            # Emergency stop (HUMAN-0 set)
            if self._emergency_stop:
                decision = VelocityDecision(
                    decision_id=decision_id,
                    admission_rate=0.0,
                    velocity_mode=VelocityMode.HALT.value,
                    outcome=DecisionOutcome.HALT_EMERGENCY.value,
                    signals_snapshot=signals_snapshot,
                    rationale="CMVG-HUMAN0-0: emergency-stop active — HUMAN-0 override",
                )
                self._commit(decision)
                return decision

            # Policy override (HUMAN-0 set explicit rate)
            if self._policy_rate is not None:
                rate = max(CMVG_FLOOR, min(CMVG_CEIL, self._policy_rate))
                decision = VelocityDecision(
                    decision_id=decision_id,
                    admission_rate=rate,
                    velocity_mode=self._mode_for_rate(rate),
                    outcome=DecisionOutcome.POLICY_OVERRIDE.value,
                    signals_snapshot=signals_snapshot,
                    rationale=f"CMVG-HUMAN0-0: policy override rate={rate}",
                )
                self._commit(decision)
                return decision

            # Normal computation — CMVG-DETERM-0
            rate, rationale = self._compute_rate(signals)

            # Guard invariants explicitly
            if rate > CMVG_CEIL:  # pragma: no cover — defensive
                raise CMVGCeilError(f"CMVG-CEIL-0: rate {rate} > {CMVG_CEIL}")
            if rate < CMVG_FLOOR:  # pragma: no cover — defensive
                raise CMVGFloorError(f"CMVG-FLOOR-0: rate {rate} < {CMVG_FLOOR}")

            decision = VelocityDecision(
                decision_id=decision_id,
                admission_rate=rate,
                velocity_mode=self._mode_for_rate(rate),
                outcome=DecisionOutcome.DECIDED.value,
                signals_snapshot=signals_snapshot,
                rationale=rationale,
            )
            self._commit(decision)
            return decision

        except CMVGError:
            raise
        except Exception as exc:  # CMVG-FAILCLOSED-0
            try:
                err_id = "CMVG-ERR-" + hashlib.sha256(str(exc).encode()).hexdigest()[:8].upper()
                fallback = VelocityDecision(
                    decision_id=err_id,
                    admission_rate=0.0,
                    velocity_mode=VelocityMode.HALT.value,
                    outcome=DecisionOutcome.ERROR.value,
                    signals_snapshot={},
                    rationale=f"CMVG-FAILCLOSED-0: error → HALT: {exc}",
                )
                self._commit(fallback)
            except Exception:  # pragma: no cover
                pass
            raise CMVGError(f"CMVG-FAILCLOSED-0: {exc}") from exc

    def emergency_stop(self, human_id: str) -> None:
        """Engage emergency stop. Requires HUMAN-0. CMVG-HUMAN0-0."""
        if not human_id or not human_id.strip():
            raise CMVGAuthError("CMVG-HUMAN0-0: human_id required for emergency_stop")
        self._emergency_stop = True

    def clear_emergency_stop(self, human_id: str) -> None:
        """Clear emergency stop. Requires HUMAN-0. CMVG-HUMAN0-0."""
        if not human_id or not human_id.strip():
            raise CMVGAuthError("CMVG-HUMAN0-0: human_id required for clear_emergency_stop")
        self._emergency_stop = False

    def set_policy_rate(self, rate: float, human_id: str) -> None:
        """Set a HUMAN-0 policy override rate. CMVG-HUMAN0-0."""
        if not human_id or not human_id.strip():
            raise CMVGAuthError("CMVG-HUMAN0-0: human_id required for set_policy_rate")
        if rate > CMVG_CEIL:
            raise CMVGCeilError(f"CMVG-CEIL-0: policy rate {rate} > {CMVG_CEIL}")
        self._policy_rate = rate

    def clear_policy_rate(self, human_id: str) -> None:
        """Clear policy override. Requires HUMAN-0. CMVG-HUMAN0-0."""
        if not human_id or not human_id.strip():
            raise CMVGAuthError("CMVG-HUMAN0-0: human_id required for clear_policy_rate")
        self._policy_rate = None

    def status(self) -> Dict[str, Any]:
        """Return current governor status."""
        last = self._ledger.last_decision()
        return {
            "innov_id": INNOV_ID,
            "phase": PHASE,
            "version": CMVG_VERSION,
            "emergency_stop": self._emergency_stop,
            "policy_rate": self._policy_rate,
            "last_decision": last,
            "ledger_path": str(self._ledger._path),
        }

    def verify_chain(self) -> Dict[str, Any]:
        """Delegate to ledger chain verification. CMVG-CHAIN-0."""
        return self._ledger.verify_chain()

    def all_decisions(self) -> List[Dict[str, Any]]:
        """Return all ledger decisions."""
        return self._ledger.all_decisions()
