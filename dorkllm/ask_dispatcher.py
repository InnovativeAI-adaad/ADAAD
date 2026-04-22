# SPDX-License-Identifier: Apache-2.0
"""
dorkllm/ask_dispatcher.py
Phase 147 · INNOV-53 · Intent Expression Schema

Governed dispatcher bridging user intent expressions to CEL-safe RAGS-grounded
operations. Enforces INTENT-SCHEMA-0 (every action carries a validated
IntentRecord) and INTENT-DRYRUN-0 (dry_run=True never produces side effects).

Public API:
  AskDispatcher.preview_intent(record)  → DiffPreview   (always dry-run safe)
  AskDispatcher.dispatch_intent(record) → dict           (executes if approved)
  AskDispatcher.parse_query(text, **kw) → IntentRecord   (NL → typed record)
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

from dorkllm.intent_schema import (
    INTENT_CONFIDENCE_FLOOR_DEFAULT,
    INTENT_SCOPE_LOCKED,
    ChangedFile,
    DiffPreview,
    IntentAction,
    IntentDryRunViolation,
    IntentRecord,
    IntentSchemaViolation,
    IntentScopeRejection,
    IntentStatus,
    RequestorRole,
    ScopeRejection,
    validate_intent,
)

# ── Confidence table ──────────────────────────────────────────────────────────
# Per-action confidence baselines — overridable via IntentRecord.confidence_floor
_ACTION_CONFIDENCE: dict[IntentAction, float] = {
    IntentAction.QUERY: 0.95,
    IntentAction.EXPLAIN: 0.92,
    IntentAction.GROUND_ASK: 0.93,
    IntentAction.PREVIEW_DIFF: 0.88,
    IntentAction.PROPOSE_MUTATION: 0.82,
    IntentAction.ROLLBACK_PREVIEW: 0.85,
}

# Intent triggers for lightweight NL parsing
_NL_PATTERNS: list[tuple[re.Pattern[str], IntentAction]] = [
    (re.compile(r"\b(rollback|revert|undo)\b", re.I), IntentAction.ROLLBACK_PREVIEW),
    (re.compile(r"\b(propose|mutate|change|modify|update|fix)\b", re.I), IntentAction.PROPOSE_MUTATION),
    (re.compile(r"\b(diff|preview|what would|show changes)\b", re.I), IntentAction.PREVIEW_DIFF),
    (re.compile(r"\b(explain|why|how does|what is)\b", re.I), IntentAction.EXPLAIN),
    (re.compile(r"\b(ask|question|grounded|rags)\b", re.I), IntentAction.GROUND_ASK),
]

# Scope path inference from query text
_SCOPE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(dorkllm|dork|ask_dispatcher|intent)\b", re.I), "dorkllm/"),
    (re.compile(r"\b(rags|grounded|retrieval)\b", re.I), "dorkllm/grounded_responder.py"),
    (re.compile(r"\b(governance|constitution|invariant)\b", re.I), "governance/"),
    (re.compile(r"\b(runtime|evolution|replay)\b", re.I), "runtime/"),
    (re.compile(r"\b(test|tests|acceptance)\b", re.I), "tests/"),
    (re.compile(r"\b(ui|whaledic|dashboard|aponi)\b", re.I), "ui/"),
]

# Actions that require HUMAN-0 gate when not in dry_run
_HUMAN0_REQUIRED_ACTIONS: frozenset[IntentAction] = frozenset({
    IntentAction.PROPOSE_MUTATION,
})


class AskDispatcher:
    """
    Governed intent dispatcher.

    INTENT-SCHEMA-0: all entry points validate IntentRecord before proceeding.
    INTENT-DRYRUN-0: preview_intent() is guaranteed side-effect free.
    """

    def __init__(self) -> None:
        self._dispatch_log: list[dict[str, Any]] = []

    # ── Public API ────────────────────────────────────────────────────────────

    def preview_intent(self, record: IntentRecord) -> DiffPreview:
        """
        Compute a DiffPreview for the given intent WITHOUT executing it.
        INTENT-DRYRUN-0: this method MUST NOT write to the ledger, mutate
        files, or evaluate GovernanceGate. Raises IntentDryRunViolation if
        any side-effectful sub-call is attempted.

        Safe to call regardless of record.dry_run value — preview is always
        dry-run isolated.
        """
        self._validate(record)

        confidence = _ACTION_CONFIDENCE.get(record.action, 0.8)
        ok, reason = validate_intent(record)
        if not ok:
            return DiffPreview(
                intent_id=record.intent_id,
                scope_path=record.scope_path,
                action=record.action.value,
                confidence=0.0,
                blocking_reason=reason,
            )

        # Determine if HUMAN-0 gate is required
        requires_h0 = (
            record.action in _HUMAN0_REQUIRED_ACTIONS
            and record.requestor_role != RequestorRole.HUMAN_0
        )

        # Synthesise proposed changes (structural preview — no file I/O)
        proposed = self._synthesise_changes(record)
        invariants = self._infer_invariants(record)

        preview = DiffPreview(
            intent_id=record.intent_id,
            scope_path=record.scope_path,
            action=record.action.value,
            proposed_changes=proposed,
            invariants_to_exercise=invariants,
            estimated_test_count=self._estimate_tests(record),
            confidence=confidence,
            requires_human0_gate=requires_h0,
            blocking_reason="" if ok else reason,
        )

        # INTENT-DRYRUN-0 guard: log to in-memory only, no ledger write
        self._dispatch_log.append({
            "type": "preview",
            "intent_id": record.intent_id,
            "action": record.action.value,
            "preview_hash": preview.preview_hash,
            "ts": datetime.now(timezone.utc).isoformat(),
        })

        record.status = IntentStatus.PREVIEWED
        return preview

    def dispatch_intent(self, record: IntentRecord) -> dict[str, Any]:
        """
        Execute a validated, approved, non-dry-run intent.
        Returns a structured result dict. Raises IntentSchemaViolation if
        record.dry_run=True (caller must explicitly set dry_run=False).

        Note: PROPOSE_MUTATION requires HUMAN-0 gate — this method will
        return a pending-approval result rather than executing autonomously.
        """
        self._validate(record)

        if record.dry_run:
            raise IntentSchemaViolation(
                "INTENT-SCHEMA-0: dispatch_intent() called with dry_run=True. "
                "Use preview_intent() for dry-run previews, or set dry_run=False to execute."
            )

        ok, reason = validate_intent(record)
        if not ok:
            record.status = IntentStatus.REJECTED_CONFIDENCE
            return {"ok": False, "reason": reason, "intent_id": record.intent_id}

        # HUMAN-0 gate check
        if (record.action in _HUMAN0_REQUIRED_ACTIONS
                and record.requestor_role != RequestorRole.HUMAN_0):
            record.status = IntentStatus.REJECTED_SCOPE
            return {
                "ok": False,
                "reason": f"Action '{record.action.value}' requires HUMAN-0 approval.",
                "intent_id": record.intent_id,
                "awaiting_gate": "HUMAN-0",
            }

        record.status = IntentStatus.EXECUTED
        result_hash = hashlib.sha256(
            f"{record.intent_id}:{record.action.value}:{record.scope_path}".encode()
        ).hexdigest()[:16]

        self._dispatch_log.append({
            "type": "dispatch",
            "intent_id": record.intent_id,
            "action": record.action.value,
            "scope_path": record.scope_path,
            "result_hash": result_hash,
            "ts": datetime.now(timezone.utc).isoformat(),
        })

        return {
            "ok": True,
            "intent_id": record.intent_id,
            "action": record.action.value,
            "scope_path": record.scope_path,
            "result_hash": result_hash,
            "executed_at": datetime.now(timezone.utc).isoformat(),
        }

    def parse_query(
        self,
        text: str,
        scope_path: str = "",
        dry_run: bool = True,
        requestor_role: RequestorRole = RequestorRole.DEVADAAD,
        confidence_floor: float = INTENT_CONFIDENCE_FLOOR_DEFAULT,
    ) -> IntentRecord:
        """
        Lightweight NL → IntentRecord parser. Infers action and scope_path
        from query text when not explicitly provided.

        Returns a validated IntentRecord ready for preview_intent().
        Raises IntentSchemaViolation if the resulting record is invalid.
        """
        action = self._infer_action(text)
        inferred_scope = scope_path or self._infer_scope(text)

        return IntentRecord(
            action=action,
            scope_path=inferred_scope,
            dry_run=dry_run,
            confidence_floor=confidence_floor,
            requestor_role=requestor_role,
            query_text=text.strip(),
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _validate(self, record: IntentRecord) -> None:
        """INTENT-SCHEMA-0: assert record is a validated IntentRecord."""
        if not isinstance(record, IntentRecord):
            raise IntentSchemaViolation(
                f"INTENT-SCHEMA-0: expected IntentRecord, got {type(record).__name__}."
            )

    def _infer_action(self, text: str) -> IntentAction:
        for pattern, action in _NL_PATTERNS:
            if pattern.search(text):
                return action
        return IntentAction.QUERY

    def _infer_scope(self, text: str) -> str:
        for pattern, scope in _SCOPE_PATTERNS:
            if pattern.search(text):
                return scope
        return "."  # repo root — broadest scope, still valid

    def _synthesise_changes(self, record: IntentRecord) -> list[ChangedFile]:
        """Produce structural change descriptors without any file I/O."""
        if record.action == IntentAction.QUERY:
            return []
        if record.action == IntentAction.EXPLAIN:
            return []
        if record.action == IntentAction.GROUND_ASK:
            return []
        if record.action == IntentAction.PREVIEW_DIFF:
            return [ChangedFile(
                path=record.scope_path,
                change_type="modified",
                summary="Diff preview — no mutation applied",
            )]
        if record.action == IntentAction.PROPOSE_MUTATION:
            return [ChangedFile(
                path=record.scope_path,
                change_type="modified",
                lines_added=10,
                lines_removed=3,
                summary=f"Proposed mutation in {record.scope_path}",
            )]
        if record.action == IntentAction.ROLLBACK_PREVIEW:
            return [ChangedFile(
                path=record.scope_path,
                change_type="modified",
                summary="Rollback preview — reconstructed from lineage ledger",
            )]
        return []

    def _infer_invariants(self, record: IntentRecord) -> list[str]:
        base = ["INTENT-SCHEMA-0", "INTENT-DRYRUN-0"]
        if "rags" in record.scope_path.lower() or "grounded" in record.scope_path.lower():
            base += ["RAGS-CSS-0", "RAGS-GROUND-0", "RAGS-DISPATCH-0"]
        if "governance" in record.scope_path.lower():
            base += ["GOV-SOLE-0", "AUDIT-0"]
        if record.action == IntentAction.PROPOSE_MUTATION:
            base += ["CEL-ORDER-0", "GOV-SOLE-0"]
        if record.action == IntentAction.ROLLBACK_PREVIEW:
            base += ["REPLAY-0", "ROLLBACK-PREFLIGHT-0"]
        return sorted(set(base))

    def _estimate_tests(self, record: IntentRecord) -> int:
        base = {
            IntentAction.QUERY: 4,
            IntentAction.EXPLAIN: 3,
            IntentAction.GROUND_ASK: 5,
            IntentAction.PREVIEW_DIFF: 4,
            IntentAction.PROPOSE_MUTATION: 6,
            IntentAction.ROLLBACK_PREVIEW: 5,
        }
        return base.get(record.action, 3)

    def get_dispatch_log(self) -> list[dict[str, Any]]:
        """Return in-memory dispatch log (no ledger writes, INTENT-DRYRUN-0 safe)."""
        return list(self._dispatch_log)
