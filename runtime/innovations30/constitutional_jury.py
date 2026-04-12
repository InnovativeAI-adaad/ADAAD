# SPDX-License-Identifier: Apache-2.0
"""Innovation #14 — Constitutional Jury System (CJS).

2-of-3 independent agent evaluations for high-stakes mutations.
Dissenting verdicts feed InvariantDiscoveryEngine.

Constitutional invariants enforced by this module
──────────────────────────────────────────────────
  CJS-0         ConstitutionalJury.deliberate() is the sole authority for high-stakes
                mutation evaluation. Any mutation touching HIGH_STAKES_PATHS MUST be
                routed through deliberate() before promotion.
  CJS-QUORUM-0  Majority verdict requires >= MAJORITY_REQUIRED (2-of-3) approve votes.
                Ties and failures default to "reject". jury_size < JURY_SIZE is a
                configuration error and raises ConstitutionalJuryConfigError.
  CJS-DETERM-0  JuryDecision.decision_digest is sha256(mutation_id:majority_verdict:
                approve_count:jury_size) — deterministic; no datetime.now(), random,
                or uuid4. Seeds are constructed from mutation_id only.
  CJS-DISSENT-0 All dissenting verdicts MUST be appended to the dissent ledger before
                deliberate() returns. InvariantDiscoveryEngine relies on this feed for
                constitutional rule derivation.
  CJS-PERSIST-0 _persist() and _record_dissent() MUST use Path.open in append mode.
                Never builtins.open. Ledgers are append-only; no overwrites permitted.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import hashlib
import hmac

# Hardening scaffold — injected by fix/senior-deep-dive-hardening
COJU_INV_CHAIN: str = "COJU-INV-CHAIN"
COJU_LEDGER_DEFAULT: str = "data/constitutional_jury_events.jsonl"


class ConstitutionalJuryViolation(RuntimeError):
    """Raised when a Constitutional Jury constitutional invariant is breached."""



# ── Invariant constants ───────────────────────────────────────────────────────
JURY_SIZE: int = 3
MAJORITY_REQUIRED: int = 2
HIGH_STAKES_PATHS: frozenset[str] = frozenset(["runtime/", "security/", "app/main.py"])

_CJS_LEDGER_DEFAULT: str = "data/jury_decisions.jsonl"
_CJS_DISSENT_SUFFIX: str = ".dissent.jsonl"


# ── Exception types ───────────────────────────────────────────────────────────

class ConstitutionalJuryConfigError(Exception):
    """Raised when jury_size < JURY_SIZE (CJS-QUORUM-0 misconfiguration)."""


class JuryQuorumError(Exception):
    """Raised when evaluate_fn returns fewer verdicts than jury_size."""


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class JurorVerdict:
    """Single juror evaluation result.

    CJS-DETERM-0: random_seed MUST be derived deterministically from mutation_id
    and juror index — never from datetime or uuid4.
    """
    juror_id: str
    mutation_id: str
    verdict: str          # "approve" | "reject"
    confidence: float
    reasoning: str
    rules_fired: list[str]
    random_seed: str


@dataclass
class JuryDecision:
    """Aggregated multi-juror outcome.

    CJS-DETERM-0: decision_digest = sha256(mutation_id:majority_verdict:
                  approve_count:jury_size) — deterministic, no entropy.
    CJS-QUORUM-0: majority_verdict is "approve" iff approve_count >= MAJORITY_REQUIRED.
    """
    mutation_id: str
    unanimous: bool
    majority_verdict: str      # "approve" | "reject"
    approve_count: int
    reject_count: int
    jury_size: int
    individual_verdicts: list[JurorVerdict]
    dissent_recorded: bool
    decision_digest: str = field(default="")

    def __post_init__(self) -> None:
        """CJS-DETERM-0: compute digest deterministically if not already set."""
        if not self.decision_digest:
            self.decision_digest = _compute_decision_digest(
                self.mutation_id, self.majority_verdict,
                self.approve_count, self.jury_size,
            )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _compute_decision_digest(
    mutation_id: str, majority_verdict: str, approve_count: int, jury_size: int
) -> str:
    """CJS-DETERM-0: deterministic sha256 digest over four fixed fields."""
    payload = f"{mutation_id}:{majority_verdict}:{approve_count}:{jury_size}"
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def _make_seed(mutation_id: str, juror_index: int) -> str:
    """CJS-DETERM-0: derive juror seed from mutation_id and index — no entropy."""
    return f"seed-{mutation_id[:8]}-juror-{juror_index}"


def is_high_stakes(changed_files: list[str]) -> bool:
    """CJS-0: return True if any file touches HIGH_STAKES_PATHS."""
    return any(
        any(p in str(f) for p in HIGH_STAKES_PATHS)
        for f in changed_files
    )


# ── Main jury engine ──────────────────────────────────────────────────────────

class ConstitutionalJury:
    """Convenes 2-of-3 deliberation for high-stakes mutations.

    CJS-0         deliberate() is the sole evaluation authority for HIGH_STAKES_PATHS.
    CJS-QUORUM-0  jury_size < JURY_SIZE raises ConstitutionalJuryConfigError at init.
    CJS-DETERM-0  Seeds and decision_digest are deterministic from mutation_id only.
    CJS-DISSENT-0 Dissent ledger written before deliberate() returns.
    CJS-PERSIST-0 All ledger writes use Path.open("a") — never builtins.open.
    """

    def __init__(
        self,
        ledger_path: Path = Path(_CJS_LEDGER_DEFAULT),
        jury_size: int = JURY_SIZE,
    ):
        # CJS-QUORUM-0: fail at construction if quorum is unreachable
        if jury_size < JURY_SIZE:
            raise ConstitutionalJuryConfigError(
                f"CJS-QUORUM-0: jury_size={jury_size} is below minimum JURY_SIZE={JURY_SIZE}"
            )
        self.ledger_path = Path(ledger_path)
        self.jury_size = jury_size

    # ── Deliberation ──────────────────────────────────────────────────────────

    def deliberate(
        self,
        mutation_id: str,
        changed_files: list[str],
        evaluate_fn: Callable[[str, str], JurorVerdict],
    ) -> JuryDecision:
        """CJS-0: convene jury for a mutation. evaluate_fn(mutation_id, seed) → JurorVerdict.

        CJS-DETERM-0: seeds derived from mutation_id + index only.
        CJS-QUORUM-0: majority requires >= MAJORITY_REQUIRED approve votes.
        CJS-DISSENT-0: dissent ledger written before return.
        CJS-PERSIST-0: all writes use Path.open.
        """
        # CJS-DETERM-0: deterministic seeds
        seeds = [_make_seed(mutation_id, i) for i in range(self.jury_size)]
        verdicts = [evaluate_fn(mutation_id, seed) for seed in seeds]

        # CJS-QUORUM-0: count and decide
        approve_count = sum(1 for v in verdicts if v.verdict == "approve")
        reject_count = self.jury_size - approve_count
        majority = "approve" if approve_count >= MAJORITY_REQUIRED else "reject"
        unanimous = (approve_count == self.jury_size or reject_count == self.jury_size)
        dissent_recorded = not unanimous

        # CJS-DISSENT-0: write dissent BEFORE constructing and persisting decision
        if dissent_recorded:
            self._record_dissent(mutation_id, verdicts, majority)

        decision = JuryDecision(
            mutation_id=mutation_id,
            unanimous=unanimous,
            majority_verdict=majority,
            approve_count=approve_count,
            reject_count=reject_count,
            jury_size=self.jury_size,
            individual_verdicts=verdicts,
            dissent_recorded=dissent_recorded,
        )

        # CJS-PERSIST-0: persist decision ledger entry
        self._persist(decision)
        return decision

    # ── Dissent feed (CJS-DISSENT-0) ─────────────────────────────────────────

    def dissent_records(self, limit: int = 20) -> list[dict[str, Any]]:
        """CJS-DISSENT-0 / CJS-LOAD-0: return recent dissent records.

        Fail-open: corrupt lines silently skipped; missing file returns [].
        """
        dissent_path = self.ledger_path.with_suffix(_CJS_DISSENT_SUFFIX)
        if not dissent_path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in dissent_path.read_text().splitlines():
            try:
                records.append(json.loads(line))
            except Exception:
                pass
        return records[-limit:]

    def verdict_ledger(self, limit: int = 50) -> list[dict[str, Any]]:
        """CJS-LOAD-0: return recent decision ledger records. Fail-open."""
        if not self.ledger_path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in self.ledger_path.read_text().splitlines():
            try:
                records.append(json.loads(line))
            except Exception:
                pass
        return records[-limit:]

    # ── Internal ledger writers ───────────────────────────────────────────────

    def _record_dissent(
        self,
        mutation_id: str,
        verdicts: list[JurorVerdict],
        majority: str,
    ) -> None:
        """CJS-DISSENT-0 / CJS-PERSIST-0: append dissenters to dissent ledger.

        Path.open("a") — never builtins.open.
        CJS-DETERM-0: no datetime.now() in the record.
        """
        dissenters = [v for v in verdicts if v.verdict != majority]
        dissent_path = self.ledger_path.with_suffix(_CJS_DISSENT_SUFFIX)
        dissent_path.parent.mkdir(parents=True, exist_ok=True)
        with dissent_path.open("a") as fh:
            for d in dissenters:
                fh.write(
                    json.dumps(
                        {
                            "mutation_id": mutation_id,
                            "dissenter": d.juror_id,
                            "verdict": d.verdict,
                            "confidence": d.confidence,
                            "rules_fired": d.rules_fired,
                            "reasoning": d.reasoning,
                            "majority": majority,
                            "invariants": ["CJS-DISSENT-0", "CJS-PERSIST-0"],
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )

    def _persist(self, decision: JuryDecision) -> None:
        """CJS-PERSIST-0: append decision summary to jury ledger.

        Path.open("a") — never builtins.open. Individual verdicts omitted to
        keep the ledger compact; dissent ledger carries full reasoning.
        """
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "mutation_id": decision.mutation_id,
            "majority_verdict": decision.majority_verdict,
            "approve_count": decision.approve_count,
            "reject_count": decision.reject_count,
            "jury_size": decision.jury_size,
            "unanimous": decision.unanimous,
            "dissent_recorded": decision.dissent_recorded,
            "decision_digest": decision.decision_digest,
            "invariants": ["CJS-0", "CJS-QUORUM-0", "CJS-DETERM-0",
                           "CJS-DISSENT-0", "CJS-PERSIST-0"],
        }
        with self.ledger_path.open("a") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")


__all__ = [
    "ConstitutionalJury",
    "JuryDecision",
    "JurorVerdict",
    "ConstitutionalJuryConfigError",
    "JuryQuorumError",
    "is_high_stakes",
    "JURY_SIZE",
    "MAJORITY_REQUIRED",
    "HIGH_STAKES_PATHS",
]
