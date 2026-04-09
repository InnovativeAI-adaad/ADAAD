# SPDX-License-Identifier: Apache-2.0
"""Phase 130 — INNOV-40 Cross-Epoch Agent Learning Transfer (CELT) test suite.

Naming convention: T130-CELT-NN
All 30 tests must pass (30/30) for phase acceptance.
"""
from __future__ import annotations

import json
import os
import hashlib
from pathlib import Path

import pytest

from runtime.innovations30.cross_epoch_transfer import (
    CELTEngine,
    ChainError,
    EpochBoundaryError,
    LearningBundle,
    MergeError,
    MergeResult,
    ProfileSnapshot,
    QuarantineError,
    SanitizationError,
    VerificationError,
    merge_profile,
    sanitise_profile,
    snapshot_from_profile,
)

# ────────────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────────────

SECRET = bytes.fromhex(os.environ.get("ACSA_HMAC_SECRET", "c" * 64))

_SNAP_A = ProfileSnapshot(
    agent_id="ARCH-1",
    target_type_counts={"refactor": 10, "bugfix": 3},
    strategy_counts={"safe": 8, "aggressive": 2},
    risk_scores=[0.1, 0.2, 0.3],
    fitness_deltas=[0.05, 0.10],
    epochs_active=5,
)

_SNAP_B = ProfileSnapshot(
    agent_id="ARCH-1",
    target_type_counts={"refactor": 5, "feature": 2},
    strategy_counts={"safe": 4, "minimal": 1},
    risk_scores=[0.15, 0.25],
    fitness_deltas=[0.08],
    epochs_active=3,
)


def _engine(tmp_path: Path, epoch: str = "EPOCH-99") -> CELTEngine:
    return CELTEngine(
        hmac_secret=SECRET,
        instance_id="INST-TEST",
        current_epoch=epoch,
        ledger_path=tmp_path / "celt_ledger.jsonl",
    )


def _signed_bundle(snap: ProfileSnapshot, source_epoch: str = "EPOCH-01",
                   bundle_id: str = "BNDL-001") -> LearningBundle:
    b = LearningBundle(
        bundle_id=bundle_id,
        agent_id=snap.agent_id,
        source_instance="INST-SOURCE",
        source_epoch=source_epoch,
        profile_snapshot=snap.to_dict(),
    )
    b.sign(SECRET)
    return b


# ────────────────────────────────────────────────────────────────────────────
# T130-CELT-01: Module imports cleanly
# ────────────────────────────────────────────────────────────────────────────
def test_T130_CELT_01_module_import():
    from runtime.innovations30 import cross_epoch_transfer  # noqa: F401
    assert True


# ────────────────────────────────────────────────────────────────────────────
# T130-CELT-02: Engine initialises with zero records
# ────────────────────────────────────────────────────────────────────────────
def test_T130_CELT_02_engine_init(tmp_path):
    eng = _engine(tmp_path)
    assert eng.record_count() == 0


# ────────────────────────────────────────────────────────────────────────────
# T130-CELT-03: export_bundle produces signed bundle
# ────────────────────────────────────────────────────────────────────────────
def test_T130_CELT_03_export_signed(tmp_path):
    eng = _engine(tmp_path, epoch="EPOCH-10")
    eng.register_profile(_SNAP_A)
    bundle = eng.export_bundle("ARCH-1", "BNDL-EXP-001")
    assert bundle.hmac_digest != ""
    assert bundle.bundle_digest != ""


# ────────────────────────────────────────────────────────────────────────────
# T130-CELT-04: bundle_digest is deterministic (CELT-DETERM-0)
# ────────────────────────────────────────────────────────────────────────────
def test_T130_CELT_04_digest_deterministic():
    b1 = _signed_bundle(_SNAP_A, "EPOCH-01", "BNDL-D1")
    b2 = _signed_bundle(_SNAP_A, "EPOCH-01", "BNDL-D1")
    assert b1.bundle_digest == b2.bundle_digest


# ────────────────────────────────────────────────────────────────────────────
# T130-CELT-05: bundle_digest changes with different profile (CELT-DETERM-0)
# ────────────────────────────────────────────────────────────────────────────
def test_T130_CELT_05_digest_varies_with_profile():
    b1 = _signed_bundle(_SNAP_A, "EPOCH-01", "BNDL-V1")
    b2 = _signed_bundle(_SNAP_B, "EPOCH-01", "BNDL-V1")
    assert b1.bundle_digest != b2.bundle_digest


# ────────────────────────────────────────────────────────────────────────────
# T130-CELT-06: verify passes on untampered bundle (CELT-VERIFY-0)
# ────────────────────────────────────────────────────────────────────────────
def test_T130_CELT_06_verify_passes():
    b = _signed_bundle(_SNAP_A)
    b.verify(SECRET)  # must not raise


# ────────────────────────────────────────────────────────────────────────────
# T130-CELT-07: verify raises on tampered hmac_digest (CELT-VERIFY-0)
# ────────────────────────────────────────────────────────────────────────────
def test_T130_CELT_07_verify_tampered_hmac():
    b = _signed_bundle(_SNAP_A)
    b.hmac_digest = "000000000000000000000000"
    with pytest.raises(VerificationError):
        b.verify(SECRET)


# ────────────────────────────────────────────────────────────────────────────
# T130-CELT-08: verify raises on empty hmac_digest (CELT-VERIFY-0)
# ────────────────────────────────────────────────────────────────────────────
def test_T130_CELT_08_verify_unsigned():
    b = LearningBundle("BNDL-X", "ARCH-1", "INST-A", "EPOCH-01", _SNAP_A.to_dict())
    with pytest.raises(VerificationError):
        b.verify(SECRET)


# ────────────────────────────────────────────────────────────────────────────
# T130-CELT-09: sanitise_profile succeeds on valid snapshot
# ────────────────────────────────────────────────────────────────────────────
def test_T130_CELT_09_sanitise_valid():
    snap = sanitise_profile(_SNAP_A.to_dict())
    assert snap.agent_id == "ARCH-1"


# ────────────────────────────────────────────────────────────────────────────
# T130-CELT-10: sanitise_profile raises on missing field (CELT-SANITIZE-0)
# ────────────────────────────────────────────────────────────────────────────
def test_T130_CELT_10_sanitise_missing_field():
    bad = _SNAP_A.to_dict()
    del bad["epochs_active"]
    with pytest.raises(SanitizationError):
        sanitise_profile(bad)


# ────────────────────────────────────────────────────────────────────────────
# T130-CELT-11: sanitise_profile raises on non-list risk_scores (CELT-SANITIZE-0)
# ────────────────────────────────────────────────────────────────────────────
def test_T130_CELT_11_sanitise_bad_list_type():
    bad = _SNAP_A.to_dict()
    bad["risk_scores"] = "not-a-list"
    with pytest.raises(SanitizationError):
        sanitise_profile(bad)


# ────────────────────────────────────────────────────────────────────────────
# T130-CELT-12: sanitise_profile raises on negative count (CELT-SANITIZE-0)
# ────────────────────────────────────────────────────────────────────────────
def test_T130_CELT_12_sanitise_negative_count():
    bad = _SNAP_A.to_dict()
    bad["target_type_counts"]["refactor"] = -1
    with pytest.raises(SanitizationError):
        sanitise_profile(bad)


# ────────────────────────────────────────────────────────────────────────────
# T130-CELT-13: merge_profile is additive (CELT-MERGE-0)
# ────────────────────────────────────────────────────────────────────────────
def test_T130_CELT_13_merge_additive():
    local = ProfileSnapshot("ARCH-1", {"refactor": 10}, {"safe": 8}, [0.1], [0.05], 5)
    incoming = ProfileSnapshot("ARCH-1", {"refactor": 5, "feature": 2}, {"safe": 4}, [0.2], [0.08], 3)
    updated, result = merge_profile(local, incoming)
    assert updated.target_type_counts["refactor"] == 15
    assert updated.target_type_counts["feature"] == 2
    assert updated.strategy_counts["safe"] == 12
    assert updated.epochs_active == 8


# ────────────────────────────────────────────────────────────────────────────
# T130-CELT-14: merge_profile sorts lists canonically (CELT-DETERM-0)
# ────────────────────────────────────────────────────────────────────────────
def test_T130_CELT_14_merge_sorted_lists():
    local = ProfileSnapshot("ARCH-1", {}, {}, [0.5], [0.1], 1)
    incoming = ProfileSnapshot("ARCH-1", {}, {}, [0.1], [0.05], 1)
    updated, _ = merge_profile(local, incoming)
    assert updated.risk_scores == sorted(updated.risk_scores)
    assert updated.fitness_deltas == sorted(updated.fitness_deltas)


# ────────────────────────────────────────────────────────────────────────────
# T130-CELT-15: merge_profile raises on agent_id mismatch (CELT-MERGE-0)
# ────────────────────────────────────────────────────────────────────────────
def test_T130_CELT_15_merge_agent_mismatch():
    local = ProfileSnapshot("ARCH-1", {}, {}, [], [], 0)
    incoming = ProfileSnapshot("DREAM-1", {}, {}, [], [], 0)
    with pytest.raises(MergeError):
        merge_profile(local, incoming)


# ────────────────────────────────────────────────────────────────────────────
# T130-CELT-16: successful import returns updated profile (CELT-0)
# ────────────────────────────────────────────────────────────────────────────
def test_T130_CELT_16_import_success(tmp_path):
    eng = _engine(tmp_path, epoch="EPOCH-99")
    bundle = _signed_bundle(_SNAP_A, "EPOCH-01")
    updated, result = eng.celt_import_gate(bundle, target_epoch="EPOCH-99")
    assert updated.agent_id == "ARCH-1"
    assert result.added_epochs == 5


# ────────────────────────────────────────────────────────────────────────────
# T130-CELT-17: import merges into existing local profile (CELT-MERGE-0)
# ────────────────────────────────────────────────────────────────────────────
def test_T130_CELT_17_import_merges_existing(tmp_path):
    eng = _engine(tmp_path, epoch="EPOCH-99")
    eng.register_profile(ProfileSnapshot("ARCH-1", {"refactor": 5}, {}, [], [], 2))
    bundle = _signed_bundle(_SNAP_A, "EPOCH-01")
    updated, _ = eng.celt_import_gate(bundle, target_epoch="EPOCH-99")
    assert updated.target_type_counts["refactor"] == 15   # 5 local + 10 incoming


# ────────────────────────────────────────────────────────────────────────────
# T130-CELT-18: CELT-EPOCH-0 — same-epoch transfer raises EpochBoundaryError
# ────────────────────────────────────────────────────────────────────────────
def test_T130_CELT_18_same_epoch_blocked(tmp_path):
    eng = _engine(tmp_path, epoch="EPOCH-99")
    bundle = _signed_bundle(_SNAP_A, source_epoch="EPOCH-99")
    with pytest.raises(EpochBoundaryError):
        eng.celt_import_gate(bundle, target_epoch="EPOCH-99")


# ────────────────────────────────────────────────────────────────────────────
# T130-CELT-19: CELT-QUARANTINE-0 — quarantined bundle raises QuarantineError
# ────────────────────────────────────────────────────────────────────────────
def test_T130_CELT_19_quarantined_blocked(tmp_path):
    eng = _engine(tmp_path, epoch="EPOCH-99")
    bundle = _signed_bundle(_SNAP_A, "EPOCH-01", "BNDL-Q")
    eng.quarantine_bundle("BNDL-Q")
    with pytest.raises(QuarantineError):
        eng.celt_import_gate(bundle, target_epoch="EPOCH-99")


# ────────────────────────────────────────────────────────────────────────────
# T130-CELT-20: quarantine_bundle makes is_quarantined return True
# ────────────────────────────────────────────────────────────────────────────
def test_T130_CELT_20_is_quarantined(tmp_path):
    eng = _engine(tmp_path)
    eng.quarantine_bundle("BNDL-QQ")
    assert eng.is_quarantined("BNDL-QQ") is True
    assert eng.is_quarantined("BNDL-NOT") is False


# ────────────────────────────────────────────────────────────────────────────
# T130-CELT-21: CELT-VERIFY-0 — tampered bundle raises VerificationError on import
# ────────────────────────────────────────────────────────────────────────────
def test_T130_CELT_21_tampered_import_rejected(tmp_path):
    eng = _engine(tmp_path, epoch="EPOCH-99")
    bundle = _signed_bundle(_SNAP_A, "EPOCH-01")
    bundle.hmac_digest = "000000000000000000000000"
    with pytest.raises(VerificationError):
        eng.celt_import_gate(bundle, target_epoch="EPOCH-99")


# ────────────────────────────────────────────────────────────────────────────
# T130-CELT-22: rejected import still appended to ledger (CELT-CHAIN-0)
# ────────────────────────────────────────────────────────────────────────────
def test_T130_CELT_22_rejected_still_logged(tmp_path):
    eng = _engine(tmp_path, epoch="EPOCH-99")
    bundle = _signed_bundle(_SNAP_A, "EPOCH-99")  # same epoch → rejected
    with pytest.raises(EpochBoundaryError):
        eng.celt_import_gate(bundle, target_epoch="EPOCH-99")
    assert eng.record_count() == 1
    assert (tmp_path / "celt_ledger.jsonl").exists()


# ────────────────────────────────────────────────────────────────────────────
# T130-CELT-23: ledger line is valid JSON (CELT-CHAIN-0)
# ────────────────────────────────────────────────────────────────────────────
def test_T130_CELT_23_ledger_valid_json(tmp_path):
    eng = _engine(tmp_path, epoch="EPOCH-99")
    bundle = _signed_bundle(_SNAP_A, "EPOCH-01")
    eng.celt_import_gate(bundle, target_epoch="EPOCH-99")
    for line in (tmp_path / "celt_ledger.jsonl").read_text().splitlines():
        json.loads(line)


# ────────────────────────────────────────────────────────────────────────────
# T130-CELT-24: first ledger record has prev_digest="genesis" (CELT-CHAIN-0)
# ────────────────────────────────────────────────────────────────────────────
def test_T130_CELT_24_first_record_genesis(tmp_path):
    eng = _engine(tmp_path, epoch="EPOCH-99")
    bundle = _signed_bundle(_SNAP_A, "EPOCH-01")
    eng.celt_import_gate(bundle, target_epoch="EPOCH-99")
    line = (tmp_path / "celt_ledger.jsonl").read_text().splitlines()[0]
    rec = json.loads(line)
    assert rec["prev_digest"] == "genesis"


# ────────────────────────────────────────────────────────────────────────────
# T130-CELT-25: chain links correctly across multiple imports (CELT-CHAIN-0)
# ────────────────────────────────────────────────────────────────────────────
def test_T130_CELT_25_chain_links(tmp_path):
    eng = _engine(tmp_path, epoch="EPOCH-99")
    for i in range(3):
        b = _signed_bundle(_SNAP_A, f"EPOCH-0{i}", f"BNDL-CL-{i}")
        eng.celt_import_gate(b, target_epoch="EPOCH-99")
    lines = (tmp_path / "celt_ledger.jsonl").read_text().splitlines()
    recs = [json.loads(l) for l in lines]
    for i in range(1, len(recs)):
        assert recs[i]["prev_digest"] == recs[i-1]["record_digest"]


# ────────────────────────────────────────────────────────────────────────────
# T130-CELT-26: verify_chain passes on intact ledger (CELT-CHAIN-0)
# ────────────────────────────────────────────────────────────────────────────
def test_T130_CELT_26_verify_chain_intact(tmp_path):
    eng = _engine(tmp_path, epoch="EPOCH-99")
    for i in range(3):
        b = _signed_bundle(_SNAP_A, f"EPOCH-{i:02d}", f"BNDL-VC-{i}")
        eng.celt_import_gate(b, target_epoch="EPOCH-99")
    assert eng.verify_chain() is True


# ────────────────────────────────────────────────────────────────────────────
# T130-CELT-27: verify_chain raises on tampered ledger (CELT-CHAIN-0)
# ────────────────────────────────────────────────────────────────────────────
def test_T130_CELT_27_verify_chain_tamper(tmp_path):
    eng = _engine(tmp_path, epoch="EPOCH-99")
    for i in range(2):
        b = _signed_bundle(_SNAP_A, f"EPOCH-0{i}", f"BNDL-TAM-{i}")
        eng.celt_import_gate(b, target_epoch="EPOCH-99")
    ledger = tmp_path / "celt_ledger.jsonl"
    lines = ledger.read_text().splitlines()
    rec = json.loads(lines[1])
    rec["prev_digest"] = "tampered"
    lines[1] = json.dumps(rec)
    ledger.write_text("\n".join(lines) + "\n")
    eng2 = CELTEngine(SECRET, "INST-TEST", "EPOCH-99", ledger)
    with pytest.raises(ChainError):
        eng2.verify_chain()


# ────────────────────────────────────────────────────────────────────────────
# T130-CELT-28: snapshot_from_profile converts ERS profile correctly
# ────────────────────────────────────────────────────────────────────────────
def test_T130_CELT_28_snapshot_from_profile():
    from runtime.innovations30.emergent_roles import AgentBehaviorProfile
    profile = AgentBehaviorProfile(agent_id="BEAST-1")
    profile.record_action("refactor", "safe", 0.2, 0.05)
    profile.record_action("bugfix",   "safe", 0.1, 0.03)
    snap = snapshot_from_profile(profile)
    assert snap.agent_id == "BEAST-1"
    assert snap.target_type_counts["refactor"] == 1
    assert snap.epochs_active == 2


# ────────────────────────────────────────────────────────────────────────────
# T130-CELT-29: engine reloads record_counter from ledger on restart
# ────────────────────────────────────────────────────────────────────────────
def test_T130_CELT_29_reload_record_counter(tmp_path):
    ledger = tmp_path / "celt_ledger.jsonl"
    eng = CELTEngine(SECRET, "INST-TEST", "EPOCH-99", ledger)
    for i in range(3):
        b = _signed_bundle(_SNAP_A, f"EPOCH-{i:02d}", f"BNDL-RL-{i}")
        eng.celt_import_gate(b, target_epoch="EPOCH-99")
    eng2 = CELTEngine(SECRET, "INST-TEST", "EPOCH-99", ledger)
    assert eng2.record_count() == 3


# ────────────────────────────────────────────────────────────────────────────
# T130-CELT-30: MergeResult carries non-empty merge_digest
# ────────────────────────────────────────────────────────────────────────────
def test_T130_CELT_30_merge_result_digest(tmp_path):
    eng = _engine(tmp_path, epoch="EPOCH-99")
    bundle = _signed_bundle(_SNAP_A, "EPOCH-01")
    _, result = eng.celt_import_gate(bundle, target_epoch="EPOCH-99")
    assert result.merge_digest != ""
    assert len(result.merge_digest) == 24
