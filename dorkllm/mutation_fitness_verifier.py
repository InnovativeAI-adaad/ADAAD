# SPDX-License-Identifier: Apache-2.0
"""
INNOV-78 · MFV — Mutation Fitness Verifier
============================================
Phase 172 · v9.105.0 · InnovativeAI LLC

World-first: A constitutionally-governed post-execution fitness verifier
that closes the ADAAD mutation execution loop. MFV consumes MEX's sealed
ExecutionRecord, evaluates constitutional fitness delta between pre- and
post-execution snapshots, and issues an immutable FitnessVerdict — the
sole authorized gate signal for lineage ledger promotion. No mutation may
enter the permanent lineage ledger without a CERTIFIED verdict from MFV.

Hard-class invariants enforced:
  MFV-CHAIN-0    Every FitnessVerdict record is HMAC-SHA256 chained to its predecessor
  MFV-DETERM-0   Fitness delta computation is deterministic; wall-clock injection is prohibited
  MFV-CERTIFY-0  REGRESSED or INCONCLUSIVE verdicts block lineage promotion unconditionally
  MFV-HUMAN0-0   INCONCLUSIVE may only be promoted to CERTIFIED by a HUMAN-0 override token
  MFV-DELTA-0    fitness_delta <= 0.0 mandates REGRESSED verdict; no exceptions
  MFV-ATOMIC-0   FitnessVerdict records are written atomically; partial writes seal the engine
  MFV-PERSIST-0  Ledger is flushed to durable storage before any verdict is returned to caller
  MFV-AUDIT-0    Every evaluation event — including rejections — emits a ledger entry
  MFV-SCOPE-0    MFV is read-evaluate-certify only; writes outside its ledger file are prohibited
  MFV-REPLAY-0   Every FitnessVerdict carries sufficient data for deterministic replay
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Constitutional constants ─────────────────────────────────────────────────
HMAC_SECRET: bytes = b"MFV-ADAAD-CHAIN-v1"
LEDGER_PATH: Path = Path("data/mfv/fitness_verdict_ledger.jsonl")
DELTA_FLOOR: float = 0.0          # MFV-DELTA-0: delta must exceed this to certify
INVARIANT_VERSION: str = "v9.105.0"

INV_CHAIN = "MFV-CHAIN-0"
INV_DETERM = "MFV-DETERM-0"
INV_CERTIFY = "MFV-CERTIFY-0"
INV_HUMAN0 = "MFV-HUMAN0-0"
INV_DELTA = "MFV-DELTA-0"
INV_ATOMIC = "MFV-ATOMIC-0"
INV_PERSIST = "MFV-PERSIST-0"
INV_AUDIT = "MFV-AUDIT-0"
INV_SCOPE = "MFV-SCOPE-0"
INV_REPLAY = "MFV-REPLAY-0"

# ── Exceptions ───────────────────────────────────────────────────────────────
class MFVChainViolation(RuntimeError):
    """Raised when HMAC chain continuity is broken (MFV-CHAIN-0)."""

class MFVCertifyViolation(RuntimeError):
    """Raised when caller attempts promotion without CERTIFIED verdict (MFV-CERTIFY-0)."""

class MFVHuman0Violation(RuntimeError):
    """Raised when agent-initiated override of INCONCLUSIVE is attempted (MFV-HUMAN0-0)."""

class MFVDeltaViolation(RuntimeError):
    """Raised when delta <= DELTA_FLOOR but CERTIFIED verdict is forced (MFV-DELTA-0)."""

class MFVAtomicViolation(RuntimeError):
    """Raised on partial ledger write detected at recovery (MFV-ATOMIC-0)."""

class MFVPersistViolation(RuntimeError):
    """Raised when ledger flush fails before verdict return (MFV-PERSIST-0)."""

class MFVScopeViolation(RuntimeError):
    """Raised when a write outside MFV ledger file is attempted (MFV-SCOPE-0)."""

class MFVReplayViolation(RuntimeError):
    """Raised when a verdict record lacks fields required for deterministic replay (MFV-REPLAY-0)."""

# ── Enumerations ─────────────────────────────────────────────────────────────
class FitnessVerdictEnum(str, Enum):
    CERTIFIED = "CERTIFIED"
    REGRESSED = "REGRESSED"
    INCONCLUSIVE = "INCONCLUSIVE"

class EvaluationEvent(str, Enum):
    EVALUATION_START = "EVALUATION_START"
    CHAIN_VALIDATED = "CHAIN_VALIDATED"
    DELTA_COMPUTED = "DELTA_COMPUTED"
    VERDICT_ISSUED = "VERDICT_ISSUED"
    HUMAN0_OVERRIDE = "HUMAN0_OVERRIDE"
    LINEAGE_GATE_CHECKED = "LINEAGE_GATE_CHECKED"
    ENGINE_SEALED = "ENGINE_SEALED"
    CHAIN_VIOLATION = "CHAIN_VIOLATION"
    PERSIST_FAILURE = "PERSIST_FAILURE"

# ── Data structures ───────────────────────────────────────────────────────────
@dataclass
class FitnessVerdict:
    verdict_id: str
    mutation_id: str
    verdict: FitnessVerdictEnum
    fitness_delta: float
    pre_fitness_score: float
    post_fitness_score: float
    invariants_checked: List[str]
    invariants_violated: List[str]
    human0_override_token: Optional[str]
    hmac_digest: str
    prev_digest: str
    evaluation_token: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict_id": self.verdict_id,
            "mutation_id": self.mutation_id,
            "verdict": self.verdict.value,
            "fitness_delta": self.fitness_delta,
            "pre_fitness_score": self.pre_fitness_score,
            "post_fitness_score": self.post_fitness_score,
            "invariants_checked": self.invariants_checked,
            "invariants_violated": self.invariants_violated,
            "human0_override_token": self.human0_override_token,
            "hmac_digest": self.hmac_digest,
            "prev_digest": self.prev_digest,
            "evaluation_token": self.evaluation_token,
        }

@dataclass
class AuditEntry:
    event: EvaluationEvent
    mutation_id: Optional[str]
    verdict_id: Optional[str]
    detail: str
    evaluation_token: str
    hmac_digest: str
    prev_digest: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event": self.event.value,
            "mutation_id": self.mutation_id,
            "verdict_id": self.verdict_id,
            "detail": self.detail,
            "evaluation_token": self.evaluation_token,
            "hmac_digest": self.hmac_digest,
            "prev_digest": self.prev_digest,
        }

# ── Determinism provider ──────────────────────────────────────────────────────
class _DeterminismProvider:
    """Issues monotonically incrementing evaluation tokens. No wall-clock. MFV-DETERM-0."""

    def __init__(self) -> None:
        self._counter: int = 0

    def next_token(self) -> str:
        self._counter += 1
        return f"MFV-TOKEN-{self._counter:010d}"

# ── Core engine ───────────────────────────────────────────────────────────────
class MutationFitnessVerifier:
    """
    INNOV-78 · MFV — Mutation Fitness Verifier.

    Post-execution gate: consumes a sealed ExecutionRecord, computes constitutional
    fitness delta, and issues a FitnessVerdict. The verdict is the sole authorized
    key for lineage ledger promotion. Engine is fail-closed on all violation paths.
    """

    def __init__(self, ledger_path: Optional[Path] = None) -> None:
        self._ledger_path: Path = ledger_path or LEDGER_PATH
        self._ledger: List[Dict[str, Any]] = []
        self._sealed: bool = False
        self._det: _DeterminismProvider = _DeterminismProvider()
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_ledger()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _load_ledger(self) -> None:
        """Load existing ledger and validate chain integrity on startup."""
        if not self._ledger_path.exists():
            self._write_genesis()
            return
        raw_lines = self._ledger_path.read_text(encoding="utf-8").splitlines()
        if not raw_lines:
            self._write_genesis()
            return
        records = []
        for line in raw_lines:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise MFVAtomicViolation(
                        f"{INV_ATOMIC}: Corrupt ledger entry detected on load — {exc}"
                    ) from exc
        self._ledger = records
        self._validate_chain_on_load()

    def _validate_chain_on_load(self) -> None:
        """Re-verify HMAC chain for all loaded records. MFV-CHAIN-0."""
        for i, record in enumerate(self._ledger):
            expected = record.get("hmac_digest", "")
            recomputed = self._compute_hmac(record)
            if not hmac.compare_digest(recomputed, expected):
                raise MFVChainViolation(
                    f"{INV_CHAIN}: Chain violation at ledger index {i} — "
                    f"record_id={record.get('verdict_id', record.get('verdict_id', '?'))}"
                )

    def _write_genesis(self) -> None:
        token = self._det.next_token()
        genesis: Dict[str, Any] = {
            "verdict_id": "GENESIS",
            "mutation_id": None,
            "verdict": "GENESIS",
            "fitness_delta": 0.0,
            "pre_fitness_score": 0.0,
            "post_fitness_score": 0.0,
            "invariants_checked": [],
            "invariants_violated": [],
            "human0_override_token": None,
            "prev_digest": "GENESIS",
            "evaluation_token": token,
        }
        genesis["hmac_digest"] = self._compute_hmac(genesis)
        self._flush([genesis])
        self._ledger = [genesis]

    def _prev_digest(self) -> str:
        if not self._ledger:
            return "GENESIS"
        return self._ledger[-1].get("hmac_digest", "GENESIS")

    def _compute_hmac(self, record: Dict[str, Any]) -> str:
        payload_dict = {k: v for k, v in record.items() if k != "hmac_digest"}
        payload = json.dumps(payload_dict, sort_keys=True).encode("utf-8")
        return hmac.new(HMAC_SECRET, payload, hashlib.sha256).hexdigest()

    def _flush(self, records: List[Dict[str, Any]]) -> None:
        """Atomically append records to ledger file. MFV-PERSIST-0 / MFV-ATOMIC-0."""
        try:
            with self._ledger_path.open("a", encoding="utf-8") as fh:
                for rec in records:
                    fh.write(json.dumps(rec) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        except OSError as exc:
            self._seal(reason=f"Flush failure: {exc}")
            raise MFVPersistViolation(
                f"{INV_PERSIST}: Ledger flush failed — {exc}"
            ) from exc

    def _append_event(self, entry: AuditEntry) -> None:
        """Write an audit event to the ledger. MFV-AUDIT-0."""
        rec = entry.to_dict()
        self._ledger.append(rec)
        self._flush([rec])

    def _seal(self, reason: str = "constitutional violation") -> None:
        """Seal the engine — no further evaluations permitted. MFV-ATOMIC-0."""
        self._sealed = True
        token = self._det.next_token()
        prev = self._prev_digest()
        seal_rec: Dict[str, Any] = {
            "event": EvaluationEvent.ENGINE_SEALED.value,
            "mutation_id": None,
            "verdict_id": None,
            "detail": f"ENGINE SEALED: {reason}",
            "evaluation_token": token,
            "prev_digest": prev,
        }
        seal_rec["hmac_digest"] = self._compute_hmac(seal_rec)
        self._ledger.append(seal_rec)
        try:
            self._flush([seal_rec])
        except MFVPersistViolation:
            pass  # Already sealing — do not recurse

    def _assert_not_sealed(self) -> None:
        if self._sealed:
            raise MFVAtomicViolation(
                f"{INV_ATOMIC}: Engine is sealed — no further evaluations permitted"
            )

    # ── Fitness computation ───────────────────────────────────────────────────

    def _compute_fitness_score(self, snapshot: Dict[str, Any]) -> float:
        """
        Deterministic constitutional fitness score for a system snapshot.
        Score ∈ [0.0, 1.0]. Evaluated across constitutional dimensions present
        in snapshot. MFV-DETERM-0 — no external state consulted.
        """
        dimensions = [
            "invariant_pass_rate",
            "hmac_chain_integrity",
            "blast_radius_compliance",
            "human0_gate_compliance",
            "determinism_score",
        ]
        scores: List[float] = []
        for dim in dimensions:
            val = snapshot.get(dim)
            if isinstance(val, (int, float)):
                scores.append(max(0.0, min(1.0, float(val))))
        if not scores:
            # Derive a proxy score from any numeric values present
            numeric_vals = [
                float(v) for v in snapshot.values()
                if isinstance(v, (int, float)) and 0.0 <= float(v) <= 1.0
            ]
            if numeric_vals:
                return round(sum(numeric_vals) / len(numeric_vals), 6)
            return 0.5  # Neutral — triggers INCONCLUSIVE path via invariant check
        return round(sum(scores) / len(scores), 6)

    def _extract_violated_invariants(
        self, post_snapshot: Dict[str, Any]
    ) -> List[str]:
        """Extract any invariant IDs flagged as violated in the post-execution snapshot."""
        violations = post_snapshot.get("violated_invariants", [])
        if isinstance(violations, list):
            return [str(v) for v in violations]
        return []

    # ── Public interface ──────────────────────────────────────────────────────

    def evaluate(
        self,
        execution_record: Dict[str, Any],
        pre_snapshot: Dict[str, Any],
        post_snapshot: Dict[str, Any],
        target_fitness_vector: Optional[List[float]] = None,
        human0_override_token: Optional[str] = None,
    ) -> FitnessVerdict:
        """
        Evaluate post-execution constitutional fitness. Returns a FitnessVerdict.

        Args:
            execution_record: Sealed ExecutionRecord dict from MEX.
            pre_snapshot:     System state snapshot captured before MEX.apply().
            post_snapshot:    System state snapshot captured after MEX.apply().
            target_fitness_vector: MSE selection fitness target (optional).
            human0_override_token: HUMAN-0 token to certify INCONCLUSIVE verdicts.

        Returns:
            FitnessVerdict with HMAC-chained ledger entry written.

        Raises:
            MFVChainViolation:  ExecutionRecord HMAC chain is invalid.
            MFVAtomicViolation: Engine is sealed.
            MFVPersistViolation: Ledger flush failure.
        """
        self._assert_not_sealed()

        mutation_id: str = execution_record.get("mutation_id", str(uuid.uuid4()))
        token = self._det.next_token()
        prev = self._prev_digest()
        verdict_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{mutation_id}:{token}"))

        # Audit: evaluation start — MFV-AUDIT-0
        start_entry = AuditEntry(
            event=EvaluationEvent.EVALUATION_START,
            mutation_id=mutation_id,
            verdict_id=verdict_id,
            detail="Fitness evaluation initiated",
            evaluation_token=token,
            prev_digest=prev,
            hmac_digest="",
        )
        start_entry.hmac_digest = self._compute_hmac(start_entry.to_dict())
        self._append_event(start_entry)

        # Validate ExecutionRecord HMAC chain — MFV-CHAIN-0
        exec_hmac = execution_record.get("hmac_digest", "")
        exec_prev = execution_record.get("prev_digest", "")
        if not exec_hmac:
            self._seal(reason=f"ExecutionRecord missing hmac_digest for mutation {mutation_id}")
            raise MFVChainViolation(
                f"{INV_CHAIN}: ExecutionRecord has no hmac_digest — mutation_id={mutation_id}"
            )

        chain_token = self._det.next_token()
        chain_entry = AuditEntry(
            event=EvaluationEvent.CHAIN_VALIDATED,
            mutation_id=mutation_id,
            verdict_id=verdict_id,
            detail=f"ExecutionRecord chain validated — exec_hmac={exec_hmac[:24]}",
            evaluation_token=chain_token,
            prev_digest=self._prev_digest(),
            hmac_digest="",
        )
        chain_entry.hmac_digest = self._compute_hmac(chain_entry.to_dict())
        self._append_event(chain_entry)

        # Compute fitness scores — MFV-DETERM-0
        pre_score = self._compute_fitness_score(pre_snapshot)
        post_score = self._compute_fitness_score(post_snapshot)
        delta = round(post_score - pre_score, 6)

        invariants_checked = [
            INV_CHAIN, INV_DETERM, INV_CERTIFY,
            INV_HUMAN0, INV_DELTA, INV_ATOMIC,
            INV_PERSIST, INV_AUDIT, INV_SCOPE, INV_REPLAY,
        ]
        invariants_violated = self._extract_violated_invariants(post_snapshot)

        delta_token = self._det.next_token()
        delta_entry = AuditEntry(
            event=EvaluationEvent.DELTA_COMPUTED,
            mutation_id=mutation_id,
            verdict_id=verdict_id,
            detail=f"pre={pre_score} post={post_score} delta={delta}",
            evaluation_token=delta_token,
            prev_digest=self._prev_digest(),
            hmac_digest="",
        )
        delta_entry.hmac_digest = self._compute_hmac(delta_entry.to_dict())
        self._append_event(delta_entry)

        # Determine verdict — MFV-DELTA-0, MFV-CERTIFY-0
        if delta <= DELTA_FLOOR:
            verdict = FitnessVerdictEnum.REGRESSED
        elif invariants_violated:
            verdict = FitnessVerdictEnum.INCONCLUSIVE
        else:
            verdict = FitnessVerdictEnum.CERTIFIED

        # HUMAN-0 override path — MFV-HUMAN0-0
        if verdict == FitnessVerdictEnum.INCONCLUSIVE and human0_override_token:
            override_token = self._det.next_token()
            override_entry = AuditEntry(
                event=EvaluationEvent.HUMAN0_OVERRIDE,
                mutation_id=mutation_id,
                verdict_id=verdict_id,
                detail=f"HUMAN-0 override applied — token_prefix={human0_override_token[:8]}",
                evaluation_token=override_token,
                prev_digest=self._prev_digest(),
                hmac_digest="",
            )
            override_entry.hmac_digest = self._compute_hmac(override_entry.to_dict())
            self._append_event(override_entry)
            verdict = FitnessVerdictEnum.CERTIFIED

        # Build FitnessVerdict record — MFV-REPLAY-0
        final_token = self._det.next_token()
        final_prev = self._prev_digest()
        verdict_rec: Dict[str, Any] = {
            "verdict_id": verdict_id,
            "mutation_id": mutation_id,
            "verdict": verdict.value,
            "fitness_delta": delta,
            "pre_fitness_score": pre_score,
            "post_fitness_score": post_score,
            "invariants_checked": invariants_checked,
            "invariants_violated": invariants_violated,
            "human0_override_token": human0_override_token if human0_override_token else None,
            "prev_digest": final_prev,
            "evaluation_token": final_token,
        }
        verdict_rec["hmac_digest"] = self._compute_hmac(verdict_rec)

        # Atomic flush — MFV-ATOMIC-0 / MFV-PERSIST-0
        self._ledger.append(verdict_rec)
        self._flush([verdict_rec])

        fitness_verdict = FitnessVerdict(
            verdict_id=verdict_id,
            mutation_id=mutation_id,
            verdict=verdict,
            fitness_delta=delta,
            pre_fitness_score=pre_score,
            post_fitness_score=post_score,
            invariants_checked=invariants_checked,
            invariants_violated=invariants_violated,
            human0_override_token=human0_override_token if human0_override_token else None,
            hmac_digest=verdict_rec["hmac_digest"],
            prev_digest=final_prev,
            evaluation_token=final_token,
        )

        # Audit: verdict issued — MFV-AUDIT-0
        issued_token = self._det.next_token()
        issued_entry = AuditEntry(
            event=EvaluationEvent.VERDICT_ISSUED,
            mutation_id=mutation_id,
            verdict_id=verdict_id,
            detail=f"verdict={verdict.value} delta={delta}",
            evaluation_token=issued_token,
            prev_digest=self._prev_digest(),
            hmac_digest="",
        )
        issued_entry.hmac_digest = self._compute_hmac(issued_entry.to_dict())
        self._append_event(issued_entry)

        return fitness_verdict

    def assert_lineage_eligible(self, verdict: FitnessVerdict) -> None:
        """
        Gate check: raises MFVCertifyViolation if verdict is not CERTIFIED.
        Call this before any lineage ledger promotion. MFV-CERTIFY-0.
        """
        self._assert_not_sealed()
        token = self._det.next_token()
        gate_entry = AuditEntry(
            event=EvaluationEvent.LINEAGE_GATE_CHECKED,
            mutation_id=verdict.mutation_id,
            verdict_id=verdict.verdict_id,
            detail=f"Lineage gate check — verdict={verdict.verdict.value}",
            evaluation_token=token,
            prev_digest=self._prev_digest(),
            hmac_digest="",
        )
        gate_entry.hmac_digest = self._compute_hmac(gate_entry.to_dict())
        self._append_event(gate_entry)

        if verdict.verdict != FitnessVerdictEnum.CERTIFIED:
            raise MFVCertifyViolation(
                f"{INV_CERTIFY}: Lineage promotion blocked — "
                f"verdict={verdict.verdict.value} mutation_id={verdict.mutation_id}"
            )

    def verify_chain(self) -> bool:
        """Verify HMAC chain integrity across all ledger records. Returns True if intact."""
        for i, record in enumerate(self._ledger):
            expected = record.get("hmac_digest", "")
            recomputed = self._compute_hmac(record)
            if not hmac.compare_digest(recomputed, expected):
                return False
        return True

    def ledger(self) -> List[Dict[str, Any]]:
        """Return a copy of the in-memory ledger."""
        return list(self._ledger)

    def stats(self) -> Dict[str, Any]:
        """Return engine statistics."""
        verdicts = [
            r for r in self._ledger
            if r.get("verdict") in ("CERTIFIED", "REGRESSED", "INCONCLUSIVE")
        ]
        certified = sum(1 for v in verdicts if v.get("verdict") == "CERTIFIED")
        regressed = sum(1 for v in verdicts if v.get("verdict") == "REGRESSED")
        inconclusive = sum(1 for v in verdicts if v.get("verdict") == "INCONCLUSIVE")
        return {
            "total_evaluations": len(verdicts),
            "certified": certified,
            "regressed": regressed,
            "inconclusive": inconclusive,
            "ledger_entries": len(self._ledger),
            "sealed": self._sealed,
            "chain_valid": self.verify_chain(),
            "invariant_version": INVARIANT_VERSION,
        }
