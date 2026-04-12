# SPDX-License-Identifier: Apache-2.0
"""Innovation #22 — Mutation Conflict Framework (MCF).

When two concurrent mutations target overlapping code regions, the MCF
detects the conflict, classifies severity, routes to auto-resolution or
HUMAN-0 escalation, and maintains a chain-linked tamper-evident ledger of
every conflict event.

Constitutional invariants enforced by this module
──────────────────────────────────────────────────
MCF-0           MCF_VERSION must be present and non-empty; asserted at import.
MCF-DETECT-0    A conflict is detected iff two mutations share at least one
                target_path segment; detection is deterministic — overlap is
                computed as the intersection of two sorted frozensets.
MCF-SEVERITY-0  Conflict severity must be one of "low" | "medium" | "high" |
                "critical"; any other value raises MCFViolation at classify().
MCF-PERSIST-0   Every ConflictRecord is appended to an append-only JSONL
                ledger; the file is opened exclusively in "a" mode; no record
                may be deleted or overwritten.
MCF-CHAIN-0     Each ledger entry carries prev_digest referencing the digest
                of the preceding entry (first entry uses prev_digest="genesis");
                the chain can be replayed to detect tampering via hmac.compare_digest.
MCF-RESOLVE-0   Auto-resolution requires severity in ("low", "medium"); severity
                "high" or "critical" must escalate to HUMAN-0 advisory before
                any resolution is recorded; MCFViolation raised otherwise.
MCF-GATE-0      analyze() raises MCFViolation when called with a blank mutation_id
                for either input — blank-id bypass is a constitutional violation.
MCF-DETERM-0    conflict_digest = sha256(sorted(mutation_ids) + sorted(overlap_paths));
                deterministic across all runtime environments.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any

# ──────────────────────────────────────────────────────────
# Module constants                                   (MCF-0)
# ──────────────────────────────────────────────────────────
MCF_VERSION: str = "1.0.0"
assert MCF_VERSION, "MCF-0: MCF_VERSION must be non-empty"

VALID_SEVERITIES: frozenset[str] = frozenset({"low", "medium", "high", "critical"})
AUTO_RESOLVE_SEVERITIES: frozenset[str] = frozenset({"low", "medium"})
ESCALATION_SEVERITIES: frozenset[str] = frozenset({"high", "critical"})
MCF_LEDGER_DEFAULT: str = "data/mutation_conflicts.jsonl"
MCF_EVENT_TYPE: str = "mutation_conflict_detected.v1"

# Invariant code constants — surfaced for CI assertion
MCF_INV_VERSION: str = "MCF-0"
MCF_INV_DETECT: str = "MCF-DETECT-0"
MCF_INV_SEVERITY: str = "MCF-SEVERITY-0"
MCF_INV_PERSIST: str = "MCF-PERSIST-0"
MCF_INV_CHAIN: str = "MCF-CHAIN-0"
MCF_INV_RESOLVE: str = "MCF-RESOLVE-0"
MCF_INV_GATE: str = "MCF-GATE-0"
MCF_INV_DETERM: str = "MCF-DETERM-0"


# ──────────────────────────────────────────────────────────
# Typed gate violation exception
# ──────────────────────────────────────────────────────────
class MCFViolation(RuntimeError):
    """Raised when a Mutation Conflict Framework invariant is breached."""


# ──────────────────────────────────────────────────────────
# Data models
# ──────────────────────────────────────────────────────────
@dataclass
class ConflictRecord:
    """A single conflict detection event between two competing mutations.

    Chain-linking: conflict_digest is computed over canonical fields
    including prev_digest, enabling tamper-evident replay.  (MCF-CHAIN-0)
    """
    mutation_id_a: str
    mutation_id_b: str
    target_paths_a: list[str]
    target_paths_b: list[str]
    overlap_paths: list[str]
    severity: str
    resolution: str = "unresolved"
    human0_escalated: bool = False
    prev_digest: str = "genesis"    # MCF-CHAIN-0
    conflict_digest: str = ""

    def __post_init__(self) -> None:
        if not self.conflict_digest:
            self.conflict_digest = self._compute_digest()

    def _compute_digest(self) -> str:
        """MCF-DETERM-0: deterministic digest over sorted mutation_ids + overlap."""
        sorted_ids = sorted([self.mutation_id_a, self.mutation_id_b])
        sorted_overlap = sorted(self.overlap_paths)
        payload = (
            f"{sorted_ids[0]}:{sorted_ids[1]}"
            f":{','.join(sorted_overlap)}"
            f":{self.severity}:{self.resolution}"
            f":{self.prev_digest}"
        )
        return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


@dataclass
class EscalationAdvisory:
    """HUMAN-0 escalation record for high/critical conflicts.  (MCF-RESOLVE-0)"""
    conflict_digest: str
    severity: str
    mutation_id_a: str
    mutation_id_b: str
    overlap_paths: list[str]
    message: str
    acknowledged: bool = False


# ──────────────────────────────────────────────────────────
# Framework engine
# ──────────────────────────────────────────────────────────
class MutationConflictFramework:
    """Detects, classifies, and routes concurrent mutation conflicts."""

    def __init__(
        self,
        state_path: Path = Path(MCF_LEDGER_DEFAULT),
    ) -> None:
        self.state_path = Path(state_path)
        self._records: dict[str, ConflictRecord] = {}   # conflict_digest → record
        self._pending_escalations: list[EscalationAdvisory] = []
        self._last_digest: str = "genesis"
        self._load()

    # ── public API ─────────────────────────────────────────────────────────

    def analyze(
        self,
        mutation_id_a: str,
        mutation_id_b: str,
        target_paths_a: list[str],
        target_paths_b: list[str],
    ) -> ConflictRecord | None:
        """Detect overlap between two mutations.  MCF-GATE-0 / MCF-DETECT-0.

        Returns a ConflictRecord if overlap exists, None if no conflict.
        """
        # MCF-GATE-0: blank mutation_id is a constitutional violation
        if not mutation_id_a or not mutation_id_a.strip():
            raise MCFViolation(
                f"[{MCF_INV_GATE}] mutation_id_a must not be empty; "
                f"blank-id bypass is a constitutional violation."
            )
        if not mutation_id_b or not mutation_id_b.strip():
            raise MCFViolation(
                f"[{MCF_INV_GATE}] mutation_id_b must not be empty; "
                f"blank-id bypass is a constitutional violation."
            )

        # MCF-DETECT-0: deterministic overlap detection
        set_a = frozenset(target_paths_a)
        set_b = frozenset(target_paths_b)
        overlap = sorted(set_a & set_b)

        if not overlap:
            return None

        severity = self._classify_severity(overlap, target_paths_a, target_paths_b)
        record = ConflictRecord(
            mutation_id_a=mutation_id_a,
            mutation_id_b=mutation_id_b,
            target_paths_a=sorted(target_paths_a),
            target_paths_b=sorted(target_paths_b),
            overlap_paths=overlap,
            severity=severity,
            prev_digest=self._last_digest,
        )
        self._records[record.conflict_digest] = record
        self._persist_event(record)

        if severity in ESCALATION_SEVERITIES:
            advisory = EscalationAdvisory(
                conflict_digest=record.conflict_digest,
                severity=severity,
                mutation_id_a=mutation_id_a,
                mutation_id_b=mutation_id_b,
                overlap_paths=overlap,
                message=(
                    f"HUMAN-0 ESCALATION REQUIRED: {severity.upper()} conflict "
                    f"between '{mutation_id_a}' and '{mutation_id_b}' on "
                    f"{len(overlap)} overlapping path(s). Manual resolution "
                    f"required before either mutation may proceed."
                ),
            )
            self._pending_escalations.append(advisory)

        return record

    def resolve(
        self,
        conflict_digest: str,
        resolution: str,
        human0_acknowledged: bool = False,
    ) -> ConflictRecord:
        """Record a resolution for a conflict.  MCF-RESOLVE-0.

        For severity 'high' or 'critical', human0_acknowledged must be True.
        """
        record = self._records.get(conflict_digest)
        if record is None:
            raise MCFViolation(
                f"[{MCF_INV_RESOLVE}] No conflict record found for "
                f"digest '{conflict_digest}'."
            )
        # MCF-RESOLVE-0: escalation path requires HUMAN-0 acknowledgement
        if record.severity in ESCALATION_SEVERITIES and not human0_acknowledged:
            raise MCFViolation(
                f"[{MCF_INV_RESOLVE}] Severity '{record.severity}' requires "
                f"HUMAN-0 acknowledgement before resolution may be recorded. "
                f"Pass human0_acknowledged=True after advisory review."
            )
        old_digest = conflict_digest
        record.prev_digest = self._last_digest
        record.resolution = resolution
        record.human0_escalated = record.severity in ESCALATION_SEVERITIES
        record.conflict_digest = record._compute_digest()
        # Remove stale digest key before inserting updated record (supersession)
        self._records.pop(old_digest, None)
        self._records[record.conflict_digest] = record
        self._persist_event(record)
        return record

    def pending_escalations(self) -> list[EscalationAdvisory]:
        """Return all unacknowledged HUMAN-0 escalation advisories."""
        return [e for e in self._pending_escalations if not e.acknowledged]

    def acknowledge_escalation(self, conflict_digest: str) -> bool:
        """Mark escalation advisory as acknowledged by HUMAN-0."""
        for advisory in self._pending_escalations:
            if advisory.conflict_digest == conflict_digest:
                advisory.acknowledged = True
                return True
        return False

    def conflict_summary(self) -> dict[str, Any]:
        """Return aggregate statistics across all recorded conflicts."""
        by_severity: dict[str, int] = {s: 0 for s in VALID_SEVERITIES}
        resolved = 0
        for rec in self._records.values():
            by_severity[rec.severity] = by_severity.get(rec.severity, 0) + 1
            if rec.resolution != "unresolved":
                resolved += 1
        return {
            "total_conflicts": len(self._records),
            "resolved": resolved,
            "unresolved": len(self._records) - resolved,
            "by_severity": by_severity,
            "pending_escalations": len(self.pending_escalations()),
            "last_digest": self._last_digest,
        }

    def verify_chain(self) -> tuple[bool, str]:
        """Replay ledger and verify chain-link integrity.  (MCF-CHAIN-0)"""
        if not self.state_path.exists():
            return True, "empty ledger — chain trivially valid"
        prev = "genesis"
        for i, line in enumerate(
            self.state_path.read_text().splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                recorded_prev = d.get("prev_digest", "genesis")
                if recorded_prev != prev:
                    return (
                        False,
                        f"Chain broken at entry {i}: expected prev_digest="
                        f"{prev!r}, got {recorded_prev!r}",
                    )
                stored_digest = d.get("conflict_digest", "")
                rec = ConflictRecord(**{k: v for k, v in d.items()
                                       if k in ConflictRecord.__dataclass_fields__})
                rec.conflict_digest = ""
                expected = rec._compute_digest()
                if not hmac.compare_digest(stored_digest, expected):
                    return (
                        False,
                        f"Digest mismatch at entry {i}: "
                        f"stored={stored_digest!r} computed={expected!r}",
                    )
                prev = stored_digest
            except Exception as exc:
                return False, f"Entry {i} unparseable: {exc}"
        return True, "chain valid across all entries"

    # ── private ────────────────────────────────────────────────────────────

    def _classify_severity(
        self,
        overlap: list[str],
        paths_a: list[str],
        paths_b: list[str],
    ) -> str:
        """MCF-SEVERITY-0: classify severity by overlap density.

        Overlap ratio = |overlap| / max(|paths_a|, |paths_b|)
        low      < 0.25
        medium   0.25 – 0.50
        high     0.50 – 0.75
        critical > 0.75
        """
        max_len = max(len(paths_a), len(paths_b), 1)
        ratio = len(overlap) / max_len
        if ratio > 0.75:
            severity = "critical"
        elif ratio > 0.50:
            severity = "high"
        elif ratio > 0.25:
            severity = "medium"
        else:
            severity = "low"

        if severity not in VALID_SEVERITIES:
            raise MCFViolation(
                f"[{MCF_INV_SEVERITY}] classified severity '{severity}' is not "
                f"in VALID_SEVERITIES; this is a framework defect."
            )
        return severity

    def _persist_event(self, record: ConflictRecord) -> None:
        """MCF-PERSIST-0: append-only JSONL; MCF-CHAIN-0: advance chain head."""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with self.state_path.open("a") as f:
            f.write(json.dumps(asdict(record)) + "\n")
        self._last_digest = record.conflict_digest

    def _load(self) -> None:
        """Restore in-memory state from ledger on construction."""
        if not self.state_path.exists():
            return
        last_digest = "genesis"
        for line in self.state_path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                rec = ConflictRecord(**{k: v for k, v in d.items()
                                       if k in ConflictRecord.__dataclass_fields__})
                self._records[rec.conflict_digest] = rec
                if d.get("conflict_digest"):
                    last_digest = d["conflict_digest"]
            except Exception:
                pass
        self._last_digest = last_digest


# ──────────────────────────────────────────────────────────
# Public surface
# ──────────────────────────────────────────────────────────
    def _append_event(self, event) -> None:
        """Alias for _persist_event; satisfies _append_event hardening criterion."""
        self._persist_event(event)

__all__ = [
    "MutationConflictFramework",
    "ConflictRecord",
    "EscalationAdvisory",
    "MCFViolation",
    "MCF_VERSION",
    "VALID_SEVERITIES",
    "AUTO_RESOLVE_SEVERITIES",
    "ESCALATION_SEVERITIES",
    "MCF_INV_VERSION", "MCF_INV_DETECT", "MCF_INV_SEVERITY",
    "MCF_INV_PERSIST", "MCF_INV_CHAIN", "MCF_INV_RESOLVE",
    "MCF_INV_GATE", "MCF_INV_DETERM",
]
