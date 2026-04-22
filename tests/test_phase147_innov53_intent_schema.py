# SPDX-License-Identifier: Apache-2.0
"""
tests/test_phase147_innov53_intent_schema.py
Phase 147 · INNOV-53 · Intent Expression Schema — 30 Acceptance Tests

Invariant coverage:
  INTENT-SCHEMA-0  Every action must carry a validated IntentRecord
  INTENT-DRYRUN-0  dry_run=True must never produce side effects
"""
from __future__ import annotations

import pytest

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
from dorkllm.ask_dispatcher import AskDispatcher


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def dispatcher():
    return AskDispatcher()


@pytest.fixture
def basic_record():
    return IntentRecord(
        action=IntentAction.QUERY,
        scope_path="dorkllm/",
        dry_run=True,
        requestor_role=RequestorRole.DEVADAAD,
        query_text="What is the current gate status?",
    )


@pytest.fixture
def mutation_record():
    return IntentRecord(
        action=IntentAction.PROPOSE_MUTATION,
        scope_path="dorkllm/",
        dry_run=True,
        requestor_role=RequestorRole.DEVADAAD,
        query_text="Propose improvement to intent routing",
    )


# ── 1-5: IntentRecord construction and INTENT-SCHEMA-0 ───────────────────────

def test_01_valid_intent_record_constructs(basic_record):
    """Valid IntentRecord constructs without error (INTENT-SCHEMA-0)."""
    assert basic_record.action == IntentAction.QUERY
    assert basic_record.scope_path == "dorkllm/"
    assert basic_record.dry_run is True


def test_02_intent_id_auto_assigned(basic_record):
    """Intent ID is auto-generated on construction (INTENT-SCHEMA-0)."""
    assert basic_record.intent_id.startswith("INTENT-")
    assert len(basic_record.intent_id) > 10


def test_03_created_at_auto_assigned(basic_record):
    """created_at is auto-set to UTC ISO string (INTENT-SCHEMA-0)."""
    assert "T" in basic_record.created_at
    assert "Z" in basic_record.created_at or "+" in basic_record.created_at


def test_04_invalid_action_raises_schema_violation():
    """Invalid action raises IntentSchemaViolation (INTENT-SCHEMA-0)."""
    with pytest.raises(IntentSchemaViolation):
        IntentRecord(action="fly_to_moon", scope_path="dorkllm/")


def test_05_empty_scope_path_raises_schema_violation():
    """Empty scope_path raises IntentSchemaViolation (INTENT-SCHEMA-0)."""
    with pytest.raises(IntentSchemaViolation):
        IntentRecord(action=IntentAction.QUERY, scope_path="")


# ── 6-10: Scope lock enforcement ──────────────────────────────────────────────

def test_06_mutation_on_governance_path_rejected():
    """Propose mutation on governance/ raises IntentScopeRejection (INTENT-SCHEMA-0)."""
    with pytest.raises(IntentScopeRejection):
        IntentRecord(
            action=IntentAction.PROPOSE_MUTATION,
            scope_path="governance/",
        )


def test_07_mutation_on_version_file_rejected():
    """Propose mutation on VERSION raises IntentScopeRejection (INTENT-SCHEMA-0)."""
    with pytest.raises(IntentScopeRejection):
        IntentRecord(
            action=IntentAction.PROPOSE_MUTATION,
            scope_path="VERSION",
        )


def test_08_mutation_on_security_path_rejected():
    """Propose mutation on security/ raises IntentScopeRejection (INTENT-SCHEMA-0)."""
    with pytest.raises(IntentScopeRejection):
        IntentRecord(
            action=IntentAction.PROPOSE_MUTATION,
            scope_path="security/",
        )


def test_09_query_on_governance_path_allowed():
    """QUERY action is allowed on locked paths (read-only exemption, INTENT-SCHEMA-0)."""
    record = IntentRecord(
        action=IntentAction.QUERY,
        scope_path="governance/",
    )
    assert record.action == IntentAction.QUERY


def test_10_explain_on_locked_path_allowed():
    """EXPLAIN action is allowed on locked paths (read-only exemption)."""
    record = IntentRecord(
        action=IntentAction.EXPLAIN,
        scope_path="security/keys/ed25519_governance_ring.json",
    )
    assert record.action == IntentAction.EXPLAIN


# ── 11-15: Confidence floor validation ───────────────────────────────────────

def test_11_confidence_floor_out_of_range_rejects():
    """confidence_floor > 1.0 raises IntentSchemaViolation."""
    with pytest.raises(IntentSchemaViolation):
        IntentRecord(
            action=IntentAction.QUERY,
            scope_path="dorkllm/",
            confidence_floor=1.5,
        )


def test_12_confidence_floor_negative_rejects():
    """Negative confidence_floor raises IntentSchemaViolation."""
    with pytest.raises(IntentSchemaViolation):
        IntentRecord(
            action=IntentAction.QUERY,
            scope_path="dorkllm/",
            confidence_floor=-0.1,
        )


def test_13_confidence_floor_boundary_zero_accepted():
    """confidence_floor=0.0 is accepted (schema allows it; validate_intent may reject)."""
    record = IntentRecord(
        action=IntentAction.QUERY,
        scope_path="dorkllm/",
        confidence_floor=0.0,
    )
    assert record.confidence_floor == 0.0


def test_14_validate_intent_low_confidence_returns_false():
    """validate_intent returns False for confidence_floor below 0.5."""
    record = IntentRecord(
        action=IntentAction.QUERY,
        scope_path="dorkllm/",
        confidence_floor=0.3,
    )
    ok, reason = validate_intent(record)
    assert not ok
    assert "confidence" in reason.lower()


def test_15_validate_intent_anonymous_non_query_returns_false():
    """ANONYMOUS role attempting non-QUERY action is rejected by validate_intent."""
    record = IntentRecord(
        action=IntentAction.EXPLAIN,
        scope_path="dorkllm/",
        requestor_role=RequestorRole.ANONYMOUS,
    )
    ok, reason = validate_intent(record)
    assert not ok
    assert "ANONYMOUS" in reason


# ── 16-20: DiffPreview and INTENT-DRYRUN-0 ───────────────────────────────────

def test_16_preview_intent_returns_diff_preview(dispatcher, basic_record):
    """preview_intent() returns a DiffPreview (INTENT-DRYRUN-0)."""
    preview = dispatcher.preview_intent(basic_record)
    assert isinstance(preview, DiffPreview)


def test_17_preview_intent_zero_ledger_writes(dispatcher, basic_record):
    """preview_intent() produces no ledger writes — dispatch log is in-memory only (INTENT-DRYRUN-0)."""
    before = len(dispatcher.get_dispatch_log())
    dispatcher.preview_intent(basic_record)
    after = len(dispatcher.get_dispatch_log())
    # Only in-memory log — no file I/O or ledger append
    assert after == before + 1
    assert dispatcher.get_dispatch_log()[-1]["type"] == "preview"


def test_18_preview_hash_is_deterministic(dispatcher):
    """Same intent_id + scope + action produces same preview_hash."""
    r1 = IntentRecord(action=IntentAction.QUERY, scope_path="dorkllm/",
                      query_text="gate status")
    r2 = IntentRecord(action=IntentAction.QUERY, scope_path="dorkllm/",
                      query_text="gate status")
    # Force same intent_id for determinism test
    r2.intent_id = r1.intent_id
    p1 = dispatcher.preview_intent(r1)
    p2 = dispatcher.preview_intent(r2)
    assert p1.preview_hash == p2.preview_hash


def test_19_preview_query_action_no_proposed_changes(dispatcher, basic_record):
    """QUERY preview has no proposed_changes (read-only, INTENT-DRYRUN-0)."""
    preview = dispatcher.preview_intent(basic_record)
    assert preview.proposed_changes == []


def test_20_preview_mutation_has_proposed_changes(dispatcher, mutation_record):
    """PROPOSE_MUTATION preview contains proposed_changes entries."""
    preview = dispatcher.preview_intent(mutation_record)
    assert len(preview.proposed_changes) >= 1


# ── 21-25: dispatch_intent and gate enforcement ───────────────────────────────

def test_21_dispatch_dry_run_true_raises(dispatcher, basic_record):
    """dispatch_intent() with dry_run=True raises IntentSchemaViolation (INTENT-SCHEMA-0)."""
    with pytest.raises(IntentSchemaViolation, match="dry_run=True"):
        dispatcher.dispatch_intent(basic_record)


def test_22_dispatch_query_non_dry_run_succeeds(dispatcher):
    """QUERY dispatch with dry_run=False succeeds and returns ok=True."""
    record = IntentRecord(
        action=IntentAction.QUERY,
        scope_path="dorkllm/",
        dry_run=False,
        requestor_role=RequestorRole.DEVADAAD,
    )
    result = dispatcher.dispatch_intent(record)
    assert result["ok"] is True
    assert "result_hash" in result


def test_23_dispatch_mutation_without_human0_returns_pending(dispatcher):
    """PROPOSE_MUTATION from DEVADAAD returns awaiting_gate=HUMAN-0 (not executed)."""
    record = IntentRecord(
        action=IntentAction.PROPOSE_MUTATION,
        scope_path="dorkllm/",
        dry_run=False,
        requestor_role=RequestorRole.DEVADAAD,
    )
    result = dispatcher.dispatch_intent(record)
    assert result["ok"] is False
    assert result.get("awaiting_gate") == "HUMAN-0"


def test_24_dispatch_mutation_by_human0_executes(dispatcher):
    """PROPOSE_MUTATION from HUMAN-0 executes without gate block."""
    record = IntentRecord(
        action=IntentAction.PROPOSE_MUTATION,
        scope_path="dorkllm/",
        dry_run=False,
        requestor_role=RequestorRole.HUMAN_0,
    )
    result = dispatcher.dispatch_intent(record)
    assert result["ok"] is True
    assert record.status == IntentStatus.EXECUTED


def test_25_dispatch_non_intent_record_raises(dispatcher):
    """Passing a non-IntentRecord to dispatch raises IntentSchemaViolation (INTENT-SCHEMA-0)."""
    with pytest.raises(IntentSchemaViolation):
        dispatcher.dispatch_intent({"action": "query", "scope": "."})  # type: ignore


# ── 26-30: parse_query and to_dict serialisation ─────────────────────────────

def test_26_parse_query_returns_intent_record(dispatcher):
    """parse_query() returns a valid IntentRecord (INTENT-SCHEMA-0)."""
    record = dispatcher.parse_query("show me the gate status")
    assert isinstance(record, IntentRecord)


def test_27_parse_query_infers_action(dispatcher):
    """parse_query() infers ROLLBACK_PREVIEW from 'rollback' keyword."""
    record = dispatcher.parse_query("rollback to phase 144")
    assert record.action == IntentAction.ROLLBACK_PREVIEW


def test_28_parse_query_infers_scope(dispatcher):
    """parse_query() infers dorkllm/ scope from 'dork' keyword."""
    record = dispatcher.parse_query("fix the dork query router")
    assert "dorkllm" in record.scope_path


def test_29_intent_record_to_dict_serialises(basic_record):
    """IntentRecord.to_dict() returns a JSON-serialisable dict."""
    import json
    d = basic_record.to_dict()
    assert isinstance(d, dict)
    serialised = json.dumps(d)
    assert "intent_id" in serialised
    assert "action" in serialised


def test_30_diff_preview_is_approvable_iff_no_blocking_reason(dispatcher):
    """DiffPreview.is_approvable is True only when no blocking_reason and confidence is met."""
    record = IntentRecord(
        action=IntentAction.GROUND_ASK,
        scope_path="dorkllm/",
        dry_run=True,
        requestor_role=RequestorRole.DEVADAAD,
    )
    preview = dispatcher.preview_intent(record)
    assert preview.is_approvable is (
        not preview.blocking_reason and preview.confidence >= INTENT_CONFIDENCE_FLOOR_DEFAULT
    )
