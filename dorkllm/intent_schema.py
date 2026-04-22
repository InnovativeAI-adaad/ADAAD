# SPDX-License-Identifier: Apache-2.0
"""
dorkllm/intent_schema.py
Phase 147 · INNOV-53 · Intent Expression Schema

Typed intent manifest binding user-expressed requests to constitutionally
governed, CEL-safe operations. Enforces scope boundaries, dry-run isolation,
and confidence floors before any mutation is permitted to fire.

Hard-class invariants enforced here:
  INTENT-SCHEMA-0   Every autonomous action originating from user input MUST
                    carry a validated IntentRecord. Unvalidated actions are
                    constitutionally prohibited.
  INTENT-DRYRUN-0   dry_run=True MUST never produce a ledger write, file
                    mutation, or GovernanceGate evaluation. Violation is a
                    constitutional breach.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


# ── Constants ─────────────────────────────────────────────────────────────────

INTENT_SCHEMA_VERSION = "1.0.0"
INTENT_CONFIDENCE_FLOOR_DEFAULT: float = 0.75
INTENT_SCOPE_LOCKED: tuple[str, ...] = (
    "governance/",
    "artifacts/governance/",
    "security/",
    ".adaad_agent_state.json",
    "VERSION",
    "pyproject.toml",
)

# ── INTENT-SCHEMA-0 ───────────────────────────────────────────────────────────
# Hard invariant: every autonomous action originating from user input MUST carry
# a validated IntentRecord. Bare strings, dicts, or untyped payloads are
# constitutionally prohibited as action descriptors. Enforcement: IntentRecord
# construction raises IntentSchemaViolation on any invalid field combination.
# ─────────────────────────────────────────────────────────────────────────────

# ── INTENT-DRYRUN-0 ───────────────────────────────────────────────────────────
# Hard invariant: when dry_run=True, AskDispatcher.preview_intent() MUST return
# a DiffPreview without writing to the lineage ledger, mutating any file, or
# evaluating the GovernanceGate. Any code path that attempts a side-effectful
# operation while dry_run=True MUST raise IntentDryRunViolation.
# ─────────────────────────────────────────────────────────────────────────────


class IntentAction(str, Enum):
    """Enumerated set of CEL-safe autonomous actions."""
    QUERY = "query"                        # read-only state retrieval
    PROPOSE_MUTATION = "propose_mutation"  # draft a mutation for review
    GROUND_ASK = "ground_ask"             # RAGS-grounded question
    PREVIEW_DIFF = "preview_diff"         # compute diff without applying
    EXPLAIN = "explain"                   # explain a governance artifact
    ROLLBACK_PREVIEW = "rollback_preview" # preview a phase rollback (read-only)


class RequestorRole(str, Enum):
    """Roles permitted to originate intents."""
    HUMAN_0 = "HUMAN-0"          # Dustin L. Reid — full authority
    DEVADAAD = "DEVADAAD"        # Track A agent — scoped authority
    OPERATOR = "operator"        # authenticated operator — advisory only
    ANONYMOUS = "anonymous"      # unauthenticated — query-only


class IntentStatus(str, Enum):
    PENDING = "pending"
    PREVIEWED = "previewed"
    APPROVED = "approved"
    REJECTED_SCOPE = "rejected_scope"
    REJECTED_CONFIDENCE = "rejected_confidence"
    REJECTED_LOCKED = "rejected_locked"
    EXECUTED = "executed"


class IntentSchemaViolation(Exception):
    """Raised when an IntentRecord fails INTENT-SCHEMA-0 validation."""


class IntentDryRunViolation(Exception):
    """Raised when a side-effectful operation is attempted during dry_run (INTENT-DRYRUN-0)."""


class IntentScopeRejection(Exception):
    """Raised when intent targets a locked or out-of-scope path."""


# ── Core types ────────────────────────────────────────────────────────────────

@dataclass
class IntentRecord:
    """
    Typed intent manifest. MUST be validated before any governed action fires.
    INTENT-SCHEMA-0: construction validates all fields; raises IntentSchemaViolation on failure.
    """
    action: IntentAction
    scope_path: str                                # target path or module (e.g. "dorkllm/")
    dry_run: bool = True                           # default safe — must be explicitly False
    confidence_floor: float = INTENT_CONFIDENCE_FLOOR_DEFAULT
    requestor_role: RequestorRole = RequestorRole.DEVADAAD
    query_text: str = ""                           # original user expression
    context: dict[str, Any] = field(default_factory=dict)
    intent_id: str = field(default="")
    created_at: str = field(default="")
    status: IntentStatus = field(default=IntentStatus.PENDING)
    schema_version: str = field(default=INTENT_SCHEMA_VERSION)

    def __post_init__(self) -> None:
        # INTENT-SCHEMA-0 enforcement
        if not isinstance(self.action, IntentAction):
            try:
                self.action = IntentAction(self.action)
            except ValueError as exc:
                raise IntentSchemaViolation(
                    f"INTENT-SCHEMA-0: invalid action '{self.action}'. "
                    f"Must be one of {[a.value for a in IntentAction]}"
                ) from exc

        if not isinstance(self.requestor_role, RequestorRole):
            try:
                self.requestor_role = RequestorRole(self.requestor_role)
            except ValueError as exc:
                raise IntentSchemaViolation(
                    f"INTENT-SCHEMA-0: invalid requestor_role '{self.requestor_role}'."
                ) from exc

        if not self.scope_path or not self.scope_path.strip():
            raise IntentSchemaViolation(
                "INTENT-SCHEMA-0: scope_path must be a non-empty string."
            )

        if not (0.0 <= self.confidence_floor <= 1.0):
            raise IntentSchemaViolation(
                f"INTENT-SCHEMA-0: confidence_floor must be in [0.0, 1.0], got {self.confidence_floor}."
            )

        # Auto-assign ID and timestamp if not provided
        if not self.intent_id:
            self.intent_id = _generate_intent_id(self)
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

        # Scope lock check
        _assert_scope_not_locked(self.scope_path, self.action)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["action"] = self.action.value
        d["requestor_role"] = self.requestor_role.value
        d["status"] = self.status.value
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


@dataclass
class ChangedFile:
    """A single file change in a DiffPreview."""
    path: str
    change_type: str      # "modified" | "added" | "deleted"
    lines_added: int = 0
    lines_removed: int = 0
    summary: str = ""


@dataclass
class DiffPreview:
    """
    Read-only preview of what an intent would produce if executed.
    INTENT-DRYRUN-0: construction of DiffPreview MUST NOT produce any
    ledger write or file mutation. It is purely descriptive.
    """
    intent_id: str
    scope_path: str
    action: str
    proposed_changes: list[ChangedFile] = field(default_factory=list)
    invariants_to_exercise: list[str] = field(default_factory=list)
    estimated_test_count: int = 0
    confidence: float = 0.0
    requires_human0_gate: bool = False
    blocking_reason: str = ""
    preview_hash: str = field(default="")
    generated_at: str = field(default="")

    def __post_init__(self) -> None:
        if not self.preview_hash:
            payload = f"{self.intent_id}:{self.scope_path}:{self.action}:{self.confidence}"
            self.preview_hash = hashlib.sha256(payload.encode()).hexdigest()[:16]
        if not self.generated_at:
            self.generated_at = datetime.now(timezone.utc).isoformat()

    @property
    def is_approvable(self) -> bool:
        """True if the intent can proceed to execution (no blocking reason, confidence met)."""
        return not self.blocking_reason and self.confidence >= INTENT_CONFIDENCE_FLOOR_DEFAULT

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "scope_path": self.scope_path,
            "action": self.action,
            "proposed_changes": [
                {"path": c.path, "change_type": c.change_type,
                 "lines_added": c.lines_added, "lines_removed": c.lines_removed,
                 "summary": c.summary}
                for c in self.proposed_changes
            ],
            "invariants_to_exercise": self.invariants_to_exercise,
            "estimated_test_count": self.estimated_test_count,
            "confidence": self.confidence,
            "requires_human0_gate": self.requires_human0_gate,
            "blocking_reason": self.blocking_reason,
            "is_approvable": self.is_approvable,
            "preview_hash": self.preview_hash,
            "generated_at": self.generated_at,
        }


@dataclass
class ScopeRejection:
    """Structured rejection when intent targets a locked or out-of-scope path."""
    intent_id: str
    scope_path: str
    reason: str
    locked_prefix: Optional[str] = None
    remediation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _generate_intent_id(record: IntentRecord) -> str:
    payload = f"{record.action}:{record.scope_path}:{record.requestor_role}:{record.query_text}"
    digest = hashlib.sha256(payload.encode()).hexdigest()[:12]
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"INTENT-{ts}-{digest}"


def _assert_scope_not_locked(scope_path: str, action: IntentAction) -> None:
    """
    INTENT-SCHEMA-0: raise IntentScopeRejection if scope_path targets a
    constitutionally locked path and the action is not read-only (QUERY/EXPLAIN).
    """
    read_only_actions = {IntentAction.QUERY, IntentAction.EXPLAIN,
                         IntentAction.PREVIEW_DIFF, IntentAction.ROLLBACK_PREVIEW}
    if action in read_only_actions:
        return  # read-only actions may inspect locked paths
    for locked in INTENT_SCOPE_LOCKED:
        if scope_path.startswith(locked) or scope_path == locked.rstrip("/"):
            raise IntentScopeRejection(
                f"INTENT-SCHEMA-0: path '{scope_path}' is constitutionally locked "
                f"(prefix '{locked}'). Mutating actions are prohibited. "
                "Use QUERY or EXPLAIN to inspect, or initiate HUMAN-0 Track B ceremony."
            )


def validate_intent(record: IntentRecord) -> tuple[bool, str]:
    """
    Secondary validation gate. Returns (ok, reason).
    Primary validation occurs in IntentRecord.__post_init__ (INTENT-SCHEMA-0).
    """
    if record.confidence_floor < 0.5:
        return False, f"confidence_floor {record.confidence_floor} below minimum 0.5"
    if record.requestor_role == RequestorRole.ANONYMOUS and record.action != IntentAction.QUERY:
        return False, "ANONYMOUS role is restricted to QUERY actions only"
    if record.action == IntentAction.PROPOSE_MUTATION and record.dry_run:
        # Mutation proposals in dry_run are valid — they produce a DiffPreview only
        pass
    return True, ""
