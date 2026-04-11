# SPDX-License-Identifier: Apache-2.0
"""Phase 128 — INNOV-38 ACSA test suite.

Naming convention: T128-ACSA-NN
All 25 tests must pass (25/25) for phase acceptance.

Environment variables (injected by conftest autouse fixture):
  ACSA_HMAC_SECRET — hex-encoded 32-byte secret
"""
from __future__ import annotations

import json
import os
import hashlib
import hmac
from dataclasses import dataclass
from pathlib import Path

import pytest

from runtime.innovations30.constitutional_self_amendment import (
    ACSAEngine,
    ACSAGateVerdict,
    BlockedAmendment,
    ChainIntegrityError,
    ConstitutionalPatch,
    DeterminismError,
    DuplicatePatchError,
    HumanGateBlockError,
    PatchStatus,
    acsa_gate_check,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SECRET = bytes.fromhex(os.environ.get("ACSA_HMAC_SECRET", "a" * 64))


@dataclass
class _FakeProposal:
    proposal_id: str
    invariant_target: str
    classification: str
    patch_description: str
    human0_ack: str = ""


def _engine(tmp_path: Path) -> ACSAEngine:
    return ACSAEngine(
        hmac_secret=SECRET,
        ledger_path=tmp_path / "acsa_ledger.jsonl",
        constitution_path=tmp_path / "constitution.json",
    )


# ---------------------------------------------------------------------------
# T128-ACSA-01: Module imports without error
# ---------------------------------------------------------------------------
def test_T128_ACSA_01_module_import():
    from runtime.innovations30 import constitutional_self_amendment  # noqa: F401
    assert True


# ---------------------------------------------------------------------------
# T128-ACSA-02: Engine instantiates with clean state
# ---------------------------------------------------------------------------
def test_T128_ACSA_02_engine_init(tmp_path):
    eng = _engine(tmp_path)
    assert eng.applied_count() == 0


# ---------------------------------------------------------------------------
# T128-ACSA-03: ADVISORY proposal → APPLIED record
# ---------------------------------------------------------------------------
def test_T128_ACSA_03_advisory_applied(tmp_path):
    eng = _engine(tmp_path)
    prop = _FakeProposal("PROP-001", "ACSA-0", "ADVISORY", "Tighten null-check on patch_text.")
    rec = eng.apply_proposal(prop)
    assert rec.status == PatchStatus.APPLIED.value
    assert rec.proposal_id == "PROP-001"


# ---------------------------------------------------------------------------
# T128-ACSA-04: WARNING proposal → APPLIED record
# ---------------------------------------------------------------------------
def test_T128_ACSA_04_warning_applied(tmp_path):
    eng = _engine(tmp_path)
    prop = _FakeProposal("PROP-002", "GRRP-0", "WARNING", "Add pre-check for empty finding list.")
    rec = eng.apply_proposal(prop)
    assert rec.status == PatchStatus.APPLIED.value


# ---------------------------------------------------------------------------
# T128-ACSA-05: CRITICAL without human0_ack → BLOCKED (ACSA-HUMAN0-0)
# ---------------------------------------------------------------------------
def test_T128_ACSA_05_critical_no_ack_blocked(tmp_path):
    eng = _engine(tmp_path)
    prop = _FakeProposal("PROP-003", "REDTEAM-HALT-0", "CRITICAL", "Remove halt gate.", human0_ack="")
    rec = eng.apply_proposal(prop)
    assert rec.status == PatchStatus.BLOCKED.value


# ---------------------------------------------------------------------------
# T128-ACSA-06: BREACH without human0_ack → BLOCKED (ACSA-HUMAN0-0)
# ---------------------------------------------------------------------------
def test_T128_ACSA_06_breach_no_ack_blocked(tmp_path):
    eng = _engine(tmp_path)
    prop = _FakeProposal("PROP-004", "CEL-0", "BREACH", "Bypass CEL gate.", human0_ack="")
    rec = eng.apply_proposal(prop)
    assert rec.status == PatchStatus.BLOCKED.value


# ---------------------------------------------------------------------------
# T128-ACSA-07: CRITICAL with valid human0_ack → APPLIED
# ---------------------------------------------------------------------------
def test_T128_ACSA_07_critical_with_ack_applied(tmp_path):
    eng = _engine(tmp_path)
    prop = _FakeProposal(
        "PROP-005", "REDTEAM-HALT-0", "CRITICAL",
        "Harden halt gate with timeout.", human0_ack="HUMAN0-ACK-VALID-TOKEN-001"
    )
    rec = eng.apply_proposal(prop)
    assert rec.status == PatchStatus.APPLIED.value


# ---------------------------------------------------------------------------
# T128-ACSA-08: BREACH with valid human0_ack → APPLIED
# ---------------------------------------------------------------------------
def test_T128_ACSA_08_breach_with_ack_applied(tmp_path):
    eng = _engine(tmp_path)
    prop = _FakeProposal(
        "PROP-006", "CEL-0", "BREACH",
        "Restore CEL step ordering constraint.", human0_ack="HUMAN0-ACK-VALID-TOKEN-002"
    )
    rec = eng.apply_proposal(prop)
    assert rec.status == PatchStatus.APPLIED.value


# ---------------------------------------------------------------------------
# T128-ACSA-09: Duplicate proposal → BLOCKED (ACSA-REPLAY-0)
# ---------------------------------------------------------------------------
def test_T128_ACSA_09_duplicate_blocked(tmp_path):
    eng = _engine(tmp_path)
    prop = _FakeProposal("PROP-007", "ACSA-0", "ADVISORY", "Patch once only.")
    rec1 = eng.apply_proposal(prop)
    assert rec1.status == PatchStatus.APPLIED.value
    rec2 = eng.apply_proposal(prop)
    assert rec2.status == PatchStatus.BLOCKED.value


# ---------------------------------------------------------------------------
# T128-ACSA-10: Empty patch_description → BLOCKED (ACSA-GATE-0 malformed)
# ---------------------------------------------------------------------------
def test_T128_ACSA_10_empty_patch_blocked(tmp_path):
    eng = _engine(tmp_path)
    prop = _FakeProposal("PROP-008", "ACSA-0", "ADVISORY", "   ")
    rec = eng.apply_proposal(prop)
    assert rec.status == PatchStatus.BLOCKED.value


# ---------------------------------------------------------------------------
# T128-ACSA-11: Applied record has non-empty patch_id
# ---------------------------------------------------------------------------
def test_T128_ACSA_11_applied_has_patch_id(tmp_path):
    eng = _engine(tmp_path)
    prop = _FakeProposal("PROP-009", "ACSA-0", "ADVISORY", "Patch description.")
    rec = eng.apply_proposal(prop)
    assert rec.patch_id.startswith("PATCH-PROP-009")


# ---------------------------------------------------------------------------
# T128-ACSA-12: Blocked record has non-empty blocked_id
# ---------------------------------------------------------------------------
def test_T128_ACSA_12_blocked_has_blocked_id(tmp_path):
    eng = _engine(tmp_path)
    prop = _FakeProposal("PROP-010", "X-0", "CRITICAL", "No ack.")
    rec = eng.apply_proposal(prop)
    assert rec.blocked_id.startswith("BLOCKED-PROP-010")


# ---------------------------------------------------------------------------
# T128-ACSA-13: patch_digest is deterministic (ACSA-DETERM-0)
# ---------------------------------------------------------------------------
def test_T128_ACSA_13_patch_digest_deterministic():
    patch = ConstitutionalPatch(
        patch_id="P1", proposal_id="PROP-A", invariant_target="X-0",
        classification="ADVISORY", patch_text="Some fix."
    )
    d1 = patch.compute_patch_digest()
    d2 = patch.compute_patch_digest()
    assert d1 == d2
    assert len(d1) == 64  # SHA-256 hex


# ---------------------------------------------------------------------------
# T128-ACSA-14: patch_digest changes when patch_text changes (ACSA-DETERM-0)
# ---------------------------------------------------------------------------
def test_T128_ACSA_14_patch_digest_varies_with_text():
    p1 = ConstitutionalPatch("P1", "PROP-A", "X-0", "ADVISORY", "Fix A.")
    p2 = ConstitutionalPatch("P1", "PROP-A", "X-0", "ADVISORY", "Fix B.")
    assert p1.compute_patch_digest() != p2.compute_patch_digest()


# ---------------------------------------------------------------------------
# T128-ACSA-15: Ledger written to disk after apply
# ---------------------------------------------------------------------------
def test_T128_ACSA_15_ledger_written(tmp_path):
    eng = _engine(tmp_path)
    prop = _FakeProposal("PROP-011", "ACSA-0", "ADVISORY", "Write to ledger.")
    eng.apply_proposal(prop)
    assert (tmp_path / "acsa_ledger.jsonl").exists()


# ---------------------------------------------------------------------------
# T128-ACSA-16: Ledger line is valid JSON
# ---------------------------------------------------------------------------
def test_T128_ACSA_16_ledger_valid_json(tmp_path):
    eng = _engine(tmp_path)
    prop = _FakeProposal("PROP-012", "ACSA-0", "ADVISORY", "JSON line check.")
    eng.apply_proposal(prop)
    lines = (tmp_path / "acsa_ledger.jsonl").read_text().splitlines()
    for line in lines:
        json.loads(line)  # must not raise


# ---------------------------------------------------------------------------
# T128-ACSA-17: Chain is intact after multiple proposals (ACSA-CHAIN-0)
# ---------------------------------------------------------------------------
def test_T128_ACSA_17_chain_intact(tmp_path):
    eng = _engine(tmp_path)
    for i in range(5):
        prop = _FakeProposal(f"PROP-C{i}", "ACSA-0", "ADVISORY", f"Patch {i}.")
        eng.apply_proposal(prop)
    assert eng.verify_chain() is True


# ---------------------------------------------------------------------------
# T128-ACSA-18: First record carries prev_digest="genesis"
# ---------------------------------------------------------------------------
def test_T128_ACSA_18_first_record_genesis(tmp_path):
    eng = _engine(tmp_path)
    prop = _FakeProposal("PROP-013", "ACSA-0", "ADVISORY", "Genesis check.")
    eng.apply_proposal(prop)
    line = (tmp_path / "acsa_ledger.jsonl").read_text().splitlines()[0]
    rec = json.loads(line)
    assert rec["prev_digest"] == "genesis"


# ---------------------------------------------------------------------------
# T128-ACSA-19: Subsequent records chain to previous record_digest
# ---------------------------------------------------------------------------
def test_T128_ACSA_19_chain_links(tmp_path):
    eng = _engine(tmp_path)
    for i in range(3):
        prop = _FakeProposal(f"PROP-D{i}", "ACSA-0", "ADVISORY", f"Patch {i}.")
        eng.apply_proposal(prop)
    lines = (tmp_path / "acsa_ledger.jsonl").read_text().splitlines()
    recs = [json.loads(l) for l in lines]
    for i in range(1, len(recs)):
        assert recs[i]["prev_digest"] == recs[i - 1]["record_digest"]


# ---------------------------------------------------------------------------
# T128-ACSA-20: Constitution JSON updated after APPLIED patch
# ---------------------------------------------------------------------------
def test_T128_ACSA_20_constitution_updated(tmp_path):
    eng = _engine(tmp_path)
    prop = _FakeProposal("PROP-014", "ACSA-0", "ADVISORY", "Constitution update test.")
    eng.apply_proposal(prop)
    c = json.loads((tmp_path / "constitution.json").read_text())
    assert c["patches_applied"] == 1
    assert c["patches"][0]["proposal_id"] == "PROP-014"


# ---------------------------------------------------------------------------
# T128-ACSA-21: Engine reloads applied_ids from ledger on restart (ACSA-REPLAY-0)
# ---------------------------------------------------------------------------
def test_T128_ACSA_21_reload_applied_ids(tmp_path):
    eng = _engine(tmp_path)
    prop = _FakeProposal("PROP-015", "ACSA-0", "ADVISORY", "Persist ID test.")
    eng.apply_proposal(prop)
    # New engine instance — same ledger path
    eng2 = ACSAEngine(
        hmac_secret=SECRET,
        ledger_path=tmp_path / "acsa_ledger.jsonl",
        constitution_path=tmp_path / "constitution.json",
    )
    assert "PROP-015" in eng2._applied_ids


# ---------------------------------------------------------------------------
# T128-ACSA-22: verify_chain raises ChainIntegrityError on tampered ledger
# ---------------------------------------------------------------------------
def test_T128_ACSA_22_chain_tamper_detected(tmp_path):
    eng = _engine(tmp_path)
    for i in range(2):
        prop = _FakeProposal(f"PROP-E{i}", "ACSA-0", "ADVISORY", f"Patch {i}.")
        eng.apply_proposal(prop)
    # Tamper second line
    ledger = tmp_path / "acsa_ledger.jsonl"
    lines = ledger.read_text().splitlines()
    rec = json.loads(lines[1])
    rec["prev_digest"] = "tampered"
    lines[1] = json.dumps(rec)
    ledger.write_text("\n".join(lines) + "\n")
    eng2 = ACSAEngine(
        hmac_secret=SECRET,
        ledger_path=ledger,
        constitution_path=tmp_path / "constitution.json",
    )
    with pytest.raises(ChainIntegrityError):
        eng2.verify_chain()


# ---------------------------------------------------------------------------
# T128-ACSA-23: applied_count increments correctly
# ---------------------------------------------------------------------------
def test_T128_ACSA_23_applied_count(tmp_path):
    eng = _engine(tmp_path)
    for i in range(4):
        prop = _FakeProposal(f"PROP-F{i}", "ACSA-0", "ADVISORY", f"Patch {i}.")
        eng.apply_proposal(prop)
    assert eng.applied_count() == 4


# ---------------------------------------------------------------------------
# T128-ACSA-24: Stateless gate check — PASS for valid ADVISORY
# ---------------------------------------------------------------------------
def test_T128_ACSA_24_stateless_gate_pass():
    verdict, reason = acsa_gate_check(
        "PROP-NEW", "ADVISORY", "", "Valid patch.", applied_ids=set()
    )
    assert verdict == ACSAGateVerdict.PASS
    assert reason == ""


# ---------------------------------------------------------------------------
# T128-ACSA-25: Stateless gate check — BLOCKED_HUMAN_GATE for CRITICAL no ack
# ---------------------------------------------------------------------------
def test_T128_ACSA_25_stateless_gate_human_gate():
    verdict, reason = acsa_gate_check(
        "PROP-NEW", "CRITICAL", "", "Critical patch.", applied_ids=set()
    )
    assert verdict == ACSAGateVerdict.BLOCKED_HUMAN_GATE
    assert "ACSA-HUMAN0-0" in reason
