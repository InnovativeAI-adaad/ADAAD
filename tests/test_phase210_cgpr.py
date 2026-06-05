# SPDX-License-Identifier: Apache-2.0
"""Phase 210 · INNOV-115 · CGPR — 30-test acceptance suite.

Constitutional Governance Proof Renderer.
"""
from __future__ import annotations

import json
import hashlib
import hmac as _hmac
import pytest
from pathlib import Path

from dorkllm.constitutional_governance_proof_renderer import (
    ConstitutionalGovernanceProofRenderer,
    ProofLedger,
    ProofBundle,
    SlotStatus,
    InvariantStatus,
    AttestationEventType,
    CGPRManifestError,
    CGPRAttestError,
    CGPRVerifyError,
    CGPRChainError,
    GOVERNOR,
    INNOV_CODE,
    PHASE,
    GENESIS_DIGEST,
    HMAC_SECRET,
    _bundle_seal_hmac,
    _deterministic_bundle_id,
    _invariant_hmac,
)

pytestmark = pytest.mark.cgpr

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_INVARIANTS = [
    {"code": "CGPR-CHAIN-0",    "name": "Chain integrity",   "phase_introduced": 210},
    {"code": "CGPR-IMMUT-0",    "name": "Ledger immutability","phase_introduced": 210},
    {"code": "CGPR-BUNDLE-0",   "name": "Deterministic ID",  "phase_introduced": 210},
]

SAMPLE_ATTESTATIONS = [
    {
        "source": "cmac_admission_ledger",
        "phase": 210,
        "event_type": AttestationEventType.PHASE_RATIFICATION.value,
        "payload_digest": "a" * 64,
    },
    {
        "source": "cmpe_policy_ledger",
        "phase": 210,
        "event_type": AttestationEventType.INNOVATION_SHIPPED.value,
        "payload_digest": "b" * 64,
    },
]


@pytest.fixture
def tmp_ledger(tmp_path):
    return ProofLedger(path=tmp_path / "proof_ledger.jsonl")


@pytest.fixture
def renderer(tmp_ledger):
    return ConstitutionalGovernanceProofRenderer(ledger=tmp_ledger)


@pytest.fixture
def basic_bundle(renderer):
    return renderer.render(
        phase=210,
        invariants=SAMPLE_INVARIANTS,
        attestations=SAMPLE_ATTESTATIONS,
        _fixed_ns=1_700_000_000_000_000_000,
    )


# ---------------------------------------------------------------------------
# T210-CGPR-01 — bundle_id is deterministic (CGPR-BUNDLE-0 / CGPR-DETERM-0)
# ---------------------------------------------------------------------------

def test_01_bundle_id_deterministic(renderer):
    ns = 1_700_000_000_000_000_000
    b1 = renderer.render(210, SAMPLE_INVARIANTS, SAMPLE_ATTESTATIONS, _fixed_ns=ns)
    renderer2 = ConstitutionalGovernanceProofRenderer(
        ledger=ProofLedger(path=renderer.ledger.path)
    )
    b2 = renderer2.render(210, SAMPLE_INVARIANTS, SAMPLE_ATTESTATIONS, _fixed_ns=ns)
    assert b1.bundle_id == b2.bundle_id


# ---------------------------------------------------------------------------
# T210-CGPR-02 — bundle_id matches deterministic formula
# ---------------------------------------------------------------------------

def test_02_bundle_id_formula(basic_bundle):
    ns = 1_700_000_000_000_000_000
    expected = _deterministic_bundle_id(GOVERNOR, 210, ns)
    assert basic_bundle.bundle_id == expected


# ---------------------------------------------------------------------------
# T210-CGPR-03 — bundle_hmac present and non-empty
# ---------------------------------------------------------------------------

def test_03_bundle_hmac_present(basic_bundle):
    assert isinstance(basic_bundle.bundle_hmac, str)
    assert len(basic_bundle.bundle_hmac) == 64


# ---------------------------------------------------------------------------
# T210-CGPR-04 — bundle_hmac verifies correctly (CGPR-HMAC-0)
# ---------------------------------------------------------------------------

def test_04_bundle_hmac_verifies(basic_bundle):
    bundle_dict = basic_bundle.to_dict()
    expected = _bundle_seal_hmac(bundle_dict)
    assert _hmac.compare_digest(expected, basic_bundle.bundle_hmac)


# ---------------------------------------------------------------------------
# T210-CGPR-05 — invariant manifest built correctly (CGPR-MANIFEST-0)
# ---------------------------------------------------------------------------

def test_05_invariant_manifest_built(basic_bundle):
    assert len(basic_bundle.invariant_manifest) == len(SAMPLE_INVARIANTS)
    for inv in basic_bundle.invariant_manifest:
        assert "hmac_digest" in inv
        assert len(inv["hmac_digest"]) == 64


# ---------------------------------------------------------------------------
# T210-CGPR-06 — invariant HMAC values correct
# ---------------------------------------------------------------------------

def test_06_invariant_hmac_correct(basic_bundle):
    for inv in basic_bundle.invariant_manifest:
        expected = _invariant_hmac(inv["code"], inv["name"], inv["phase_introduced"])
        assert _hmac.compare_digest(expected, inv["hmac_digest"])


# ---------------------------------------------------------------------------
# T210-CGPR-07 — attestation chain built (CGPR-ATTEST-0)
# ---------------------------------------------------------------------------

def test_07_attestation_chain_built(basic_bundle):
    assert len(basic_bundle.attestations) == len(SAMPLE_ATTESTATIONS)
    prev = GENESIS_DIGEST
    for att in basic_bundle.attestations:
        assert att["prev_digest"] == prev
        prev = att["hmac_digest"]


# ---------------------------------------------------------------------------
# T210-CGPR-08 — chain_summary reflects attestation state
# ---------------------------------------------------------------------------

def test_08_chain_summary(basic_bundle):
    cs = basic_bundle.chain_summary
    assert cs["entry_count"] == len(SAMPLE_ATTESTATIONS)
    assert cs["chain_valid"] is True
    assert cs["genesis_digest"] == GENESIS_DIGEST
    assert cs["head_digest"] == basic_bundle.attestations[-1]["hmac_digest"]


# ---------------------------------------------------------------------------
# T210-CGPR-09 — human0_slot UNSIGNED when no signature (CGPR-HUMAN0-0)
# ---------------------------------------------------------------------------

def test_09_human0_slot_unsigned(basic_bundle):
    slot = basic_bundle.human0_slot
    assert slot["slot_status"] == SlotStatus.UNSIGNED.value
    assert slot["signature_hex"] == ""


# ---------------------------------------------------------------------------
# T210-CGPR-10 — human0_slot SIGNED when signature provided
# ---------------------------------------------------------------------------

def test_10_human0_slot_signed(renderer):
    bundle = renderer.render(
        phase=210,
        invariants=SAMPLE_INVARIANTS,
        attestations=SAMPLE_ATTESTATIONS,
        human0_signature_hex="deadbeef" * 8,
        human0_pubkey_fingerprint="cafebabe" * 8,
        _fixed_ns=1_700_000_000_000_000_001,
    )
    assert bundle.human0_slot["slot_status"] == SlotStatus.SIGNED.value
    assert bundle.human0_slot["signature_hex"] == "deadbeef" * 8


# ---------------------------------------------------------------------------
# T210-CGPR-11 — empty invariants raises CGPRManifestError (CGPR-MANIFEST-0)
# ---------------------------------------------------------------------------

def test_11_empty_invariants_raises(renderer):
    with pytest.raises(CGPRManifestError):
        renderer.render(210, [], SAMPLE_ATTESTATIONS)


# ---------------------------------------------------------------------------
# T210-CGPR-12 — empty attestations raises CGPRAttestError (CGPR-ATTEST-0)
# ---------------------------------------------------------------------------

def test_12_empty_attestations_raises(renderer):
    with pytest.raises(CGPRAttestError):
        renderer.render(210, SAMPLE_INVARIANTS, [])


# ---------------------------------------------------------------------------
# T210-CGPR-13 — proof ledger sealed after render (CGPR-AUDIT-0)
# ---------------------------------------------------------------------------

def test_13_ledger_sealed_after_render(renderer, basic_bundle):
    assert renderer.ledger.entry_count >= 1


# ---------------------------------------------------------------------------
# T210-CGPR-14 — ledger entry count increments on each render
# ---------------------------------------------------------------------------

def test_14_ledger_entry_count_increments(renderer):
    c0 = renderer.ledger.entry_count
    renderer.render(210, SAMPLE_INVARIANTS, SAMPLE_ATTESTATIONS, _fixed_ns=1)
    renderer.render(210, SAMPLE_INVARIANTS, SAMPLE_ATTESTATIONS, _fixed_ns=2)
    assert renderer.ledger.entry_count == c0 + 2


# ---------------------------------------------------------------------------
# T210-CGPR-15 — ledger head_digest changes after render (CGPR-CHAIN-0)
# ---------------------------------------------------------------------------

def test_15_ledger_head_digest_changes(renderer):
    renderer.render(210, SAMPLE_INVARIANTS, SAMPLE_ATTESTATIONS, _fixed_ns=10)
    d1 = renderer.ledger.head_digest
    renderer.render(210, SAMPLE_INVARIANTS, SAMPLE_ATTESTATIONS, _fixed_ns=11)
    d2 = renderer.ledger.head_digest
    assert d1 != d2


# ---------------------------------------------------------------------------
# T210-CGPR-16 — verify() passes on a valid bundle
# ---------------------------------------------------------------------------

def test_16_verify_passes_valid_bundle(renderer, basic_bundle):
    report = renderer.verify(basic_bundle)
    assert report["bundle_hmac_ok"] is True
    assert report["invariant_manifest_ok"] is True
    assert report["attestation_chain_ok"] is True
    assert report["errors"] == []


# ---------------------------------------------------------------------------
# T210-CGPR-17 — verify() raises on tampered bundle_hmac
# ---------------------------------------------------------------------------

def test_17_verify_raises_on_tampered_hmac(renderer, basic_bundle):
    basic_bundle.bundle_hmac = "00" * 32
    with pytest.raises(CGPRVerifyError):
        renderer.verify(basic_bundle)


# ---------------------------------------------------------------------------
# T210-CGPR-18 — verify() raises on tampered invariant HMAC
# ---------------------------------------------------------------------------

def test_18_verify_raises_on_tampered_invariant(renderer, basic_bundle):
    basic_bundle.invariant_manifest[0]["hmac_digest"] = "ff" * 32
    # Must also re-seal the outer bundle_hmac so the outer check passes
    # but inner manifest check fails
    bundle_dict = basic_bundle.to_dict()
    basic_bundle.bundle_hmac = _bundle_seal_hmac(bundle_dict)
    with pytest.raises(CGPRVerifyError):
        renderer.verify(basic_bundle)


# ---------------------------------------------------------------------------
# T210-CGPR-19 — verify() raises on tampered attestation chain
# ---------------------------------------------------------------------------

def test_19_verify_raises_on_tampered_attestation(renderer, basic_bundle):
    basic_bundle.attestations[0]["prev_digest"] = "ee" * 32
    bundle_dict = basic_bundle.to_dict()
    basic_bundle.bundle_hmac = _bundle_seal_hmac(bundle_dict)
    with pytest.raises(CGPRVerifyError):
        renderer.verify(basic_bundle)


# ---------------------------------------------------------------------------
# T210-CGPR-20 — governor field is always DUSTIN L REID
# ---------------------------------------------------------------------------

def test_20_governor_field(basic_bundle):
    assert basic_bundle.governor == "DUSTIN L REID"


# ---------------------------------------------------------------------------
# T210-CGPR-21 — schema_version present and semver format
# ---------------------------------------------------------------------------

def test_21_schema_version(basic_bundle):
    parts = basic_bundle.schema_version.split(".")
    assert len(parts) == 3
    assert all(p.isdigit() for p in parts)


# ---------------------------------------------------------------------------
# T210-CGPR-22 — verification_instructions non-empty (CGPR-OFFLINE-0)
# ---------------------------------------------------------------------------

def test_22_verification_instructions_present(basic_bundle):
    assert len(basic_bundle.verification_instructions) > 100
    assert "hmac.compare_digest" in basic_bundle.verification_instructions
    assert "offline" in basic_bundle.verification_instructions.lower()


# ---------------------------------------------------------------------------
# T210-CGPR-23 — export_json writes valid JSON file
# ---------------------------------------------------------------------------

def test_23_export_json(renderer, basic_bundle, tmp_path):
    out = tmp_path / "proof_bundle.json"
    renderer.export_json(basic_bundle, out)
    assert out.exists()
    loaded = json.loads(out.read_text())
    assert loaded["bundle_id"] == basic_bundle.bundle_id
    assert loaded["governor"] == "DUSTIN L REID"


# ---------------------------------------------------------------------------
# T210-CGPR-24 — ledger persists across renderer instances (CGPR-CHAIN-0)
# ---------------------------------------------------------------------------

def test_24_ledger_persists(tmp_path):
    ledger_path = tmp_path / "proof_ledger.jsonl"
    r1 = ConstitutionalGovernanceProofRenderer(ledger=ProofLedger(ledger_path))
    r1.render(210, SAMPLE_INVARIANTS, SAMPLE_ATTESTATIONS, _fixed_ns=100)
    count1 = r1.ledger.entry_count

    r2 = ConstitutionalGovernanceProofRenderer(ledger=ProofLedger(ledger_path))
    assert r2.ledger.entry_count == count1


# ---------------------------------------------------------------------------
# T210-CGPR-25 — tampered ledger raises CGPRChainError on load
# ---------------------------------------------------------------------------

def test_25_tampered_ledger_raises(tmp_path):
    ledger_path = tmp_path / "proof_ledger.jsonl"
    r = ConstitutionalGovernanceProofRenderer(ledger=ProofLedger(ledger_path))
    r.render(210, SAMPLE_INVARIANTS, SAMPLE_ATTESTATIONS, _fixed_ns=200)

    # Corrupt the ledger
    lines = ledger_path.read_text().splitlines()
    entry = json.loads(lines[0])
    entry["bundle_id"] = "tampered"
    lines[0] = json.dumps(entry)
    ledger_path.write_text("\n".join(lines) + "\n")

    with pytest.raises(CGPRChainError):
        ProofLedger(ledger_path)


# ---------------------------------------------------------------------------
# T210-CGPR-26 — bundle serialises to valid JSON (round-trip)
# ---------------------------------------------------------------------------

def test_26_bundle_json_round_trip(basic_bundle):
    d = basic_bundle.to_dict()
    raw = json.dumps(d)
    loaded = json.loads(raw)
    assert loaded["bundle_id"] == basic_bundle.bundle_id
    assert loaded["bundle_hmac"] == basic_bundle.bundle_hmac


# ---------------------------------------------------------------------------
# T210-CGPR-27 — multiple invariant records all present in manifest
# ---------------------------------------------------------------------------

def test_27_all_invariants_present(basic_bundle):
    codes = {inv["code"] for inv in basic_bundle.invariant_manifest}
    for inp in SAMPLE_INVARIANTS:
        assert inp["code"] in codes


# ---------------------------------------------------------------------------
# T210-CGPR-28 — INNOV_CODE and PHASE constants correct
# ---------------------------------------------------------------------------

def test_28_module_constants():
    assert INNOV_CODE == "CGPR"
    assert PHASE == 210
    assert GOVERNOR == "DUSTIN L REID"


# ---------------------------------------------------------------------------
# T210-CGPR-29 — rendered_by field captured in ledger
# ---------------------------------------------------------------------------

def test_29_rendered_by_in_ledger(tmp_path):
    ledger_path = tmp_path / "proof_ledger.jsonl"
    ledger = ProofLedger(ledger_path)
    r = ConstitutionalGovernanceProofRenderer(ledger=ledger)
    r.render(
        210, SAMPLE_INVARIANTS, SAMPLE_ATTESTATIONS,
        rendered_by="TEST_AGENT", _fixed_ns=999
    )
    raw = json.loads(ledger_path.read_text().strip())
    assert raw["rendered_by"] == "TEST_AGENT"


# ---------------------------------------------------------------------------
# T210-CGPR-30 — two bundles with different ns have different bundle_ids
# ---------------------------------------------------------------------------

def test_30_different_ns_different_ids(renderer):
    b1 = renderer.render(210, SAMPLE_INVARIANTS, SAMPLE_ATTESTATIONS, _fixed_ns=1)
    b2 = renderer.render(210, SAMPLE_INVARIANTS, SAMPLE_ATTESTATIONS, _fixed_ns=2)
    assert b1.bundle_id != b2.bundle_id
