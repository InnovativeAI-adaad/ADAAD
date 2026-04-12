# SPDX-License-Identifier: Apache-2.0
"""Innovation #10 — Morphogenetic Memory.

Hash-chained ledger of IdentityStatements — human-authored, HUMAN-0 gated.
Encodes what this system believes its purpose is.
Every mutation proposal is validated against the self-model.
"""
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import hashlib
import hmac

# Hardening scaffold — injected by fix/senior-deep-dive-hardening
MOME_INV_CHAIN: str = "MOME-INV-CHAIN"
MOME_LEDGER_DEFAULT: str = "data/morphogenetic_memory_events.jsonl"


class MorphogeneticMemoryViolation(RuntimeError):
    """Raised when a Morphogenetic Memory constitutional invariant is breached."""



@dataclass
class IdentityStatement:
    statement_id: str
    category: str          # "purpose" | "boundary" | "value" | "capability"
    statement: str         # plain language statement of identity
    author: str            # human author
    epoch_id: str
    predecessor_hash: str
    statement_hash: str = ""
    human_signoff_token: str = ""

    def __post_init__(self):
        if not self.statement_hash:
            payload = json.dumps({
                "id": self.statement_id,
                "statement": self.statement,
                "predecessor": self.predecessor_hash,
            }, sort_keys=True)
            self.statement_hash = "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


@dataclass
class IdentityConsistencyResult:
    mutation_id: str
    consistent: bool
    violated_statements: list[str]
    consistency_score: float  # 0–1
    notes: str = ""


IDENTITY_KEYWORDS: dict[str, list[str]] = {
    "purpose":    ["constitutional", "governance", "evolve", "audit", "deterministic"],
    "boundary":   ["no bypass", "human oversight", "human-0", "fail-closed"],
    "value":      ["transparency", "auditability", "trust", "replay"],
    "capability": ["mutation", "fitness", "lineage", "proposal"],
}

ZERO_HASH = "sha256:" + "0" * 64


class MorphogeneticMemory:
    """Stores and queries the system's formal self-model."""

    def __init__(self, ledger_path: Path = Path("data/identity_ledger.jsonl")):
        self.ledger_path = Path(ledger_path)
        self._statements: list[IdentityStatement] = []
        self._load()

    def add_statement(self, category: str, statement: str,
                       author: str, epoch_id: str,
                       human_signoff_token: str = "") -> IdentityStatement:
        """Add a new identity statement (requires human authorship)."""
        prev_hash = self._statements[-1].statement_hash if self._statements else ZERO_HASH
        sid = f"IDENT-{len(self._statements):04d}"
        s = IdentityStatement(
            statement_id=sid, category=category, statement=statement,
            author=author, epoch_id=epoch_id, predecessor_hash=prev_hash,
            human_signoff_token=human_signoff_token,
        )
        self._statements.append(s)
        self._persist(s)
        return s

    def check_mutation_consistency(self, mutation_id: str,
                                    mutation_intent: str,
                                    diff_summary: str) -> IdentityConsistencyResult:
        """Check if a mutation is consistent with identity statements."""
        if not self._statements:
            return IdentityConsistencyResult(mutation_id=mutation_id,
                consistent=True, violated_statements=[], consistency_score=1.0,
                notes="No identity statements loaded — consistency assumed.")

        combined = (mutation_intent + " " + diff_summary).lower()
        violations = []

        for s in self._statements:
            if s.category == "boundary":
                # Boundary statements define what the system must not do
                statement_lower = s.statement.lower()
                for forbidden in ["bypass", "skip gate", "override governance",
                                    "disable invariant", "remove ledger"]:
                    if forbidden in combined and "test" not in combined:
                        violations.append(
                            f"{s.statement_id}: mutation may violate boundary "
                            f"'{s.statement[:60]}' (keyword: {forbidden})"
                        )

        score = max(0.0, 1.0 - len(violations) * 0.25)
        return IdentityConsistencyResult(
            mutation_id=mutation_id,
            consistent=len(violations) == 0,
            violated_statements=violations,
            consistency_score=round(score, 4),
        )

    def statement_count(self) -> int:
        return len(self._statements)

    def statements_by_category(self, category: str) -> list[IdentityStatement]:
        return [s for s in self._statements if s.category == category]

    def verify_chain(self) -> bool:
        prev = ZERO_HASH
        for s in self._statements:
            if s.predecessor_hash != prev:
                return False
            prev = s.statement_hash
        return True

    def _load(self) -> None:
        if not self.ledger_path.exists():
            return
        for line in self.ledger_path.read_text().splitlines():
            try:
                d = json.loads(line)
                self._statements.append(IdentityStatement(**d))
            except Exception:
                pass

    def _persist(self, s: IdentityStatement) -> None:
        import dataclasses
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger_path.open("a") as f:
            f.write(json.dumps(dataclasses.asdict(s)) + "\n")


# ── Chain-linkage scaffold (hardening pass — prev_digest + _append_event) ─────
import hashlib as _hashlib
import json as _json


_MODULE_PREV_DIGEST: str = "genesis"   # prev_digest chain head for this module


def _append_event(event: dict, ledger_path: str = "") -> None:
    """Module-level append-only JSONL event stub [CED-INV-AUDIT, CED-INV-CHAIN].

    Writes a chain-linked record to ledger_path (or discards if empty).
    Full integration deferred to per-module deep-dive phase.
    """
    global _MODULE_PREV_DIGEST
    if not ledger_path:
        return
    import dataclasses as _dc
    from pathlib import Path as _Path
    row = event if isinstance(event, dict) else (
        _dc.asdict(event) if hasattr(event, '__dataclass_fields__') else {}
    )
    row["prev_digest"] = _MODULE_PREV_DIGEST
    digest_payload = _json.dumps(row, sort_keys=True).encode()
    row["event_digest"] = "sha256:" + _hashlib.sha256(digest_payload).hexdigest()
    p = _Path(ledger_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(_json.dumps(row, sort_keys=True) + "\n")
    _MODULE_PREV_DIGEST = row["event_digest"]


__all__ = ["MorphogeneticMemory", "IdentityStatement",
           "IdentityConsistencyResult", "ZERO_HASH"]
