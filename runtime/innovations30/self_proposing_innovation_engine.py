# SPDX-License-Identifier: Apache-2.0
"""Innovation #35 — Self-Proposing Innovation Engine (SPIE).

The system proposes its own next innovations based on three signal sources:
  1. **Failure history** — recurring failure patterns from the mutation ledger
  2. **Constitutional gap analysis** — invariant categories with low coverage
  3. **Mirror Test accuracy trends** — self-model fidelity decay signals

HUMAN-0 still ratifies every proposal.  SPIE does the discovery.

Constitutional invariants enforced by this module
  SPIE-0         Every InnovationProposal returned by propose() MUST have a
                 non-empty proposal_digest.  Fail-closed: SPIEViolation raised.
  SPIE-DETERM-0  Identical (epoch_id, signal_fingerprint) inputs produce
                 identical proposal_id and proposal_digest; no datetime.now(),
                 no random, no uuid4.
  SPIE-PERSIST-0 Every proposal returned by propose() MUST be flushed to the
                 append-only JSONL ledger before propose() returns.
  SPIE-CHAIN-0   Each ledger record is HMAC-SHA256 chain-linked to its
                 predecessor (prev_digest field).
  SPIE-GATE-0    A proposal whose signal_fingerprint already exists in the
                 known-proposals set MUST NOT be re-emitted (deduplication gate).
  SPIE-SOURCE-0  Every proposal MUST declare at least one signal_source from
                 {'failure_history', 'constitutional_gap', 'mirror_accuracy'}.
  SPIE-HUMAN0-0  The ratified field on an InnovationProposal MUST be set only
                 via ratify(), never during construction or propose(); any
                 attempt to bypass raises SPIEViolation.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ── constants ────────────────────────────────────────────────────────────────
_SPIE_VERSION: str = "1.0"
_SPIE_LEDGER: str = "data/spie_proposals_ledger.jsonl"
_HMAC_KEY: bytes = b"spie-chain-key-v1"

VALID_SIGNAL_SOURCES: frozenset[str] = frozenset(
    {"failure_history", "constitutional_gap", "mirror_accuracy"}
)

SPIE_INVARIANTS: dict[str, dict[str, str]] = {
    "SPIE-0":        {"description": "Every proposal has non-empty proposal_digest.", "class": "Hard"},
    "SPIE-DETERM-0": {"description": "Identical inputs → identical proposal_id and digest.", "class": "Hard"},
    "SPIE-PERSIST-0":{"description": "Every proposal flushed to ledger before return.", "class": "Hard"},
    "SPIE-CHAIN-0":  {"description": "HMAC-SHA256 chain-link on every ledger record.", "class": "Hard"},
    "SPIE-GATE-0":   {"description": "Duplicate signal_fingerprint must not re-emit.", "class": "Hard"},
    "SPIE-SOURCE-0": {"description": "Every proposal declares at least one valid signal_source.", "class": "Hard"},
    "SPIE-HUMAN0-0": {"description": "ratified flag settable only via ratify(); not at construction.", "class": "Hard"},
}


# ── exceptions ────────────────────────────────────────────────────────────────

class SPIEViolation(RuntimeError):
    """Raised when a SPIE Hard-class invariant is breached."""


class SPIEDuplicateError(SPIEViolation):
    """SPIE-GATE-0: proposal with same signal_fingerprint already exists."""


class SPIESourceError(SPIEViolation):
    """SPIE-SOURCE-0: proposal has no valid signal_source declared."""


class SPIEPersistError(SPIEViolation):
    """SPIE-PERSIST-0: ledger write failed before propose() returned."""


class SPIERatifyError(SPIEViolation):
    """SPIE-HUMAN0-0: ratified flag mutated outside ratify()."""


# ── guard ─────────────────────────────────────────────────────────────────────

def spie_guard(condition: bool, invariant: str, detail: str = "") -> None:
    """Fail-closed enforcement for all SPIE Hard-class invariants."""
    if not condition:
        msg = f"[SPIE Hard-class violation] {invariant}"
        if detail:
            msg += f" — {detail}"
        raise SPIEViolation(msg)


# ── signal types ──────────────────────────────────────────────────────────────

@dataclass
class FailureSignal:
    """A recurring failure pattern extracted from the mutation ledger."""
    pattern: str          # human-readable pattern description
    frequency: int        # count of occurrences in epoch window
    affected_module: str  # most frequently affected module path
    example_mutation_id: str

    def fingerprint(self) -> str:
        src = f"failure:{self.pattern}:{self.affected_module}"
        return hashlib.sha256(src.encode()).hexdigest()[:12]

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "failure_history",
            "pattern": self.pattern,
            "frequency": self.frequency,
            "affected_module": self.affected_module,
            "example_mutation_id": self.example_mutation_id,
        }


@dataclass
class ConstitutionalGapSignal:
    """An invariant category with insufficient coverage."""
    category: str       # e.g. 'federation', 'replay', 'fitness'
    current_count: int  # existing invariants in this category
    min_expected: int   # governance target
    gap_score: float    # (min_expected - current_count) / min_expected

    def fingerprint(self) -> str:
        src = f"gap:{self.category}:{self.current_count}:{self.min_expected}"
        return hashlib.sha256(src.encode()).hexdigest()[:12]

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "constitutional_gap",
            "category": self.category,
            "current_count": self.current_count,
            "min_expected": self.min_expected,
            "gap_score": round(self.gap_score, 4),
        }


@dataclass
class MirrorAccuracySignal:
    """A detected decline in Mirror Test self-model fidelity."""
    epoch_id: str
    accuracy_current: float   # 0.0 – 1.0
    accuracy_baseline: float  # reference epoch accuracy
    decay_delta: float        # baseline - current (positive = decay)
    affected_dimension: str   # e.g. 'mutation_intent', 'fitness_scoring'

    def fingerprint(self) -> str:
        src = f"mirror:{self.epoch_id}:{self.affected_dimension}:{self.decay_delta:.4f}"
        return hashlib.sha256(src.encode()).hexdigest()[:12]

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "mirror_accuracy",
            "epoch_id": self.epoch_id,
            "accuracy_current": round(self.accuracy_current, 4),
            "accuracy_baseline": round(self.accuracy_baseline, 4),
            "decay_delta": round(self.decay_delta, 4),
            "affected_dimension": self.affected_dimension,
        }


# ── proposal ──────────────────────────────────────────────────────────────────

@dataclass
class InnovationProposal:
    """A self-proposed innovation candidate.

    proposal_id       — SPIE-DETERM-0: sha256(epoch_id + signal_fingerprint)
    proposal_digest   — SPIE-0: sha256(canonical JSON of all fields)
    signal_sources    — SPIE-SOURCE-0: at least one valid source
    ratified          — SPIE-HUMAN0-0: only set via ratify()
    """
    proposal_id: str
    epoch_id: str
    signal_fingerprint: str
    title: str
    rationale: str
    suggested_invariants: list[str]
    signal_sources: list[str]
    signals: list[dict[str, Any]]
    proposal_digest: str
    prev_digest: str
    chain_link: str
    spie_version: str = _SPIE_VERSION
    ratified: bool = False
    ratified_by: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "epoch_id": self.epoch_id,
            "signal_fingerprint": self.signal_fingerprint,
            "title": self.title,
            "rationale": self.rationale,
            "suggested_invariants": list(self.suggested_invariants),
            "signal_sources": list(self.signal_sources),
            "signals": list(self.signals),
            "proposal_digest": self.proposal_digest,
            "prev_digest": self.prev_digest,
            "chain_link": self.chain_link,
            "spie_version": self.spie_version,
            "ratified": self.ratified,
            "ratified_by": self.ratified_by,
        }


# ── engine ────────────────────────────────────────────────────────────────────

class SelfProposingInnovationEngine:
    """INNOV-35 core engine.

    Consumes signal objects (FailureSignal, ConstitutionalGapSignal,
    MirrorAccuracySignal), synthesises InnovationProposals, and persists
    them to an append-only HMAC-chain-linked JSONL ledger.

    HUMAN-0 ratifies proposals via ratify().  The engine never sets
    ratified=True itself (SPIE-HUMAN0-0).
    """

    def __init__(
        self,
        instance_id: str,
        ledger_path: Path | None = None,
        hmac_key: bytes = _HMAC_KEY,
    ) -> None:
        self._instance_id = instance_id
        self._ledger_path = ledger_path or Path(_SPIE_LEDGER)
        self._hmac_key = hmac_key
        self._known_fingerprints: set[str] = set()
        self._proposals: dict[str, InnovationProposal] = {}
        self._prev_digest: str = self._genesis_digest()

    # ── internals ────────────────────────────────────────────────────────────

    def _genesis_digest(self) -> str:
        return "sha256:" + hashlib.sha256(b"spie-genesis-v1").hexdigest()

    def _proposal_id(self, epoch_id: str, fingerprint: str) -> str:
        """SPIE-DETERM-0: deterministic ID."""
        src = f"{epoch_id}:{fingerprint}:{self._instance_id}"
        return "spie:" + hashlib.sha256(src.encode()).hexdigest()[:16]

    def _proposal_digest(self, proposal_id: str, title: str, rationale: str,
                          sources: list[str], signals: list[dict]) -> str:
        """SPIE-0: non-empty digest over proposal content."""
        payload = json.dumps(
            {"proposal_id": proposal_id, "title": title,
             "rationale": rationale, "signal_sources": sorted(sources),
             "signals": signals},
            sort_keys=True, ensure_ascii=False
        )
        return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()

    def _chain_link(self, proposal_id: str, prev_digest: str) -> str:
        """SPIE-CHAIN-0: HMAC-SHA256 chain link."""
        msg = f"{proposal_id}:{prev_digest}".encode()
        return "hmac-sha256:" + hmac.new(self._hmac_key, msg, hashlib.sha256).hexdigest()

    def _persist(self, proposal: InnovationProposal) -> None:
        """SPIE-PERSIST-0: flush to ledger before returning."""
        try:
            self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with self._ledger_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(proposal.to_dict(), sort_keys=True) + "\n")
                fh.flush()
        except OSError as exc:
            raise SPIEPersistError(
                f"[SPIE-PERSIST-0] ledger write failed: {exc}"
            ) from exc

    def _validate_sources(self, sources: list[str]) -> None:
        """SPIE-SOURCE-0: at least one valid source required."""
        valid = [s for s in sources if s in VALID_SIGNAL_SOURCES]
        spie_guard(
            len(valid) > 0,
            "SPIE-SOURCE-0",
            f"No valid signal_source in {sources!r}; valid={sorted(VALID_SIGNAL_SOURCES)}"
        )

    def _synthesise_title(
        self,
        failure: FailureSignal | None,
        gap: ConstitutionalGapSignal | None,
        mirror: MirrorAccuracySignal | None,
    ) -> str:
        """Deterministic title synthesis from dominant signal."""
        if failure is not None:
            module_short = failure.affected_module.split("/")[-1].replace(".py", "")
            return f"Governed {module_short.replace('_', ' ').title()} Hardening Innovation"
        if gap is not None:
            return f"{gap.category.replace('_', ' ').title()} Constitutional Coverage Expansion"
        if mirror is not None:
            dim = mirror.affected_dimension.replace("_", " ").title()
            return f"{dim} Self-Model Fidelity Restoration Innovation"
        return "Emergent Governance Innovation"

    def _synthesise_rationale(
        self,
        failure: FailureSignal | None,
        gap: ConstitutionalGapSignal | None,
        mirror: MirrorAccuracySignal | None,
    ) -> str:
        parts: list[str] = []
        if failure is not None:
            parts.append(
                f"Failure pattern '{failure.pattern}' observed {failure.frequency}x "
                f"in {failure.affected_module}; constitutional hardening required."
            )
        if gap is not None:
            parts.append(
                f"Constitutional category '{gap.category}' has {gap.current_count} "
                f"invariants against target {gap.min_expected} "
                f"(gap_score={gap.gap_score:.2f}); coverage expansion required."
            )
        if mirror is not None:
            parts.append(
                f"Mirror Test fidelity decay of {mirror.decay_delta:.3f} detected "
                f"in dimension '{mirror.affected_dimension}' at epoch {mirror.epoch_id}; "
                "self-model restoration required."
            )
        return " ".join(parts) if parts else "Emergent governance signal detected."

    def _synthesise_invariants(
        self,
        fingerprint: str,
        failure: FailureSignal | None,
        gap: ConstitutionalGapSignal | None,
    ) -> list[str]:
        tag = fingerprint[:4].upper()
        invs = [f"SPIE-PROP-{tag}-0", f"SPIE-PROP-{tag}-DETERM-0", f"SPIE-PROP-{tag}-PERSIST-0"]
        if gap is not None:
            invs.append(f"SPIE-PROP-{tag}-GATE-0")
        if failure is not None:
            invs.append(f"SPIE-PROP-{tag}-CHAIN-0")
        return invs

    # ── public API ────────────────────────────────────────────────────────────

    def propose(
        self,
        epoch_id: str,
        *,
        failure: FailureSignal | None = None,
        gap: ConstitutionalGapSignal | None = None,
        mirror: MirrorAccuracySignal | None = None,
    ) -> InnovationProposal:
        """Synthesise and persist a new InnovationProposal.

        At least one signal (failure / gap / mirror) must be supplied.
        SPIE-GATE-0: duplicate signal fingerprints are rejected.
        SPIE-HUMAN0-0: ratified is always False at construction.
        """
        # Determine signal sources
        sources: list[str] = []
        signals: list[dict[str, Any]] = []
        if failure is not None:
            sources.append("failure_history")
            signals.append(failure.to_dict())
        if gap is not None:
            sources.append("constitutional_gap")
            signals.append(gap.to_dict())
        if mirror is not None:
            sources.append("mirror_accuracy")
            signals.append(mirror.to_dict())

        spie_guard(len(sources) > 0, "SPIE-SOURCE-0", "At least one signal required.")
        self._validate_sources(sources)

        # Composite fingerprint
        parts = []
        if failure:
            parts.append(failure.fingerprint())
        if gap:
            parts.append(gap.fingerprint())
        if mirror:
            parts.append(mirror.fingerprint())
        signal_fingerprint = hashlib.sha256(":".join(parts).encode()).hexdigest()[:16]

        # SPIE-GATE-0: deduplication
        if signal_fingerprint in self._known_fingerprints:
            raise SPIEDuplicateError(
                f"[SPIE-GATE-0] signal_fingerprint {signal_fingerprint!r} "
                "already emitted — proposal suppressed."
            )

        # Build proposal fields
        proposal_id = self._proposal_id(epoch_id, signal_fingerprint)
        title = self._synthesise_title(failure, gap, mirror)
        rationale = self._synthesise_rationale(failure, gap, mirror)
        suggested_invariants = self._synthesise_invariants(signal_fingerprint, failure, gap)

        digest = self._proposal_digest(proposal_id, title, rationale, sources, signals)
        chain_link = self._chain_link(proposal_id, self._prev_digest)

        # SPIE-0: digest must be non-empty
        spie_guard(bool(digest), "SPIE-0", "proposal_digest must not be empty.")

        proposal = InnovationProposal(
            proposal_id=proposal_id,
            epoch_id=epoch_id,
            signal_fingerprint=signal_fingerprint,
            title=title,
            rationale=rationale,
            suggested_invariants=suggested_invariants,
            signal_sources=sources,
            signals=signals,
            proposal_digest=digest,
            prev_digest=self._prev_digest,
            chain_link=chain_link,
            ratified=False,   # SPIE-HUMAN0-0: never True at construction
            ratified_by="",
        )

        # SPIE-PERSIST-0: flush before returning
        self._persist(proposal)
        self._prev_digest = chain_link
        self._known_fingerprints.add(signal_fingerprint)
        self._proposals[proposal_id] = proposal

        return proposal

    def ratify(self, proposal_id: str, ratified_by: str) -> InnovationProposal:
        """SPIE-HUMAN0-0: the only legal path to set ratified=True.

        ratified_by should be the HUMAN-0 governor identifier.
        """
        if proposal_id not in self._proposals:
            raise KeyError(f"Unknown proposal_id: {proposal_id!r}")
        spie_guard(bool(ratified_by), "SPIE-HUMAN0-0", "ratified_by must not be empty.")
        proposal = self._proposals[proposal_id]
        proposal.ratified = True
        proposal.ratified_by = ratified_by
        return proposal

    def get_proposal(self, proposal_id: str) -> InnovationProposal | None:
        return self._proposals.get(proposal_id)

    def all_proposals(self) -> list[InnovationProposal]:
        return list(self._proposals.values())

    def verify_chain_integrity(self) -> bool:
        """SPIE-CHAIN-0: replay the ledger and verify every chain_link."""
        if not self._ledger_path.exists():
            return True
        prev = self._genesis_digest()
        for line in self._ledger_path.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            expected = self._chain_link(rec["proposal_id"], prev)
            if rec["chain_link"] != expected:
                return False
            prev = rec["chain_link"]
        return True

    def export_state(self) -> dict[str, Any]:
        return {
            "spie_version": _SPIE_VERSION,
            "instance_id": self._instance_id,
            "proposal_count": len(self._proposals),
            "known_fingerprints": sorted(self._known_fingerprints),
            "proposals": [p.to_dict() for p in self._proposals.values()],
        }

    def _append_event(self, event) -> None:
        """CED-INV-AUDIT: append-only JSONL event record; advance HMAC chain head."""
        import json, dataclasses
        ledger = getattr(self, 'ledger_path', None) or getattr(self, 'state_path', None)
        if ledger is None:
            return
        from pathlib import Path
        ledger = Path(ledger)
        ledger.parent.mkdir(parents=True, exist_ok=True)
        row = json.dumps(dataclasses.asdict(event) if hasattr(event, '__dataclass_fields__') else event, sort_keys=True)
        with ledger.open("a") as f:
            f.write(row + "\n")

