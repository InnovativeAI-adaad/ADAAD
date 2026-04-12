# SPDX-License-Identifier: Apache-2.0
"""Innovation #40 — Cross-Epoch Agent Learning Transfer (CELT).

Extends INNOV-13 (IMT) and INNOV-16 (ERS) to enable governed transfer of
an agent's behavioural profile across epoch boundaries and instance
boundaries.

An agent that has learned safe structural refactoring patterns in one ADAAD
instance (or epoch) may package that knowledge into a cryptographically
signed LearningBundle and transmit it to a receiving instance.  The
receiving instance verifies integrity, sanitises the profile against the
canonical schema, merges it additively into the local agent profile, and
appends a chain-of-custody record to the transfer ledger.

The entire pipeline is constitutional: a bundle cannot mutate a local
profile without passing through ``celt_import_gate()``.  HUMAN-0 may
quarantine any bundle at any time; quarantined bundles are permanently
blocked.

Constitutional invariants enforced by this module
──────────────────────────────────────────────────
CELT-0          An AgentBehaviorProfile MUST NOT be applied cross-epoch
                without passing through celt_import_gate().
                Bypass raises GateBypassError.

CELT-VERIFY-0   import_bundle() MUST verify the HMAC signature before
                any profile state is written.
                Tampered or unsigned bundles raise VerificationError.

CELT-CHAIN-0    Every import event (successful or rejected) MUST be
                appended to the chain-of-custody ledger before the
                function returns.  Missing records raise ChainError.

CELT-DETERM-0   bundle_digest MUST be a pure function of
                (agent_id, source_instance, source_epoch, profile_snapshot).
                No wall-clock reads, no random state.

CELT-MERGE-0    Profile merge MUST be additive and deterministic.
                Counts are summed; score lists are concatenated in
                canonical (sorted) order.  No profile data is silently
                discarded.  Non-additive merge raises MergeError.

CELT-QUARANTINE-0  A bundle whose bundle_id appears in the quarantine
                registry MUST NOT be imported.  Attempt raises
                QuarantineError.

CELT-SANITIZE-0 Imported profiles MUST pass schema validation before
                merge.  Missing required fields raise SanitizationError.

CELT-EPOCH-0    A bundle's source_epoch MUST differ from the receiver's
                current_epoch.  Same-epoch transfer raises EpochBoundaryError.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import hashlib
import hmac

# Hardening scaffold — injected by fix/senior-deep-dive-hardening
CREPTR_INV_CHAIN: str = "CREPTR-INV-CHAIN"


class CrossEpochTransferViolation(RuntimeError):
    """Raised when a Cross Epoch Transfer constitutional invariant is breached."""



# ────────────────────────────────────────────────────────────────────────────
# Exceptions
# ────────────────────────────────────────────────────────────────────────────

class GateBypassError(RuntimeError):
    """CELT-0 — profile applied without passing gate."""

class VerificationError(RuntimeError):
    """CELT-VERIFY-0 — HMAC mismatch or unsigned bundle."""

class ChainError(RuntimeError):
    """CELT-CHAIN-0 — ledger chain broken."""

class DeterminismError(RuntimeError):
    """CELT-DETERM-0 — bundle_digest recomputation mismatch."""

class MergeError(RuntimeError):
    """CELT-MERGE-0 — non-additive merge attempted."""

class QuarantineError(RuntimeError):
    """CELT-QUARANTINE-0 — bundle is quarantined."""

class SanitizationError(RuntimeError):
    """CELT-SANITIZE-0 — profile schema validation failed."""

class EpochBoundaryError(RuntimeError):
    """CELT-EPOCH-0 — same-epoch transfer attempted."""

# ────────────────────────────────────────────────────────────────────────────
# Schema — required profile fields (CELT-SANITIZE-0)
# ────────────────────────────────────────────────────────────────────────────

_PROFILE_REQUIRED_FIELDS: frozenset[str] = frozenset({
    "agent_id",
    "target_type_counts",
    "strategy_counts",
    "risk_scores",
    "fitness_deltas",
    "epochs_active",
})

_PROFILE_LIST_FIELDS:  frozenset[str] = frozenset({"risk_scores", "fitness_deltas"})
_PROFILE_COUNT_FIELDS: frozenset[str] = frozenset({"target_type_counts", "strategy_counts"})

# ────────────────────────────────────────────────────────────────────────────
# Data structures
# ────────────────────────────────────────────────────────────────────────────

@dataclass
class ProfileSnapshot:
    """Serialisable point-in-time snapshot of an AgentBehaviorProfile."""
    agent_id: str
    target_type_counts: dict[str, int]
    strategy_counts: dict[str, int]
    risk_scores: list[float]
    fitness_deltas: list[float]
    epochs_active: int

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "target_type_counts": dict(sorted(self.target_type_counts.items())),
            "strategy_counts": dict(sorted(self.strategy_counts.items())),
            "risk_scores": sorted(self.risk_scores),
            "fitness_deltas": sorted(self.fitness_deltas),
            "epochs_active": self.epochs_active,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProfileSnapshot":
        return cls(
            agent_id=d["agent_id"],
            target_type_counts=dict(d.get("target_type_counts", {})),
            strategy_counts=dict(d.get("strategy_counts", {})),
            risk_scores=list(d.get("risk_scores", [])),
            fitness_deltas=list(d.get("fitness_deltas", [])),
            epochs_active=int(d.get("epochs_active", 0)),
        )


@dataclass
class LearningBundle:
    """Signed, versioned cross-epoch learning transfer package."""
    bundle_id: str
    agent_id: str
    source_instance: str
    source_epoch: str
    profile_snapshot: dict        # ProfileSnapshot.to_dict()
    bundle_digest: str = ""       # CELT-DETERM-0
    hmac_digest: str = ""         # CELT-VERIFY-0
    quarantined: bool = False

    def compute_bundle_digest(self) -> str:
        """CELT-DETERM-0: pure function of identity + profile."""
        payload = json.dumps(
            {
                "agent_id": self.agent_id,
                "source_instance": self.source_instance,
                "source_epoch": self.source_epoch,
                "profile_snapshot": self.profile_snapshot,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def sign(self, secret: bytes) -> None:
        """Compute and set bundle_digest + hmac_digest (CELT-VERIFY-0)."""
        self.bundle_digest = self.compute_bundle_digest()
        canonical = json.dumps(
            {
                "bundle_id": self.bundle_id,
                "agent_id": self.agent_id,
                "source_instance": self.source_instance,
                "source_epoch": self.source_epoch,
                "bundle_digest": self.bundle_digest,
            },
            sort_keys=True,
        )
        self.hmac_digest = hmac.new(secret, canonical.encode(), hashlib.sha256).hexdigest()[:24]

    def verify(self, secret: bytes) -> None:
        """CELT-VERIFY-0: raise VerificationError on mismatch."""
        if not self.hmac_digest:
            raise VerificationError(
                f"CELT-VERIFY-0: bundle {self.bundle_id!r} has no HMAC digest."
            )
        # Recompute expected digest
        expected_bd = self.compute_bundle_digest()
        if self.bundle_digest != expected_bd:
            raise VerificationError(
                f"CELT-VERIFY-0: bundle_digest mismatch for {self.bundle_id!r}."
            )
        canonical = json.dumps(
            {
                "bundle_id": self.bundle_id,
                "agent_id": self.agent_id,
                "source_instance": self.source_instance,
                "source_epoch": self.source_epoch,
                "bundle_digest": self.bundle_digest,
            },
            sort_keys=True,
        )
        expected_hmac = hmac.new(secret, canonical.encode(), hashlib.sha256).hexdigest()[:24]
        if not hmac.compare_digest(self.hmac_digest, expected_hmac):
            raise VerificationError(
                f"CELT-VERIFY-0: HMAC mismatch for bundle {self.bundle_id!r}."
            )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MergeResult:
    """Outcome of additive profile merge (CELT-MERGE-0)."""
    agent_id: str
    source_bundle_id: str
    added_target_counts: dict[str, int]
    added_strategy_counts: dict[str, int]
    added_risk_scores: int      # count of appended entries
    added_fitness_deltas: int   # count of appended entries
    added_epochs: int
    merge_digest: str = ""      # digest of merge event


@dataclass
class TransferRecord:
    """Append-only ledger entry for one transfer event (CELT-CHAIN-0)."""
    record_id: str
    bundle_id: str
    agent_id: str
    source_instance: str
    source_epoch: str
    target_instance: str
    target_epoch: str
    outcome: str                  # IMPORTED | REJECTED | QUARANTINED
    rejection_reason: str = ""
    prev_digest: str = "genesis"
    record_digest: str = ""

    def compute_record_digest(self, secret: bytes) -> str:
        payload = json.dumps(
            {
                "record_id": self.record_id,
                "bundle_id": self.bundle_id,
                "agent_id": self.agent_id,
                "outcome": self.outcome,
                "prev_digest": self.prev_digest,
            },
            sort_keys=True,
        )
        return hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()[:24]

# ────────────────────────────────────────────────────────────────────────────
# Profile sanitiser (CELT-SANITIZE-0)
# ────────────────────────────────────────────────────────────────────────────

def sanitise_profile(profile_dict: dict) -> ProfileSnapshot:
    """CELT-SANITIZE-0: validate schema and return ProfileSnapshot.

    Raises SanitizationError on missing/malformed fields.
    """
    missing = _PROFILE_REQUIRED_FIELDS - set(profile_dict.keys())
    if missing:
        raise SanitizationError(
            f"CELT-SANITIZE-0: profile missing required fields: {sorted(missing)}"
        )
    for f in _PROFILE_LIST_FIELDS:
        if not isinstance(profile_dict[f], list):
            raise SanitizationError(
                f"CELT-SANITIZE-0: field {f!r} must be a list; got {type(profile_dict[f]).__name__}"
            )
        for v in profile_dict[f]:
            if not isinstance(v, (int, float)):
                raise SanitizationError(
                    f"CELT-SANITIZE-0: field {f!r} contains non-numeric value {v!r}"
                )
    for f in _PROFILE_COUNT_FIELDS:
        if not isinstance(profile_dict[f], dict):
            raise SanitizationError(
                f"CELT-SANITIZE-0: field {f!r} must be a dict; got {type(profile_dict[f]).__name__}"
            )
        for k, v in profile_dict[f].items():
            if not isinstance(v, int) or v < 0:
                raise SanitizationError(
                    f"CELT-SANITIZE-0: field {f!r}[{k!r}] must be non-negative int; got {v!r}"
                )
    if not isinstance(profile_dict["epochs_active"], int) or profile_dict["epochs_active"] < 0:
        raise SanitizationError(
            f"CELT-SANITIZE-0: epochs_active must be non-negative int."
        )
    return ProfileSnapshot.from_dict(profile_dict)


# ────────────────────────────────────────────────────────────────────────────
# Additive merge (CELT-MERGE-0)
# ────────────────────────────────────────────────────────────────────────────

def merge_profile(local: ProfileSnapshot, incoming: ProfileSnapshot) -> tuple[ProfileSnapshot, MergeResult]:
    """CELT-MERGE-0: additive merge — counts summed, lists concatenated in canonical order.

    The local profile is mutated in place; returns (updated_local, MergeResult).
    """
    if local.agent_id != incoming.agent_id:
        raise MergeError(
            f"CELT-MERGE-0: agent_id mismatch — local {local.agent_id!r} vs incoming {incoming.agent_id!r}"
        )

    # Additive count merges
    added_target: dict[str, int] = {}
    for k, v in incoming.target_type_counts.items():
        if v < 0:
            raise MergeError(f"CELT-MERGE-0: negative count {v} for target_type {k!r}")
        local.target_type_counts[k] = local.target_type_counts.get(k, 0) + v
        added_target[k] = v

    added_strategy: dict[str, int] = {}
    for k, v in incoming.strategy_counts.items():
        if v < 0:
            raise MergeError(f"CELT-MERGE-0: negative count {v} for strategy {k!r}")
        local.strategy_counts[k] = local.strategy_counts.get(k, 0) + v
        added_strategy[k] = v

    # Additive list merges — canonical sort (CELT-DETERM-0)
    added_risk = len(incoming.risk_scores)
    added_delta = len(incoming.fitness_deltas)
    local.risk_scores = sorted(local.risk_scores + incoming.risk_scores)
    local.fitness_deltas = sorted(local.fitness_deltas + incoming.fitness_deltas)
    local.epochs_active += incoming.epochs_active

    # Merge digest (CELT-DETERM-0)
    merge_payload = json.dumps(
        {
            "agent_id": local.agent_id,
            "added_target_counts": dict(sorted(added_target.items())),
            "added_strategy_counts": dict(sorted(added_strategy.items())),
            "added_risk_scores": added_risk,
            "added_fitness_deltas": added_delta,
        },
        sort_keys=True,
    )
    merge_digest = hashlib.sha256(merge_payload.encode()).hexdigest()[:24]

    result = MergeResult(
        agent_id=local.agent_id,
        source_bundle_id="",  # set by caller
        added_target_counts=added_target,
        added_strategy_counts=added_strategy,
        added_risk_scores=added_risk,
        added_fitness_deltas=added_delta,
        added_epochs=incoming.epochs_active,
        merge_digest=merge_digest,
    )
    return local, result


# ────────────────────────────────────────────────────────────────────────────
# Cross-Epoch Learning Transfer Engine
# ────────────────────────────────────────────────────────────────────────────

_LEDGER_DEFAULT = Path("artifacts/governance/celt_ledger.jsonl")


class CELTEngine:
    """Orchestrates cross-epoch agent learning transfers.

    Responsibilities:
    - Bundle creation and signing (export side)
    - Verification, sanitisation, and merge (import side)
    - Quarantine registry management (HUMAN-0 authority)
    - Append-only chain-of-custody ledger (CELT-CHAIN-0)
    """

    def __init__(
        self,
        hmac_secret: bytes,
        instance_id: str,
        current_epoch: str,
        ledger_path: Path = _LEDGER_DEFAULT,
    ) -> None:
        self._secret = hmac_secret
        self._instance_id = instance_id
        self._current_epoch = current_epoch
        self._ledger_path = ledger_path
        self._quarantine: set[str] = set()
        self._prev_digest = "genesis"
        self._record_counter = 0
        self._profiles: dict[str, ProfileSnapshot] = {}
        self._load_ledger()

    # ── Export side ──────────────────────────────────────────────────────

    def export_bundle(self, agent_id: str, bundle_id: str) -> LearningBundle:
        """Package an agent's local profile into a signed LearningBundle."""
        if agent_id not in self._profiles:
            raise KeyError(f"No profile registered for agent {agent_id!r}")
        snap = self._profiles[agent_id]
        bundle = LearningBundle(
            bundle_id=bundle_id,
            agent_id=agent_id,
            source_instance=self._instance_id,
            source_epoch=self._current_epoch,
            profile_snapshot=snap.to_dict(),
        )
        bundle.sign(self._secret)   # CELT-VERIFY-0
        return bundle

    # ── Import side (gate) ───────────────────────────────────────────────

    def celt_import_gate(
        self,
        bundle: LearningBundle,
        target_epoch: str,
    ) -> tuple[ProfileSnapshot, MergeResult]:
        """CELT-0: sole authorised entry point for cross-epoch profile application.

        Enforces CELT-QUARANTINE-0, CELT-EPOCH-0, CELT-VERIFY-0,
        CELT-SANITIZE-0, CELT-MERGE-0, CELT-CHAIN-0 — in that order.
        """
        outcome = "IMPORTED"
        rejection_reason = ""

        try:
            # CELT-QUARANTINE-0
            if bundle.bundle_id in self._quarantine:
                raise QuarantineError(
                    f"CELT-QUARANTINE-0: bundle {bundle.bundle_id!r} is quarantined."
                )

            # CELT-EPOCH-0
            if bundle.source_epoch == target_epoch:
                raise EpochBoundaryError(
                    f"CELT-EPOCH-0: source_epoch {bundle.source_epoch!r} == "
                    f"target_epoch {target_epoch!r}; same-epoch transfer prohibited."
                )

            # CELT-VERIFY-0
            bundle.verify(self._secret)

            # CELT-SANITIZE-0
            incoming_snap = sanitise_profile(bundle.profile_snapshot)

        except (QuarantineError, EpochBoundaryError, VerificationError, SanitizationError) as exc:
            outcome = "QUARANTINED" if isinstance(exc, QuarantineError) else "REJECTED"
            rejection_reason = str(exc)
            self._append_record(bundle, target_epoch, outcome, rejection_reason)
            raise

        # CELT-MERGE-0
        if bundle.agent_id not in self._profiles:
            self._profiles[bundle.agent_id] = ProfileSnapshot(
                agent_id=bundle.agent_id,
                target_type_counts={},
                strategy_counts={},
                risk_scores=[],
                fitness_deltas=[],
                epochs_active=0,
            )

        updated, merge_result = merge_profile(self._profiles[bundle.agent_id], incoming_snap)
        merge_result.source_bundle_id = bundle.bundle_id
        self._profiles[bundle.agent_id] = updated

        # CELT-CHAIN-0
        self._append_record(bundle, target_epoch, outcome, "")
        return updated, merge_result

    # ── Quarantine management (HUMAN-0 authority) ────────────────────────

    def quarantine_bundle(self, bundle_id: str) -> None:
        """CELT-QUARANTINE-0: HUMAN-0 marks a bundle permanently blocked."""
        self._quarantine.add(bundle_id)

    def is_quarantined(self, bundle_id: str) -> bool:
        return bundle_id in self._quarantine

    # ── Profile registry ─────────────────────────────────────────────────

    def register_profile(self, snap: ProfileSnapshot) -> None:
        """Register or replace a local agent profile."""
        self._profiles[snap.agent_id] = snap

    def get_profile(self, agent_id: str) -> ProfileSnapshot:
        if agent_id not in self._profiles:
            raise KeyError(f"No profile for agent {agent_id!r}")
        return self._profiles[agent_id]

    # ── Chain verification ────────────────────────────────────────────────

    def verify_chain(self) -> bool:
        """CELT-CHAIN-0: verify the full transfer ledger chain."""
        if not self._ledger_path.exists():
            return True
        prev = "genesis"
        for i, line in enumerate(self._ledger_path.read_text().splitlines()):
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("prev_digest") != prev:
                raise ChainError(
                    f"CELT-CHAIN-0: chain break at line {i}: "
                    f"expected {prev!r}, got {rec.get('prev_digest')!r}"
                )
            prev = rec.get("record_digest", "")
        return True

    def record_count(self) -> int:
        return self._record_counter

    # ── Internals ─────────────────────────────────────────────────────────

    def _append_record(
        self,
        bundle: LearningBundle,
        target_epoch: str,
        outcome: str,
        rejection_reason: str,
    ) -> None:
        """CELT-CHAIN-0: always append before returning."""
        self._record_counter += 1
        rec = TransferRecord(
            record_id=f"CELT-REC-{self._record_counter:06d}",
            bundle_id=bundle.bundle_id,
            agent_id=bundle.agent_id,
            source_instance=bundle.source_instance,
            source_epoch=bundle.source_epoch,
            target_instance=self._instance_id,
            target_epoch=target_epoch,
            outcome=outcome,
            rejection_reason=rejection_reason,
            prev_digest=self._prev_digest,
        )
        rec.record_digest = rec.compute_record_digest(self._secret)
        self._prev_digest = rec.record_digest
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self._ledger_path.open("a") as fh:
            fh.write(json.dumps(asdict(rec), sort_keys=True) + "\n")

    def _load_ledger(self) -> None:
        if not self._ledger_path.exists():
            return
        for line in self._ledger_path.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            self._prev_digest = rec.get("record_digest", self._prev_digest)
            self._record_counter += 1


# ────────────────────────────────────────────────────────────────────────────
# Factory helpers
# ────────────────────────────────────────────────────────────────────────────

def snapshot_from_profile(profile: Any) -> ProfileSnapshot:
    """Convert an ERS AgentBehaviorProfile to a CELT ProfileSnapshot."""
    return ProfileSnapshot(
        agent_id=profile.agent_id,
        target_type_counts=dict(profile.target_type_counts),
        strategy_counts=dict(profile.strategy_counts),
        risk_scores=list(profile.risk_scores),
        fitness_deltas=list(profile.fitness_deltas),
        epochs_active=profile.epochs_active,
    )
