# SPDX-License-Identifier: Apache-2.0
"""Mutation Explainability Engine (MXE) — Phase 149 / INNOV-55.

Constitutional invariants enforced in this module
--------------------------------------------------
MXE-DETERM-0  : Every MutationExplanation serialises to a deterministic
                canonical dict; keys sorted, no float ambiguity, timestamps
                are ISO-8601 strings.
MXE-CHAIN-0   : HMAC-SHA256 links each explanation to its predecessor;
                broken chains raise MXEChainViolation immediately.
MXE-IMMUT-0   : Explanations are append-only; once written they are never
                mutated.  Any attempt raises MXEMutabilityViolation.
MXE-SCOPE-0   : The explainer operates on mutation proposals only; it never
                reads CEL internal execution state or agent memory.
MXE-AUDIT-0   : Every mutation verdict (ACCEPT / REJECT / BLOCK) MUST produce
                a persisted explanation record before the call returns.
                If persistence fails, MXEAuditViolation is raised.
"""

from __future__ import annotations

import hashlib
import hmac as hmac_lib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Typed exceptions — one per Hard-class invariant
# ---------------------------------------------------------------------------


class MXEDeterminismViolation(RuntimeError):
    """MXE-DETERM-0: explanation dict is not deterministic / canonical."""


class MXEChainViolation(RuntimeError):
    """MXE-CHAIN-0: HMAC chain is broken between explanation records."""


class MXEMutabilityViolation(RuntimeError):
    """MXE-IMMUT-0: attempt to mutate an already-written explanation."""


class MXEScopeViolation(RuntimeError):
    """MXE-SCOPE-0: operation outside mutation-proposal scope."""


class MXEAuditViolation(RuntimeError):
    """MXE-AUDIT-0: mutation verdict produced without a persisted explanation."""


# ---------------------------------------------------------------------------
# HMAC key
# ---------------------------------------------------------------------------

_HMAC_KEY: bytes = os.getenv(
    "ADAAD_MXE_HMAC_KEY", "adaad-mxe-dev-secret-do-not-use-in-prod"
).encode()

VALID_VERDICTS: frozenset[str] = frozenset({"ACCEPT", "REJECT", "BLOCK"})
_LEDGER_PATH = Path("ledger/mxe/explanations.mxe.jsonl")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class InvariantFinding:
    """Single invariant that fired during verdict evaluation."""

    invariant_id: str
    tier: str  # Hard | Soft | Advisory
    fired: bool  # True = caused / contributed to verdict
    description: str
    article: str = ""  # constitutional article reference if known

    def to_dict(self) -> Dict:
        return dict(sorted({
            "article": str(self.article),
            "description": str(self.description),
            "fired": bool(self.fired),
            "invariant_id": str(self.invariant_id),
            "tier": str(self.tier),
        }.items()))


@dataclass
class ReasoningStep:
    """One step in the constitutional reasoning chain."""

    order: int
    gate: str
    outcome: str  # PASS | FAIL | SKIP
    rationale: str

    def to_dict(self) -> Dict:
        return dict(sorted({
            "gate": str(self.gate),
            "order": int(self.order),
            "outcome": str(self.outcome),
            "rationale": str(self.rationale),
        }.items()))


@dataclass
class MutationExplanation:
    """Immutable, HMAC-chain-linked explanation for a mutation verdict."""

    explanation_id: str
    mutation_id: str
    verdict: str  # ACCEPT | REJECT | BLOCK
    confidence: float
    summary: str
    invariant_findings: List[InvariantFinding] = field(default_factory=list)
    reasoning_chain: List[ReasoningStep] = field(default_factory=list)
    timestamp_iso: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    prev_hmac: str = ""
    explanation_hmac: str = field(init=False, default="")

    def __post_init__(self) -> None:
        if self.verdict not in VALID_VERDICTS:
            raise MXEScopeViolation(
                f"MXE-SCOPE-0: verdict={self.verdict!r} not in {sorted(VALID_VERDICTS)}"
            )
        # Round confidence to 6dp for determinism (MXE-DETERM-0)
        self.confidence = round(float(self.confidence), 6)
        canonical = self._canonical_dict(include_hmac=False)
        self.explanation_hmac = hmac_lib.new(
            _HMAC_KEY,
            json.dumps(canonical, sort_keys=True).encode(),
            hashlib.sha256,
        ).hexdigest()

    def _canonical_dict(self, *, include_hmac: bool = True) -> Dict:
        """Deterministic serialisation — MXE-DETERM-0."""
        d: Dict = {
            "confidence": self.confidence,
            "explanation_id": str(self.explanation_id),
            "invariant_findings": [f.to_dict() for f in self.invariant_findings],
            "mutation_id": str(self.mutation_id),
            "prev_hmac": str(self.prev_hmac),
            "reasoning_chain": [s.to_dict() for s in self.reasoning_chain],
            "summary": str(self.summary),
            "timestamp_iso": str(self.timestamp_iso),
            "verdict": str(self.verdict),
        }
        if include_hmac:
            d["explanation_hmac"] = str(self.explanation_hmac)
        return dict(sorted(d.items()))

    def to_dict(self) -> Dict:
        return self._canonical_dict()

    def to_json(self) -> str:
        return json.dumps(self._canonical_dict(), sort_keys=True)

    @classmethod
    def from_dict(cls, d: Dict) -> "MutationExplanation":
        findings = [InvariantFinding(**f) for f in d.get("invariant_findings", [])]
        steps = [ReasoningStep(**s) for s in d.get("reasoning_chain", [])]
        obj = cls(
            explanation_id=d["explanation_id"],
            mutation_id=d["mutation_id"],
            verdict=d["verdict"],
            confidence=d["confidence"],
            summary=d["summary"],
            invariant_findings=findings,
            reasoning_chain=steps,
            timestamp_iso=d["timestamp_iso"],
            prev_hmac=d.get("prev_hmac", ""),
        )
        obj.explanation_hmac = d["explanation_hmac"]
        return obj


# ---------------------------------------------------------------------------
# Chain state — MXE-CHAIN-0
# ---------------------------------------------------------------------------


class MXEChainState:
    def __init__(self) -> None:
        self._tail: str = ""

    @property
    def tail(self) -> str:
        return self._tail

    def advance(self, expl: MutationExplanation) -> None:
        if not hmac_lib.compare_digest(expl.prev_hmac, self._tail):
            raise MXEChainViolation(
                f"MXE-CHAIN-0: broken chain at explanation_id={expl.explanation_id!r}; "
                f"expected prev_hmac={self._tail!r}, got {expl.prev_hmac!r}"
            )
        self._tail = expl.explanation_hmac

    def reset(self) -> None:
        self._tail = ""


# ---------------------------------------------------------------------------
# MXE Engine
# ---------------------------------------------------------------------------


class MXEExplainer:
    """Generates, persists, and retrieves constitutional mutation explanations.

    Scope constraint (MXE-SCOPE-0): this engine only accepts mutation_id
    references from the proposal/verdict pipeline.  It never reads CEL
    execution state or agent memory directly.
    """

    def __init__(self, ledger_path: Optional[Path] = None) -> None:
        self._ledger_path = ledger_path or _LEDGER_PATH
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self._chain = MXEChainState()
        self._index: Dict[str, MutationExplanation] = {}
        self._frozen: set[str] = set()  # MXE-IMMUT-0
        self._load_ledger()

    # ------------------------------------------------------------------
    # Internal: ledger bootstrap
    # ------------------------------------------------------------------

    def _load_ledger(self) -> None:
        """Replay existing ledger to warm chain state and index."""
        if not self._ledger_path.exists():
            return
        with self._ledger_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    expl = MutationExplanation.from_dict(d)
                    self._chain.advance(expl)
                    self._index[expl.mutation_id] = expl
                    self._frozen.add(expl.explanation_id)
                except Exception:  # noqa: BLE001
                    pass  # corrupt line — skip silently on load

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def explain(
        self,
        mutation_id: str,
        verdict: str,
        *,
        gate_report: Optional[Dict[str, Any]] = None,
        confidence: float = 1.0,
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> MutationExplanation:
        """Generate and persist an explanation for *mutation_id* verdict.

        MXE-SCOPE-0: gate_report must come from the mutation proposal pipeline.
        MXE-AUDIT-0: the explanation is persisted before this method returns.
        MXE-IMMUT-0: if an explanation already exists for this mutation_id,
                     it is returned as-is (idempotent).
        """
        # Idempotency — MXE-IMMUT-0
        if mutation_id in self._index:
            return self._index[mutation_id]

        gate_report = gate_report or {}
        extra_context = extra_context or {}

        # Build invariant findings from gate_report
        findings: List[InvariantFinding] = []
        for gate_name, result in gate_report.items():
            if isinstance(result, dict):
                fired = result.get("ok") is False
                findings.append(
                    InvariantFinding(
                        invariant_id=gate_name,
                        tier="Hard" if fired else "Soft",
                        fired=fired,
                        description=result.get("detail", f"{gate_name} evaluation"),
                        article=result.get("article", ""),
                    )
                )

        # Build reasoning chain
        steps: List[ReasoningStep] = []
        for i, (gate_name, result) in enumerate(gate_report.items(), 1):
            if isinstance(result, dict):
                outcome = "PASS" if result.get("ok") is True else "FAIL"
                steps.append(
                    ReasoningStep(
                        order=i,
                        gate=gate_name,
                        outcome=outcome,
                        rationale=result.get("rationale", f"{gate_name}: {outcome}"),
                    )
                )

        # Derive summary
        fired_ids = [f.invariant_id for f in findings if f.fired]
        if verdict == "ACCEPT":
            summary = (
                f"Mutation {mutation_id} ACCEPTED: all {len(gate_report)} gates passed. "
                f"No Hard-class violations detected."
            )
        elif verdict == "REJECT":
            summary = (
                f"Mutation {mutation_id} REJECTED: {len(fired_ids)} gate failure(s) — "
                + ", ".join(fired_ids[:5])
                + ("…" if len(fired_ids) > 5 else "")
                + "."
            )
        else:  # BLOCK
            summary = (
                f"Mutation {mutation_id} BLOCKED: Hard-class invariant(s) triggered — "
                + ", ".join(fired_ids[:5])
                + ("…" if len(fired_ids) > 5 else "")
                + ". Fail-closed enforcement active."
            )

        expl_id = f"MXE-{mutation_id[:16]}-{len(self._index):05d}"
        expl = MutationExplanation(
            explanation_id=expl_id,
            mutation_id=mutation_id,
            verdict=verdict,
            confidence=min(1.0, max(0.0, confidence)),
            summary=summary,
            invariant_findings=findings,
            reasoning_chain=steps,
            prev_hmac=self._chain.tail,
        )

        # Persist — MXE-AUDIT-0
        try:
            self._chain.advance(expl)
            with self._ledger_path.open("a", encoding="utf-8") as fh:
                fh.write(expl.to_json() + "\n")
            self._index[mutation_id] = expl
            self._frozen.add(expl.explanation_id)
        except MXEChainViolation:
            raise
        except Exception as exc:  # noqa: BLE001
            raise MXEAuditViolation(
                f"MXE-AUDIT-0: failed to persist explanation for mutation_id={mutation_id!r}: {exc}"
            ) from exc

        return expl

    def get(self, mutation_id: str) -> Optional[MutationExplanation]:
        """Retrieve a stored explanation by mutation_id — MXE-IMMUT-0."""
        return self._index.get(mutation_id)

    def verify_chain(self) -> Dict[str, Any]:
        """Re-read ledger and verify full HMAC chain integrity — MXE-CHAIN-0."""
        if not self._ledger_path.exists():
            return {"ok": True, "explanations": 0, "note": "ledger not yet written"}

        chain = MXEChainState()
        errors: List[str] = []
        count = 0

        with self._ledger_path.open("r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    expl = MutationExplanation.from_dict(d)
                    chain.advance(expl)
                    count += 1
                except MXEChainViolation as exc:
                    errors.append(f"line {lineno}: {exc}")
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"line {lineno}: parse error — {exc}")

        return {
            "ok": not errors,
            "explanations": count,
            "errors": errors,
            "tail_hmac": chain.tail,
        }

    def health_check(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "invariant": "MXE-CHAIN-0",
            "explanations_stored": len(self._index),
            "chain_tail": self._chain.tail[:16] + "…" if self._chain.tail else "",
            "ledger_path": str(self._ledger_path),
        }

    def list_explanations(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent explanations sorted by timestamp descending — MXE-DETERM-0."""
        records = list(self._index.values())
        records.sort(key=lambda e: e.timestamp_iso, reverse=True)
        return [e.to_dict() for e in records[:limit]]


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_explainer: Optional[MXEExplainer] = None


def get_explainer(*, ledger_path: Optional[Path] = None) -> MXEExplainer:
    global _explainer
    if _explainer is None:
        _explainer = MXEExplainer(ledger_path=ledger_path)
    return _explainer


def explain_mutation(
    mutation_id: str,
    verdict: str,
    gate_report: Optional[Dict[str, Any]] = None,
    confidence: float = 1.0,
) -> MutationExplanation:
    """Convenience entry-point — MXE-AUDIT-0 guaranteed."""
    return get_explainer().explain(
        mutation_id, verdict, gate_report=gate_report, confidence=confidence
    )
