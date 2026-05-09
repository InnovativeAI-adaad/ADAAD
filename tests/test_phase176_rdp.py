# SPDX-License-Identifier: Apache-2.0
# tests/test_phase176_rdp.py — INNOV-81 · RDP Acceptance Suite
# 30 tests · markers T176-RDP-01..30
# InnovativeAI LLC · HUMAN-0: Dustin L. Reid

import json
import pathlib
import tempfile
import uuid

import pytest

from dorkllm.recommendation_delivery_protocol import (
    RecommendationDeliveryProtocol,
    GovernanceProposal,
    DispositionRecord,
    DeliveryResult,
    VALID_DISPOSITIONS,
    VALID_TIERS,
    _GOVERNOR,
    _MAX_QUEUE_DEPTH,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────
@pytest.fixture
def tmp_rdp(tmp_path):
    """Fresh RDP instance with temp-isolated ledger paths."""
    cal_path = tmp_path / "cal.json"
    rdp = RecommendationDeliveryProtocol(
        cal_recommendations_path=cal_path,
        proposal_ledger_path=tmp_path / "proposals.jsonl",
        disposition_ledger_path=tmp_path / "dispositions.jsonl",
        queue_state_path=tmp_path / "queue.json",
    )
    return rdp, cal_path


def _write_cal(cal_path, recs):
    cal_path.write_text(json.dumps(recs))


def _sample_recs(n=3):
    return [
        {
            "invariant_id": f"TEST-INV-{i:02d}",
            "recommendation": ["REINFORCE", "REVIEW", "STABLE"][i % 3],
            "rationale": f"Rationale for invariant {i}",
            "governor": _GOVERNOR,
            "normalized_weight": round(0.1 * i, 2),
        }
        for i in range(1, n + 1)
    ]


# ── T176-RDP-01: Module imports cleanly ───────────────────────────────────────
@pytest.mark.T176
def test_T176_RDP_01_import():
    from dorkllm.recommendation_delivery_protocol import RecommendationDeliveryProtocol
    assert RecommendationDeliveryProtocol is not None


# ── T176-RDP-02: RDP-SCOPE-0 enforced — constructor rejects matching paths ───
@pytest.mark.T176
def test_T176_RDP_02_scope_invariant(tmp_path):
    cal = tmp_path / "cal.json"
    with pytest.raises(AssertionError, match="RDP-SCOPE-0"):
        RecommendationDeliveryProtocol(
            cal_recommendations_path=cal,
            proposal_ledger_path=cal,  # SCOPE violation
            disposition_ledger_path=tmp_path / "d.jsonl",
            queue_state_path=tmp_path / "q.json",
        )


# ── T176-RDP-03: deliver() returns DeliveryResult ────────────────────────────
@pytest.mark.T176
def test_T176_RDP_03_deliver_returns_result(tmp_rdp):
    rdp, cal_path = tmp_rdp
    _write_cal(cal_path, _sample_recs(2))
    result = rdp.deliver()
    assert isinstance(result, DeliveryResult)


# ── T176-RDP-04: proposals_generated matches CAL input ───────────────────────
@pytest.mark.T176
def test_T176_RDP_04_proposals_generated_count(tmp_rdp):
    rdp, cal_path = tmp_rdp
    _write_cal(cal_path, _sample_recs(3))
    result = rdp.deliver()
    assert result.proposals_generated == 3
    assert result.proposals_queued == 3


# ── T176-RDP-05: HMAC chain hash present in result ───────────────────────────
@pytest.mark.T176
def test_T176_RDP_05_chain_hash_in_result(tmp_rdp):
    rdp, cal_path = tmp_rdp
    _write_cal(cal_path, _sample_recs(1))
    result = rdp.deliver()
    assert len(result.hmac_chain_hash) == 64


# ── T176-RDP-06: timestamp is ISO-8601 UTC ───────────────────────────────────
@pytest.mark.T176
def test_T176_RDP_06_timestamp_utc(tmp_rdp):
    rdp, cal_path = tmp_rdp
    _write_cal(cal_path, _sample_recs(1))
    result = rdp.deliver()
    from datetime import datetime, timezone
    dt = datetime.fromisoformat(result.timestamp_utc_iso)
    assert dt.tzinfo is not None


# ── T176-RDP-07: proposals appear in get_pending_proposals ───────────────────
@pytest.mark.T176
def test_T176_RDP_07_pending_proposals_visible(tmp_rdp):
    rdp, cal_path = tmp_rdp
    _write_cal(cal_path, _sample_recs(2))
    rdp.deliver()
    pending = rdp.get_pending_proposals()
    assert len(pending) == 2
    assert all(p["status"] == "PENDING" for p in pending)


# ── T176-RDP-08: proposal has all RDP-FORMAT-0 required fields ───────────────
@pytest.mark.T176
def test_T176_RDP_08_format_fields(tmp_rdp):
    rdp, cal_path = tmp_rdp
    _write_cal(cal_path, _sample_recs(1))
    rdp.deliver()
    prop = rdp.get_pending_proposals()[0]
    for field in ("invariant_id", "tier", "rationale", "governor", "proposal_id"):
        assert field in prop, f"Missing field: {field}"


# ── T176-RDP-09: RDP-FORMAT-0 — missing invariant_id rejected ────────────────
@pytest.mark.T176
def test_T176_RDP_09_format_missing_invariant_id(tmp_rdp):
    rdp, cal_path = tmp_rdp
    bad = [{"recommendation": "REINFORCE", "rationale": "x", "governor": _GOVERNOR}]
    _write_cal(cal_path, bad)
    result = rdp.deliver()
    assert result.proposals_rejected == 1
    assert result.proposals_queued == 0


# ── T176-RDP-10: RDP-FORMAT-0 — empty rationale rejected ─────────────────────
@pytest.mark.T176
def test_T176_RDP_10_format_missing_rationale(tmp_rdp):
    rdp, cal_path = tmp_rdp
    bad = [{"invariant_id": "X-0", "recommendation": "REINFORCE", "rationale": "", "governor": _GOVERNOR}]
    _write_cal(cal_path, bad)
    result = rdp.deliver()
    assert result.proposals_rejected == 1


# ── T176-RDP-11: invalid tier is rejected ────────────────────────────────────
@pytest.mark.T176
def test_T176_RDP_11_invalid_tier_rejected(tmp_rdp):
    rdp, cal_path = tmp_rdp
    bad = [{"invariant_id": "X-0", "recommendation": "DEMOLISH", "rationale": "x", "governor": _GOVERNOR}]
    _write_cal(cal_path, bad)
    result = rdp.deliver()
    assert result.proposals_rejected == 1


# ── T176-RDP-12: proposal ledger file created on first deliver ───────────────
@pytest.mark.T176
def test_T176_RDP_12_ledger_file_created(tmp_rdp):
    rdp, cal_path = tmp_rdp
    _write_cal(cal_path, _sample_recs(1))
    rdp.deliver()
    assert rdp.proposal_ledger_path.exists()


# ── T176-RDP-13: ledger lines are valid JSONL ────────────────────────────────
@pytest.mark.T176
def test_T176_RDP_13_ledger_valid_jsonl(tmp_rdp):
    rdp, cal_path = tmp_rdp
    _write_cal(cal_path, _sample_recs(3))
    rdp.deliver()
    with open(rdp.proposal_ledger_path) as f:
        lines = [l.strip() for l in f if l.strip()]
    assert len(lines) == 3
    for line in lines:
        json.loads(line)  # must not raise


# ── T176-RDP-14: RDP-CHAIN-0 — each record has hmac_chain_hash ───────────────
@pytest.mark.T176
def test_T176_RDP_14_chain_hash_in_ledger(tmp_rdp):
    rdp, cal_path = tmp_rdp
    _write_cal(cal_path, _sample_recs(2))
    rdp.deliver()
    with open(rdp.proposal_ledger_path) as f:
        for line in f:
            rec = json.loads(line.strip())
            assert "hmac_chain_hash" in rec
            assert len(rec["hmac_chain_hash"]) == 64


# ── T176-RDP-15: verify_all_chains passes on clean ledger ────────────────────
@pytest.mark.T176
def test_T176_RDP_15_verify_chains_ok(tmp_rdp):
    rdp, cal_path = tmp_rdp
    _write_cal(cal_path, _sample_recs(2))
    rdp.deliver()
    result = rdp.verify_all_chains()
    assert result["proposal_ledger"]["status"] == "OK"


# ── T176-RDP-16: RDP-CHAIN-0 — tampered ledger detected ──────────────────────
@pytest.mark.T176
def test_T176_RDP_16_chain_tamper_detected(tmp_rdp):
    rdp, cal_path = tmp_rdp
    _write_cal(cal_path, _sample_recs(2))
    rdp.deliver()
    # Tamper: flip a byte in the ledger
    content = rdp.proposal_ledger_path.read_text()
    tampered = content[:50] + ("X" if content[50] != "X" else "Y") + content[51:]
    rdp.proposal_ledger_path.write_text(tampered)
    result = rdp.verify_all_chains()
    assert result["proposal_ledger"]["status"] == "CHAIN_BROKEN"


# ── T176-RDP-17: RDP-REPLAY-0 — duplicate cycle_id rejected ──────────────────
@pytest.mark.T176
def test_T176_RDP_17_replay_rejected(tmp_rdp):
    rdp, cal_path = tmp_rdp
    _write_cal(cal_path, _sample_recs(1))
    rdp.deliver(cycle_id="rdp-unique-001")
    with pytest.raises(ValueError, match="RDP-REPLAY-0"):
        rdp.deliver(cycle_id="rdp-unique-001")


# ── T176-RDP-18: record_disposition — ACCEPTED path ─────────────────────────
@pytest.mark.T176
def test_T176_RDP_18_disposition_accepted(tmp_rdp):
    rdp, cal_path = tmp_rdp
    _write_cal(cal_path, _sample_recs(1))
    rdp.deliver()
    pid = rdp.get_pending_proposals()[0]["proposal_id"]
    disp = rdp.record_disposition(pid, "ACCEPTED", f"approved {_GOVERNOR}", "High value")
    assert isinstance(disp, DispositionRecord)
    assert disp.disposition == "ACCEPTED"


# ── T176-RDP-19: record_disposition — DEFERRED path ──────────────────────────
@pytest.mark.T176
def test_T176_RDP_19_disposition_deferred(tmp_rdp):
    rdp, cal_path = tmp_rdp
    _write_cal(cal_path, _sample_recs(1))
    rdp.deliver()
    pid = rdp.get_pending_proposals()[0]["proposal_id"]
    disp = rdp.record_disposition(pid, "DEFERRED", f"approved {_GOVERNOR}", "Needs more data")
    assert disp.disposition == "DEFERRED"


# ── T176-RDP-20: record_disposition — REJECTED path ──────────────────────────
@pytest.mark.T176
def test_T176_RDP_20_disposition_rejected(tmp_rdp):
    rdp, cal_path = tmp_rdp
    _write_cal(cal_path, _sample_recs(1))
    rdp.deliver()
    pid = rdp.get_pending_proposals()[0]["proposal_id"]
    disp = rdp.record_disposition(pid, "REJECTED", f"approved {_GOVERNOR}", "Low signal")
    assert disp.disposition == "REJECTED"


# ── T176-RDP-21: RDP-HUMAN0-0 — empty governor_token raises ──────────────────
@pytest.mark.T176
def test_T176_RDP_21_human0_empty_token_raises(tmp_rdp):
    rdp, cal_path = tmp_rdp
    _write_cal(cal_path, _sample_recs(1))
    rdp.deliver()
    pid = rdp.get_pending_proposals()[0]["proposal_id"]
    with pytest.raises(ValueError, match="RDP-HUMAN0-0"):
        rdp.record_disposition(pid, "ACCEPTED", "", "No governor")


# ── T176-RDP-22: RDP-HUMAN0-0 — whitespace-only token raises ─────────────────
@pytest.mark.T176
def test_T176_RDP_22_human0_whitespace_token_raises(tmp_rdp):
    rdp, cal_path = tmp_rdp
    _write_cal(cal_path, _sample_recs(1))
    rdp.deliver()
    pid = rdp.get_pending_proposals()[0]["proposal_id"]
    with pytest.raises(ValueError, match="RDP-HUMAN0-0"):
        rdp.record_disposition(pid, "ACCEPTED", "   ", "Whitespace token")


# ── T176-RDP-23: invalid disposition value raises ────────────────────────────
@pytest.mark.T176
def test_T176_RDP_23_invalid_disposition_raises(tmp_rdp):
    rdp, cal_path = tmp_rdp
    _write_cal(cal_path, _sample_recs(1))
    rdp.deliver()
    pid = rdp.get_pending_proposals()[0]["proposal_id"]
    with pytest.raises(ValueError, match="Invalid disposition"):
        rdp.record_disposition(pid, "MAYBE", f"approved {_GOVERNOR}", "Bad value")


# ── T176-RDP-24: RDP-IMMUT-0 — double-disposition raises ─────────────────────
@pytest.mark.T176
def test_T176_RDP_24_double_disposition_raises(tmp_rdp):
    rdp, cal_path = tmp_rdp
    _write_cal(cal_path, _sample_recs(1))
    rdp.deliver()
    pid = rdp.get_pending_proposals()[0]["proposal_id"]
    rdp.record_disposition(pid, "ACCEPTED", f"approved {_GOVERNOR}", "First")
    with pytest.raises(ValueError, match="RDP-IMMUT-0"):
        rdp.record_disposition(pid, "REJECTED", f"approved {_GOVERNOR}", "Second")


# ── T176-RDP-25: disposition ledger chain verifies OK ────────────────────────
@pytest.mark.T176
def test_T176_RDP_25_disposition_chain_ok(tmp_rdp):
    rdp, cal_path = tmp_rdp
    _write_cal(cal_path, _sample_recs(2))
    rdp.deliver()
    for prop in rdp.get_pending_proposals():
        rdp.record_disposition(
            prop["proposal_id"], "ACCEPTED", f"approved {_GOVERNOR}", "Batch"
        )
    result = rdp.verify_all_chains()
    assert result["disposition_ledger"]["status"] == "OK"


# ── T176-RDP-26: get_disposition_summary returns correct counts ───────────────
@pytest.mark.T176
def test_T176_RDP_26_disposition_summary(tmp_rdp):
    rdp, cal_path = tmp_rdp
    _write_cal(cal_path, _sample_recs(3))
    rdp.deliver()
    props = rdp.get_pending_proposals()
    rdp.record_disposition(props[0]["proposal_id"], "ACCEPTED", f"approved {_GOVERNOR}", "OK")
    rdp.record_disposition(props[1]["proposal_id"], "DEFERRED", f"approved {_GOVERNOR}", "Later")
    rdp.record_disposition(props[2]["proposal_id"], "REJECTED", f"approved {_GOVERNOR}", "No")
    summary = rdp.get_disposition_summary()
    assert len(summary["ACCEPTED"]) == 1
    assert len(summary["DEFERRED"]) == 1
    assert len(summary["REJECTED"]) == 1
    assert summary["total"] == 3


# ── T176-RDP-27: RDP-QUEUE-0 — excess proposals rejected ─────────────────────
@pytest.mark.T176
def test_T176_RDP_27_queue_depth_bound(tmp_path):
    rdp = RecommendationDeliveryProtocol(
        cal_recommendations_path=tmp_path / "cal.json",
        proposal_ledger_path=tmp_path / "p.jsonl",
        disposition_ledger_path=tmp_path / "d.jsonl",
        queue_state_path=tmp_path / "q.json",
        max_queue_depth=2,
    )
    recs = _sample_recs(5)
    (tmp_path / "cal.json").write_text(json.dumps(recs))
    result = rdp.deliver()
    assert result.proposals_queued == 2
    assert result.proposals_rejected == 3


# ── T176-RDP-28: empty CAL path returns empty result ─────────────────────────
@pytest.mark.T176
def test_T176_RDP_28_empty_cal_empty_result(tmp_rdp):
    rdp, cal_path = tmp_rdp
    # No cal file written
    result = rdp.deliver()
    assert result.proposals_generated == 0
    assert result.proposals_queued == 0


# ── T176-RDP-29: RDP-DETERM-0 — datetime.now only inside _utc_iso ────────────
@pytest.mark.T176
def test_T176_RDP_29_determ_no_wallclock():
    import ast
    src = pathlib.Path("dorkllm/recommendation_delivery_protocol.py").read_text()
    tree = ast.parse(src)

    # Collect all Call nodes that are datetime.now(...)
    class Visitor(ast.NodeVisitor):
        def __init__(self):
            self.now_calls = []      # (lineno, enclosing_func)
            self._func_stack = []

        def visit_FunctionDef(self, node):
            self._func_stack.append(node.name)
            self.generic_visit(node)
            self._func_stack.pop()

        def visit_Call(self, node):
            fn = node.func
            if isinstance(fn, ast.Attribute) and fn.attr == "now":
                enclosing = self._func_stack[-1] if self._func_stack else "<module>"
                self.now_calls.append((node.lineno, enclosing))
            self.generic_visit(node)

    v = Visitor()
    v.visit(tree)

    bad = [(ln, fn) for ln, fn in v.now_calls if fn != "_utc_iso"]
    assert not bad, f"RDP-DETERM-0: datetime.now() outside _utc_iso at: {bad}"


# ── T176-RDP-30: requires_human0_approval is always True ─────────────────────
@pytest.mark.T176
def test_T176_RDP_30_human0_always_required(tmp_rdp):
    rdp, cal_path = tmp_rdp
    _write_cal(cal_path, _sample_recs(3))
    rdp.deliver()
    for prop in rdp.get_pending_proposals():
        assert prop["requires_human0_approval"] is True, (
            f"RDP-HUMAN0-0: proposal {prop['proposal_id']} has requires_human0_approval=False"
        )
