"""
Phase 195 · INNOV-100 · CPA — Constitutional Provenance Auditor
30-test acceptance suite (T195-CPA-01…T195-CPA-30)
Governor: DUSTIN L REID · InnovativeAI LLC
"""

import hmac as _hmac
import hashlib
import json
import time
import uuid
from pathlib import Path

import pytest

from dorkllm.constitutional_provenance_auditor import (
    ARTIFACT_CLASSES,
    GENESIS_DIGEST,
    GOVERNOR,
    ArtifactClass,
    ConstitutionalProvenanceAuditor,
    ProvenanceBundle,
    ProvenanceChain,
    ProvenanceRecord,
    ProvenanceViolation,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SECRET = b"test-cpa-secret"
PHASE = 195
INNOV = "INNOV-100"
AGENT = "ArchitectAgent"


@pytest.fixture
def auditor(tmp_path):
    ledger = tmp_path / "cpa" / "provenance_ledger.jsonl"
    return ConstitutionalProvenanceAuditor(
        ledger_path=ledger,
        hmac_secret=SECRET,
        governor=GOVERNOR,
    )


def _make_record(
    artifact_id="art-001",
    artifact_class="invariant",
    predecessor_digest=GENESIS_DIGEST,
    operation="CREATE",
    phase=PHASE,
    ancestors=None,
):
    return ProvenanceRecord(
        record_id=str(uuid.uuid4()),
        artifact_id=artifact_id,
        artifact_class=artifact_class,
        phase_origin=phase,
        innovation_id=INNOV,
        ratifying_agent=AGENT,
        human0_signoff=GOVERNOR,
        operation=operation,
        ancestors=ancestors or [],
        timestamp=time.time(),
        metadata={},
        predecessor_digest=predecessor_digest,
    )


# ---------------------------------------------------------------------------
# T195-CPA-01..05 — Record creation and HMAC sealing
# ---------------------------------------------------------------------------


def test_T195_CPA_01_record_creation():
    """T195-CPA-01: ProvenanceRecord can be instantiated with required fields."""
    r = _make_record()
    assert r.artifact_id == "art-001"
    assert r.artifact_class == "invariant"
    assert r.hmac_digest == ""


def test_T195_CPA_02_seal_attaches_digest():
    """T195-CPA-02: seal() attaches a non-empty HMAC digest."""
    r = _make_record()
    r.seal(SECRET)
    assert len(r.hmac_digest) == 64


def test_T195_CPA_03_seal_is_idempotent():
    """T195-CPA-03: CPA-ATOMIC-0 — sealing twice produces same digest."""
    r = _make_record()
    r.seal(SECRET)
    first = r.hmac_digest
    r.seal(SECRET)
    assert r.hmac_digest == first


def test_T195_CPA_04_verify_valid_record():
    """T195-CPA-04: CPA-VERIFY-0 — sealed record verifies correctly."""
    r = _make_record()
    r.seal(SECRET)
    assert r.verify(SECRET) is True


def test_T195_CPA_05_verify_tampered_record_fails():
    """T195-CPA-05: CPA-VERIFY-0 — tampered record fails verification."""
    r = _make_record()
    r.seal(SECRET)
    r.ratifying_agent = "BadAgent"
    assert r.verify(SECRET) is False


# ---------------------------------------------------------------------------
# T195-CPA-06..10 — Trace completeness across all four artifact classes
# ---------------------------------------------------------------------------


def test_T195_CPA_06_trace_invariant(auditor):
    """T195-CPA-06: CPA-TRACE-0 — trace records invariant artifact."""
    rec = auditor.trace("INV-001", "invariant", PHASE, INNOV, AGENT)
    assert rec.artifact_class == "invariant"
    assert rec.hmac_digest != ""


def test_T195_CPA_07_trace_innovation(auditor):
    """T195-CPA-07: CPA-TRACE-0 — trace records innovation artifact."""
    rec = auditor.trace("INN-100", "innovation", PHASE, INNOV, AGENT)
    assert rec.artifact_class == "innovation"


def test_T195_CPA_08_trace_mutation(auditor):
    """T195-CPA-08: CPA-TRACE-0 — trace records mutation artifact."""
    rec = auditor.trace("MUT-001", "mutation", PHASE, INNOV, AGENT)
    assert rec.artifact_class == "mutation"


def test_T195_CPA_09_trace_ledger_entry(auditor):
    """T195-CPA-09: CPA-TRACE-0 — trace records ledger_entry artifact."""
    rec = auditor.trace("LED-001", "ledger_entry", PHASE, INNOV, AGENT)
    assert rec.artifact_class == "ledger_entry"


def test_T195_CPA_10_scope_invalid_class_raises(auditor):
    """T195-CPA-10: CPA-SCOPE-0 — invalid artifact class raises ProvenanceViolation."""
    with pytest.raises(ProvenanceViolation) as exc_info:
        auditor.trace("X-001", "unknown_class", PHASE, INNOV, AGENT)
    assert "CPA-SCOPE-0" in str(exc_info.value)


# ---------------------------------------------------------------------------
# T195-CPA-11..15 — HUMAN-0 immutability
# ---------------------------------------------------------------------------


def test_T195_CPA_11_human0_signoff_set_to_governor(auditor):
    """T195-CPA-11: CPA-HUMAN0-0 — human0_signoff is always set to GOVERNOR."""
    rec = auditor.trace("INV-002", "invariant", PHASE, INNOV, AGENT)
    assert rec.human0_signoff == GOVERNOR


def test_T195_CPA_12_human0_immutability_assertion_passes(auditor):
    """T195-CPA-12: CPA-HUMAN0-0 — assert_human0_immutability passes for valid record."""
    rec = auditor.trace("INV-003", "invariant", PHASE, INNOV, AGENT)
    auditor.assert_human0_immutability(rec)  # should not raise


def test_T195_CPA_13_human0_immutability_assertion_fails_on_tamper(auditor):
    """T195-CPA-13: CPA-HUMAN0-0 — tampered human0_signoff raises ProvenanceViolation."""
    rec = auditor.trace("INV-004", "invariant", PHASE, INNOV, AGENT)
    rec.human0_signoff = "EVIL AGENT"
    with pytest.raises(ProvenanceViolation) as exc_info:
        auditor.assert_human0_immutability(rec)
    assert "CPA-HUMAN0-0" in str(exc_info.value)


def test_T195_CPA_14_no_retroactive_modification(auditor):
    """T195-CPA-14: CPA-NOMOD-0 — corrections are new trace entries, not mutations."""
    rec1 = auditor.trace("INV-005", "invariant", PHASE, INNOV, AGENT, operation="CREATE")
    rec2 = auditor.trace("INV-005", "invariant", PHASE, INNOV, AGENT, operation="AMEND")
    chain = auditor._chains["INV-005"]
    assert len(chain.records) == 2
    assert chain.records[0].operation == "CREATE"
    assert chain.records[1].operation == "AMEND"


def test_T195_CPA_15_multiple_operations_form_chain(auditor):
    """T195-CPA-15: CPA-CHAIN-0 — multiple operations on same artifact form valid chain."""
    for op in ["CREATE", "AMEND", "VERIFY"]:
        auditor.trace("INV-006", "invariant", PHASE, INNOV, AGENT, operation=op)
    chain = auditor._chains["INV-006"]
    assert len(chain.records) == 3
    assert chain.verify_full(SECRET) is True


# ---------------------------------------------------------------------------
# T195-CPA-16..20 — Deterministic replay
# ---------------------------------------------------------------------------


def test_T195_CPA_16_chain_integrity_genesis(auditor):
    """T195-CPA-16: CPA-DETERM-0 — first record predecessor_digest is GENESIS_DIGEST."""
    rec = auditor.trace("MUT-002", "mutation", PHASE, INNOV, AGENT)
    assert rec.predecessor_digest == GENESIS_DIGEST


def test_T195_CPA_17_chain_links_predecessor_digest(auditor):
    """T195-CPA-17: CPA-CHAIN-0 — second record predecessor_digest equals first record hmac_digest."""
    r1 = auditor.trace("MUT-003", "mutation", PHASE, INNOV, AGENT)
    r2 = auditor.trace("MUT-003", "mutation", PHASE, INNOV, AGENT, operation="AMEND")
    assert r2.predecessor_digest == r1.hmac_digest


def test_T195_CPA_18_chain_verify_full_passes(auditor):
    """T195-CPA-18: CPA-DETERM-0 — verify_full passes on a valid chain."""
    for _ in range(3):
        auditor.trace("LED-002", "ledger_entry", PHASE, INNOV, AGENT)
    chain = auditor._chains["LED-002"]
    assert chain.verify_full(SECRET) is True


def test_T195_CPA_19_broken_chain_verify_fails():
    """T195-CPA-19: CPA-CHAIN-0 — chain with broken link fails verify_full."""
    chain = ProvenanceChain(artifact_id="X", artifact_class="invariant")
    r1 = _make_record(artifact_id="X", predecessor_digest=GENESIS_DIGEST)
    chain.append(r1, SECRET)
    r2 = _make_record(artifact_id="X", predecessor_digest=GENESIS_DIGEST)  # wrong predecessor
    r2.seal(SECRET)
    chain.records.append(r2)  # bypass append validation
    assert chain.verify_full(SECRET) is False


def test_T195_CPA_20_wrong_predecessor_raises_on_append():
    """T195-CPA-20: CPA-CHAIN-0 — appending record with wrong predecessor raises."""
    chain = ProvenanceChain(artifact_id="Y", artifact_class="invariant")
    r1 = _make_record(artifact_id="Y", predecessor_digest=GENESIS_DIGEST)
    chain.append(r1, SECRET)
    r2 = _make_record(artifact_id="Y", predecessor_digest="badhash" * 8)
    with pytest.raises(ProvenanceViolation) as exc_info:
        chain.append(r2, SECRET)
    assert "CPA-CHAIN-0" in str(exc_info.value)


# ---------------------------------------------------------------------------
# T195-CPA-21..25 — Audit ledger emission
# ---------------------------------------------------------------------------


def test_T195_CPA_21_trace_writes_to_ledger(auditor):
    """T195-CPA-21: CPA-AUDIT-0 — trace operation writes to ledger."""
    before = auditor.ledger_path.stat().st_size if auditor.ledger_path.exists() else 0
    auditor.trace("INN-101", "innovation", PHASE, INNOV, AGENT)
    after = auditor.ledger_path.stat().st_size
    assert after > before


def test_T195_CPA_22_verify_writes_to_ledger(auditor):
    """T195-CPA-22: CPA-AUDIT-0 — verify operation writes to ledger."""
    auditor.trace("INN-102", "innovation", PHASE, INNOV, AGENT)
    before = auditor.ledger_path.stat().st_size
    auditor.verify("INN-102")
    after = auditor.ledger_path.stat().st_size
    assert after > before


def test_T195_CPA_23_ledger_entries_are_valid_jsonl(auditor):
    """T195-CPA-23: CPA-IMMUT-0 — ledger is valid JSONL."""
    auditor.trace("INN-103", "innovation", PHASE, INNOV, AGENT)
    lines = auditor.ledger_path.read_text().strip().splitlines()
    for line in lines:
        entry = json.loads(line)
        assert "event" in entry


def test_T195_CPA_24_export_writes_to_ledger(auditor):
    """T195-CPA-24: CPA-AUDIT-0 — export operation writes to ledger."""
    auditor.trace("LED-003", "ledger_entry", PHASE, INNOV, AGENT)
    before = auditor.ledger_path.stat().st_size
    auditor.export_bundle("LED-003")
    after = auditor.ledger_path.stat().st_size
    assert after > before


def test_T195_CPA_25_ledger_event_types_present(auditor):
    """T195-CPA-25: CPA-AUDIT-0 — TRACE, VERIFY, EXPORT events all appear in ledger."""
    auditor.trace("LED-004", "ledger_entry", PHASE, INNOV, AGENT)
    auditor.verify("LED-004")
    auditor.export_bundle("LED-004")
    lines = auditor.ledger_path.read_text().strip().splitlines()
    events = {json.loads(l)["event"] for l in lines}
    assert {"TRACE", "VERIFY", "EXPORT"}.issubset(events)


# ---------------------------------------------------------------------------
# T195-CPA-26..30 — Bundle export, signature, violation raises
# ---------------------------------------------------------------------------


def test_T195_CPA_26_export_bundle_returns_bundle(auditor):
    """T195-CPA-26: CPA-DETERM-0 — export_bundle returns ProvenanceBundle."""
    auditor.trace("INN-104", "innovation", PHASE, INNOV, AGENT)
    bundle = auditor.export_bundle("INN-104")
    assert isinstance(bundle, ProvenanceBundle)
    assert bundle.artifact_id == "INN-104"


def test_T195_CPA_27_bundle_hmac_is_valid(auditor):
    """T195-CPA-27: CPA-VERIFY-0 — exported bundle HMAC verifies correctly."""
    auditor.trace("INN-105", "innovation", PHASE, INNOV, AGENT)
    bundle = auditor.export_bundle("INN-105")
    assert auditor.verify_bundle(bundle) is True


def test_T195_CPA_28_tampered_bundle_fails_verify(auditor):
    """T195-CPA-28: CPA-VERIFY-0 — tampered bundle fails verification."""
    auditor.trace("INN-106", "innovation", PHASE, INNOV, AGENT)
    bundle = auditor.export_bundle("INN-106")
    bundle.chain_length = 999  # tamper
    assert auditor.verify_bundle(bundle) is False


def test_T195_CPA_29_export_nonexistent_artifact_raises(auditor):
    """T195-CPA-29: CPA-TRACE-0 — exporting unknown artifact raises ProvenanceViolation."""
    with pytest.raises(ProvenanceViolation) as exc_info:
        auditor.export_bundle("DOES-NOT-EXIST")
    assert "CPA-TRACE-0" in str(exc_info.value)


def test_T195_CPA_30_summary_covers_all_artifact_classes(auditor):
    """T195-CPA-30: CPA-SCOPE-0 — summary reports all four artifact classes."""
    for cls in ARTIFACT_CLASSES:
        auditor.trace(f"ART-{cls}", cls, PHASE, INNOV, AGENT)
    s = auditor.summary()
    for cls in ARTIFACT_CLASSES:
        assert cls in s["artifact_class_counts"]
    assert s["total_artifacts"] >= 4
    assert s["governor"] == GOVERNOR
