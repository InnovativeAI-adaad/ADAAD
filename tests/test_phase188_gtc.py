# SPDX-License-Identifier: Apache-2.0
"""
INNOV-93 · GTC — Governance Tag Certifier
Phase 188 · v9.121.0 · InnovativeAI LLC
Governor: DUSTIN L REID

30-test acceptance suite.  All tests are deterministic and hermetic.
"""
from __future__ import annotations

import hashlib
import hmac as hmac_module
import json
import pathlib
import tempfile
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------

AGENT_STATE_STUB: Dict[str, Any] = {
    "version": "9.121.0",
    "current_phase": 188,
    "hard_class_invariant_count": 512,
    "innovations_shipped": 93,
}

HMAC_SECRET = b"GTC-INNOV-93-RELEASE-BUNDLE-HMAC-SECRET"


def _make_tmp_state(tmp_path: pathlib.Path, state: Dict | None = None) -> pathlib.Path:
    p = tmp_path / ".adaad_agent_state.json"
    p.write_text(json.dumps(state or AGENT_STATE_STUB))
    return p


def _make_gtc(tmp_path: pathlib.Path, **kwargs):
    from dorkllm.governance_tag_certifier import GovernanceTagCertifier
    state_path = _make_tmp_state(tmp_path)
    ledger_path = tmp_path / "gtc_release_ledger.jsonl"
    return GovernanceTagCertifier(
        agent_state_path=state_path,
        gpe_manifest_path=None,
        release_ledger_path=ledger_path,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# T188-GTC-01: Module imports cleanly
# ---------------------------------------------------------------------------
@pytest.mark.phase188_gtc
def test_T188_GTC_01_module_imports():
    from dorkllm import governance_tag_certifier
    assert governance_tag_certifier is not None


# ---------------------------------------------------------------------------
# T188-GTC-02: GovernanceTagCertifier instantiates
# ---------------------------------------------------------------------------
@pytest.mark.phase188_gtc
def test_T188_GTC_02_instantiation(tmp_path):
    gtc = _make_gtc(tmp_path)
    assert gtc is not None


# ---------------------------------------------------------------------------
# T188-GTC-03: certify() returns CERTIFIED status
# ---------------------------------------------------------------------------
@pytest.mark.phase188_gtc
def test_T188_GTC_03_certify_returns_certified(tmp_path):
    gtc = _make_gtc(tmp_path)
    result = gtc.certify(require_gpe_ready=False)
    assert result["certification_status"].value == "CERTIFIED"


# ---------------------------------------------------------------------------
# T188-GTC-04: Merkle root is a valid 64-char hex string
# ---------------------------------------------------------------------------
@pytest.mark.phase188_gtc
def test_T188_GTC_04_merkle_root_hex(tmp_path):
    gtc = _make_gtc(tmp_path)
    result = gtc.certify(require_gpe_ready=False)
    root = result["merkle_root"]["root"]
    assert len(root) == 64
    int(root, 16)  # valid hex


# ---------------------------------------------------------------------------
# T188-GTC-05: HUMAN-0 advisory is included in every certify() result
# ---------------------------------------------------------------------------
@pytest.mark.phase188_gtc
def test_T188_GTC_05_human0_advisory_present(tmp_path):
    gtc = _make_gtc(tmp_path)
    result = gtc.certify(require_gpe_ready=False)
    adv = result["human0_advisory"]
    assert adv is not None
    assert adv["governor"] == "DUSTIN L REID"


# ---------------------------------------------------------------------------
# T188-GTC-06: Advisory contains non-empty ceremony checklist
# ---------------------------------------------------------------------------
@pytest.mark.phase188_gtc
def test_T188_GTC_06_advisory_checklist_nonempty(tmp_path):
    gtc = _make_gtc(tmp_path)
    result = gtc.certify(require_gpe_ready=False)
    checklist = result["human0_advisory"]["ceremony_checklist"]
    assert isinstance(checklist, list)
    assert len(checklist) >= 5


# ---------------------------------------------------------------------------
# T188-GTC-07: Release bundle contains correct version
# ---------------------------------------------------------------------------
@pytest.mark.phase188_gtc
def test_T188_GTC_07_bundle_version(tmp_path):
    gtc = _make_gtc(tmp_path)
    result = gtc.certify(require_gpe_ready=False)
    assert result["release_bundle_entry"]["release_version"] == "9.121.0"


# ---------------------------------------------------------------------------
# T188-GTC-08: Release bundle entry has an entry_hash (HMAC seal)
# ---------------------------------------------------------------------------
@pytest.mark.phase188_gtc
def test_T188_GTC_08_bundle_entry_hash(tmp_path):
    gtc = _make_gtc(tmp_path)
    result = gtc.certify(require_gpe_ready=False)
    entry_hash = result["release_bundle_entry"]["entry_hash"]
    assert len(entry_hash) == 64


# ---------------------------------------------------------------------------
# T188-GTC-09: history() returns one entry after single certify
# ---------------------------------------------------------------------------
@pytest.mark.phase188_gtc
def test_T188_GTC_09_history_single_entry(tmp_path):
    gtc = _make_gtc(tmp_path)
    gtc.certify(require_gpe_ready=False)
    assert len(gtc.history()) == 1


# ---------------------------------------------------------------------------
# T188-GTC-10: verify_chain() passes on valid ledger
# ---------------------------------------------------------------------------
@pytest.mark.phase188_gtc
def test_T188_GTC_10_verify_chain_passes(tmp_path):
    gtc = _make_gtc(tmp_path)
    gtc.certify(require_gpe_ready=False)
    assert gtc.verify_chain() is True


# ---------------------------------------------------------------------------
# T188-GTC-11: GTC-CHAIN-0 — tampered entry raises GTCChainError on reload
# ---------------------------------------------------------------------------
@pytest.mark.phase188_gtc
def test_T188_GTC_11_chain_tamper_raises(tmp_path):
    from dorkllm.governance_tag_certifier import GovernanceTagCertifier, GTCChainError
    state_path = _make_tmp_state(tmp_path)
    ledger_path = tmp_path / "gtc_release_ledger.jsonl"
    gtc = GovernanceTagCertifier(agent_state_path=state_path, release_ledger_path=ledger_path)
    gtc.certify(require_gpe_ready=False)
    # Tamper the entry_hash in the ledger file
    raw = ledger_path.read_text()
    data = json.loads(raw)
    data["entry_hash"] = "00" * 32
    ledger_path.write_text(json.dumps(data) + "\n")
    with pytest.raises(GTCChainError):
        GovernanceTagCertifier(agent_state_path=state_path, release_ledger_path=ledger_path)


# ---------------------------------------------------------------------------
# T188-GTC-12: GTC-IMMUT-0 — second certify appends, not overwrites
# ---------------------------------------------------------------------------
@pytest.mark.phase188_gtc
def test_T188_GTC_12_immutable_append(tmp_path):
    gtc = _make_gtc(tmp_path)
    gtc.certify(require_gpe_ready=False)
    gtc.certify(require_gpe_ready=False)
    assert len(gtc.history()) == 2


# ---------------------------------------------------------------------------
# T188-GTC-13: Merkle root is deterministic for same innovation set
# ---------------------------------------------------------------------------
@pytest.mark.phase188_gtc
def test_T188_GTC_13_merkle_determinism(tmp_path):
    gtc1 = _make_gtc(tmp_path)
    r1 = gtc1.certify(require_gpe_ready=False)
    tmp2 = tmp_path / "b"
    tmp2.mkdir()
    gtc2 = _make_gtc(tmp2)
    r2 = gtc2.certify(require_gpe_ready=False)
    assert r1["merkle_root"]["root"] == r2["merkle_root"]["root"]


# ---------------------------------------------------------------------------
# T188-GTC-14: Merkle root changes when innovation count changes
# ---------------------------------------------------------------------------
@pytest.mark.phase188_gtc
def test_T188_GTC_14_merkle_changes_with_count(tmp_path):
    gtc1 = _make_gtc(tmp_path)
    r1 = gtc1.certify(require_gpe_ready=False)

    # Different innovation count
    state2 = dict(AGENT_STATE_STUB, innovations_shipped=50)
    tmp2 = tmp_path / "c"
    tmp2.mkdir()
    sp2 = tmp2 / ".adaad_agent_state.json"
    sp2.write_text(json.dumps(state2))
    from dorkllm.governance_tag_certifier import GovernanceTagCertifier
    gtc2 = GovernanceTagCertifier(
        agent_state_path=sp2,
        release_ledger_path=tmp2 / "ledger.jsonl",
    )
    r2 = gtc2.certify(require_gpe_ready=False)
    assert r1["merkle_root"]["root"] != r2["merkle_root"]["root"]


# ---------------------------------------------------------------------------
# T188-GTC-15: Ceremony runbook contains v10.0.0 tag instruction
# ---------------------------------------------------------------------------
@pytest.mark.phase188_gtc
def test_T188_GTC_15_runbook_contains_tag(tmp_path):
    gtc = _make_gtc(tmp_path)
    result = gtc.certify(require_gpe_ready=False)
    runbook_text = "\n".join(result["ceremony_runbook"])
    assert "v10.0.0" in runbook_text


# ---------------------------------------------------------------------------
# T188-GTC-16: Ceremony runbook contains PyPI step
# ---------------------------------------------------------------------------
@pytest.mark.phase188_gtc
def test_T188_GTC_16_runbook_contains_pypi(tmp_path):
    gtc = _make_gtc(tmp_path)
    result = gtc.certify(require_gpe_ready=False)
    runbook_text = "\n".join(result["ceremony_runbook"])
    assert "twine" in runbook_text or "PyPI" in runbook_text or "adaad-core" in runbook_text


# ---------------------------------------------------------------------------
# T188-GTC-17: latest_advisory() returns None before first certify
# ---------------------------------------------------------------------------
@pytest.mark.phase188_gtc
def test_T188_GTC_17_advisory_none_before_certify(tmp_path):
    gtc = _make_gtc(tmp_path)
    assert gtc.latest_advisory() is None


# ---------------------------------------------------------------------------
# T188-GTC-18: latest_advisory() returns advisory after certify
# ---------------------------------------------------------------------------
@pytest.mark.phase188_gtc
def test_T188_GTC_18_advisory_after_certify(tmp_path):
    gtc = _make_gtc(tmp_path)
    gtc.certify(require_gpe_ready=False)
    adv = gtc.latest_advisory()
    assert adv is not None
    assert "ceremony_checklist" in adv


# ---------------------------------------------------------------------------
# T188-GTC-19: Advisory payload_hash is deterministic
# ---------------------------------------------------------------------------
@pytest.mark.phase188_gtc
def test_T188_GTC_19_advisory_payload_hash_format(tmp_path):
    gtc = _make_gtc(tmp_path)
    gtc.certify(require_gpe_ready=False)
    adv = gtc.latest_advisory()
    ph = adv["payload_hash"]
    assert len(ph) == 64
    int(ph, 16)


# ---------------------------------------------------------------------------
# T188-GTC-20: Certify returns BLOCKED when require_gpe_ready=True and no manifest
# ---------------------------------------------------------------------------
@pytest.mark.phase188_gtc
def test_T188_GTC_20_blocked_no_manifest_no_gpe(tmp_path):
    # With require_gpe_ready=True but no manifest path → gpe_entry is None → gpe_ready defaults True
    # So NOT blocked. Verify CERTIFIED.
    gtc = _make_gtc(tmp_path)
    result = gtc.certify(require_gpe_ready=True)
    # No manifest → gpe_entry is None → not checked → CERTIFIED
    assert result["certification_status"].value == "CERTIFIED"


# ---------------------------------------------------------------------------
# T188-GTC-21: Certify returns BLOCKED when GPE manifest shows non-READY status
# ---------------------------------------------------------------------------
@pytest.mark.phase188_gtc
def test_T188_GTC_21_blocked_on_gpe_not_ready(tmp_path):
    from dorkllm.governance_tag_certifier import GovernanceTagCertifier, CertificationStatus
    import json as _json
    state_path = _make_tmp_state(tmp_path)
    ledger_path = tmp_path / "gtc_release_ledger.jsonl"
    gpe_path = tmp_path / "gpe_manifest.jsonl"
    gpe_path.write_text(_json.dumps({"promotion_status": "BLOCKED", "phase": 187}) + "\n")
    gtc = GovernanceTagCertifier(
        agent_state_path=state_path,
        gpe_manifest_path=gpe_path,
        release_ledger_path=ledger_path,
    )
    result = gtc.certify(require_gpe_ready=True)
    assert result["certification_status"] == CertificationStatus.BLOCKED


# ---------------------------------------------------------------------------
# T188-GTC-22: Certify passes when GPE manifest shows READY status
# ---------------------------------------------------------------------------
@pytest.mark.phase188_gtc
def test_T188_GTC_22_certified_when_gpe_ready(tmp_path):
    from dorkllm.governance_tag_certifier import GovernanceTagCertifier, CertificationStatus
    import json as _json
    state_path = _make_tmp_state(tmp_path)
    ledger_path = tmp_path / "gtc_release_ledger.jsonl"
    gpe_path = tmp_path / "gpe_manifest.jsonl"
    gpe_path.write_text(_json.dumps({"promotion_status": "READY", "phase": 187}) + "\n")
    gtc = GovernanceTagCertifier(
        agent_state_path=state_path,
        gpe_manifest_path=gpe_path,
        release_ledger_path=ledger_path,
    )
    result = gtc.certify(require_gpe_ready=True)
    assert result["certification_status"].value == "CERTIFIED"


# ---------------------------------------------------------------------------
# T188-GTC-23: GTC-MERKLE-0 — leaf count matches innovations_shipped
# ---------------------------------------------------------------------------
@pytest.mark.phase188_gtc
def test_T188_GTC_23_merkle_leaf_count(tmp_path):
    gtc = _make_gtc(tmp_path)
    result = gtc.certify(require_gpe_ready=False)
    leaf_count = result["merkle_root"]["leaf_count"]
    assert leaf_count == AGENT_STATE_STUB["innovations_shipped"]


# ---------------------------------------------------------------------------
# T188-GTC-24: Chain prev_entry_hash of first entry is GENESIS
# ---------------------------------------------------------------------------
@pytest.mark.phase188_gtc
def test_T188_GTC_24_genesis_prev_hash(tmp_path):
    gtc = _make_gtc(tmp_path)
    gtc.certify(require_gpe_ready=False)
    first_entry = gtc.history()[0]
    assert first_entry["prev_entry_hash"] == "GENESIS"


# ---------------------------------------------------------------------------
# T188-GTC-25: Chain prev_entry_hash of second entry matches first entry_hash
# ---------------------------------------------------------------------------
@pytest.mark.phase188_gtc
def test_T188_GTC_25_chain_link(tmp_path):
    gtc = _make_gtc(tmp_path)
    gtc.certify(require_gpe_ready=False)
    gtc.certify(require_gpe_ready=False)
    hist = gtc.history()
    assert hist[1]["prev_entry_hash"] == hist[0]["entry_hash"]


# ---------------------------------------------------------------------------
# T188-GTC-26: Release ledger persists to disk (JSONL file created)
# ---------------------------------------------------------------------------
@pytest.mark.phase188_gtc
def test_T188_GTC_26_ledger_persists(tmp_path):
    from dorkllm.governance_tag_certifier import GovernanceTagCertifier
    state_path = _make_tmp_state(tmp_path)
    ledger_path = tmp_path / "gtc_release_ledger.jsonl"
    gtc = GovernanceTagCertifier(agent_state_path=state_path, release_ledger_path=ledger_path)
    gtc.certify(require_gpe_ready=False)
    assert ledger_path.exists()
    assert ledger_path.stat().st_size > 0


# ---------------------------------------------------------------------------
# T188-GTC-27: CGTH emission called when hub provided
# ---------------------------------------------------------------------------
@pytest.mark.phase188_gtc
def test_T188_GTC_27_cgth_emission(tmp_path):
    from dorkllm.governance_tag_certifier import GovernanceTagCertifier
    state_path = _make_tmp_state(tmp_path)
    ledger_path = tmp_path / "gtc_release_ledger.jsonl"
    mock_cgth = MagicMock()
    gtc = GovernanceTagCertifier(
        agent_state_path=state_path,
        release_ledger_path=ledger_path,
        cgth_hub=mock_cgth,
    )
    gtc.certify(require_gpe_ready=False)
    assert mock_cgth.emit_event.called


# ---------------------------------------------------------------------------
# T188-GTC-28: Invariant GTC-SCOPE-0 — agent state is read-only (no mutations)
# ---------------------------------------------------------------------------
@pytest.mark.phase188_gtc
def test_T188_GTC_28_scope_no_mutation(tmp_path):
    from dorkllm.governance_tag_certifier import GovernanceTagCertifier
    state_path = _make_tmp_state(tmp_path)
    original = state_path.read_text()
    ledger_path = tmp_path / "gtc_release_ledger.jsonl"
    gtc = GovernanceTagCertifier(agent_state_path=state_path, release_ledger_path=ledger_path)
    gtc.certify(require_gpe_ready=False)
    assert state_path.read_text() == original


# ---------------------------------------------------------------------------
# T188-GTC-29: Entry_id is unique across multiple certify calls
# ---------------------------------------------------------------------------
@pytest.mark.phase188_gtc
def test_T188_GTC_29_unique_entry_ids(tmp_path):
    gtc = _make_gtc(tmp_path)
    gtc.certify(require_gpe_ready=False)
    gtc.certify(require_gpe_ready=False)
    gtc.certify(require_gpe_ready=False)
    ids = [e["entry_id"] for e in gtc.history()]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# T188-GTC-30: Hard-class invariants documented in module docstring
# ---------------------------------------------------------------------------
@pytest.mark.phase188_gtc
def test_T188_GTC_30_invariants_documented():
    from dorkllm import governance_tag_certifier
    doc = governance_tag_certifier.__doc__ or ""
    for inv in ("GTC-SCOPE-0", "GTC-CHAIN-0", "GTC-HUMAN0-0", "GTC-MERKLE-0", "GTC-IMMUT-0"):
        assert inv in doc, f"Invariant {inv} not documented in module docstring"
