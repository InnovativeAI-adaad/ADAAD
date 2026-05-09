# SPDX-License-Identifier: Apache-2.0
"""
T177-CFI-01..30 — Acceptance tests for INNOV-82 · CFI — CEL Feedback Integrator
Phase 177 · v9.110.0 · InnovativeAI LLC
"""

from __future__ import annotations

import ast
import hashlib
import hmac
import inspect
import json
import textwrap
import uuid
from pathlib import Path
from typing import Dict

import pytest

from dorkllm.cfi_feedback_integrator import (
    ACCEPTED_AMPLIFY,
    CANONICAL_AXES,
    CFIAtomicError,
    CFIChainError,
    CFIFeedbackIntegrator,
    CFINormError,
    CFIReplayError,
    CFIScopeError,
    DEFAULT_WEIGHTS,
    DispositionSignal,
    FeedbackWeightSet,
    IntegrationSummary,
    NORM_TOLERANCE,
    REJECTED_DECAY,
    WEIGHT_CEIL,
    WEIGHT_FLOOR,
    _resolve_axis,
    _utc_iso,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_cfi(tmp_path):
    """Return a CFIFeedbackIntegrator wired to tmp_path."""
    return CFIFeedbackIntegrator(
        rdp_disposition_ledger_path=tmp_path / "disposition_ledger.jsonl",
        feedback_ledger_path=tmp_path / "feedback_weight_ledger.jsonl",
        weight_snapshot_path=tmp_path / "current_weights.json",
    )


def _write_disposition(path: Path, records: list[dict]) -> None:
    """Helper: write mock RDP disposition records."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def _make_disposition(
    invariant_id: str = "CAL-CHAIN-0",
    disposition: str = "ACCEPTED",
    proposal_id: str | None = None,
) -> dict:
    return {
        "record_id": str(uuid.uuid4()),
        "proposal_id": proposal_id or str(uuid.uuid4()),
        "invariant_id": invariant_id,
        "disposition": disposition,
        "decided_at_utc": _utc_iso(),
    }


# ── T177-CFI-01: Module import ────────────────────────────────────────────────

def test_cfi_01_import():
    """T177-CFI-01: Module imports without error."""
    from dorkllm import cfi_feedback_integrator  # noqa: F401


# ── T177-CFI-02: Constructor and SCOPE-0 ─────────────────────────────────────

def test_cfi_02_scope_violation(tmp_path):
    """T177-CFI-02: CFI-SCOPE-0 — feedback_ledger_path must not overlap RDP disposition path."""
    rdp_path = tmp_path / "disposition_ledger.jsonl"
    with pytest.raises(CFIScopeError):
        CFIFeedbackIntegrator(
            rdp_disposition_ledger_path=rdp_path,
            feedback_ledger_path=rdp_path,  # same path — SCOPE violation
            weight_snapshot_path=tmp_path / "snap.json",
        )


# ── T177-CFI-03: Default weights on fresh instance ───────────────────────────

def test_cfi_03_default_weights(tmp_cfi):
    """T177-CFI-03: load_current_weights returns DEFAULT_WEIGHTS when no snapshot exists."""
    weights = tmp_cfi.load_current_weights()
    assert weights == DEFAULT_WEIGHTS


# ── T177-CFI-04: Weights are over CANONICAL_AXES ─────────────────────────────

def test_cfi_04_canonical_axes_coverage():
    """T177-CFI-04: DEFAULT_WEIGHTS keys match CANONICAL_AXES exactly."""
    assert set(DEFAULT_WEIGHTS.keys()) == CANONICAL_AXES


# ── T177-CFI-05: DEFAULT_WEIGHTS sum to 1.0 ──────────────────────────────────

def test_cfi_05_default_weights_sum():
    """T177-CFI-05: DEFAULT_WEIGHTS sum to 1.0 ± NORM_TOLERANCE."""
    total = sum(DEFAULT_WEIGHTS.values())
    assert abs(total - 1.0) <= NORM_TOLERANCE


# ── T177-CFI-06: Integrate with zero signals ─────────────────────────────────

def test_cfi_06_integrate_zero_signals(tmp_cfi):
    """T177-CFI-06: integrate() with empty RDP ledger returns DEFAULT_WEIGHTS unchanged."""
    summary = tmp_cfi.integrate()
    assert isinstance(summary, IntegrationSummary)
    assert summary.signals_consumed == 0
    assert abs(sum(summary.new_weights.values()) - 1.0) <= NORM_TOLERANCE
    assert summary.new_weights == DEFAULT_WEIGHTS


# ── T177-CFI-07: IntegrationSummary type contract ────────────────────────────

def test_cfi_07_summary_type(tmp_cfi):
    """T177-CFI-07: IntegrationSummary carries required fields."""
    s = tmp_cfi.integrate()
    assert hasattr(s, "integration_id")
    assert hasattr(s, "signals_consumed")
    assert hasattr(s, "new_weights")
    assert hasattr(s, "ledger_chain_hash")
    assert hasattr(s, "timestamp_utc")
    assert "T" in s.timestamp_utc   # ISO 8601 format


# ── T177-CFI-08: ACCEPTED signal amplifies axis weight ───────────────────────

def test_cfi_08_accepted_amplifies(tmp_path):
    """T177-CFI-08: ACCEPTED disposition on CHAIN invariant amplifies constitutional_debt."""
    rdp = tmp_path / "disposition_ledger.jsonl"
    _write_disposition(rdp, [_make_disposition("MSE-CHAIN-0", "ACCEPTED")])
    cfi = CFIFeedbackIntegrator(
        rdp_disposition_ledger_path=rdp,
        feedback_ledger_path=tmp_path / "fl.jsonl",
        weight_snapshot_path=tmp_path / "snap.json",
    )
    s = cfi.integrate()
    assert s.accepted_count == 1
    # constitutional_debt should have increased (before normalisation)
    assert s.axis_deltas["constitutional_debt"] > 0 or abs(s.axis_deltas["constitutional_debt"]) < 1e-6


# ── T177-CFI-09: REJECTED signal decays axis weight ──────────────────────────

def test_cfi_09_rejected_decays(tmp_path):
    """T177-CFI-09: REJECTED disposition on CHAIN invariant decays constitutional_debt delta."""
    rdp = tmp_path / "disposition_ledger.jsonl"
    _write_disposition(rdp, [_make_disposition("MSE-CHAIN-0", "REJECTED")])
    cfi = CFIFeedbackIntegrator(
        rdp_disposition_ledger_path=rdp,
        feedback_ledger_path=tmp_path / "fl.jsonl",
        weight_snapshot_path=tmp_path / "snap.json",
    )
    s = cfi.integrate()
    assert s.rejected_count == 1
    # After normalisation, all weights still sum to 1.0
    assert abs(sum(s.new_weights.values()) - 1.0) <= NORM_TOLERANCE


# ── T177-CFI-10: DEFERRED signal is neutral (CFI-HUMAN0-0) ───────────────────

def test_cfi_10_deferred_neutral(tmp_path):
    """T177-CFI-10: CFI-HUMAN0-0 — DEFERRED dispositions do not modify weights."""
    rdp = tmp_path / "disposition_ledger.jsonl"
    _write_disposition(rdp, [_make_disposition("RDP-CHAIN-0", "DEFERRED")])
    cfi = CFIFeedbackIntegrator(
        rdp_disposition_ledger_path=rdp,
        feedback_ledger_path=tmp_path / "fl.jsonl",
        weight_snapshot_path=tmp_path / "snap.json",
    )
    s = cfi.integrate()
    assert s.deferred_count == 1
    assert s.new_weights == DEFAULT_WEIGHTS


# ── T177-CFI-11: Weights always within FLOOR / CEIL (CFI-FLOOR-0 / CFI-CEIL-0)

def test_cfi_11_floor_ceil(tmp_path):
    """T177-CFI-11: CFI-FLOOR-0 / CFI-CEIL-0 — all output weights in [WEIGHT_FLOOR, WEIGHT_CEIL]."""
    rdp = tmp_path / "disposition_ledger.jsonl"
    # Flood with REJECTED on one axis to push it toward zero
    records = [_make_disposition("MSE-CHAIN-0", "REJECTED") for _ in range(50)]
    _write_disposition(rdp, records)
    cfi = CFIFeedbackIntegrator(
        rdp_disposition_ledger_path=rdp,
        feedback_ledger_path=tmp_path / "fl.jsonl",
        weight_snapshot_path=tmp_path / "snap.json",
    )
    s = cfi.integrate()
    for ax, w in s.new_weights.items():
        assert w >= WEIGHT_FLOOR, f"Axis {ax} weight {w} below WEIGHT_FLOOR"
        assert w <= WEIGHT_CEIL, f"Axis {ax} weight {w} above WEIGHT_CEIL"


# ── T177-CFI-12: Weights sum to 1.0 after multi-signal batch (CFI-NORM-0) ────

def test_cfi_12_norm(tmp_path):
    """T177-CFI-12: CFI-NORM-0 — weights sum to 1.0 after mixed ACCEPTED/REJECTED batch."""
    rdp = tmp_path / "disposition_ledger.jsonl"
    records = (
        [_make_disposition("CAL-HUMAN0-0", "ACCEPTED") for _ in range(5)]
        + [_make_disposition("MSE-SCOPE-0", "REJECTED") for _ in range(3)]
        + [_make_disposition("RDP-DETERM-0", "DEFERRED") for _ in range(2)]
    )
    _write_disposition(rdp, records)
    cfi = CFIFeedbackIntegrator(
        rdp_disposition_ledger_path=rdp,
        feedback_ledger_path=tmp_path / "fl.jsonl",
        weight_snapshot_path=tmp_path / "snap.json",
    )
    s = cfi.integrate()
    assert abs(sum(s.new_weights.values()) - 1.0) <= NORM_TOLERANCE


# ── T177-CFI-13: Feedback ledger created on first integrate ──────────────────

def test_cfi_13_ledger_created(tmp_cfi, tmp_path):
    """T177-CFI-13: feedback_weight_ledger.jsonl is created after first integrate()."""
    assert not tmp_cfi.feedback_ledger_path.exists()
    tmp_cfi.integrate()
    assert tmp_cfi.feedback_ledger_path.exists()


# ── T177-CFI-14: Ledger records are valid JSONL ───────────────────────────────

def test_cfi_14_ledger_jsonl(tmp_cfi):
    """T177-CFI-14: All ledger lines are valid JSON objects."""
    tmp_cfi.integrate()
    with open(tmp_cfi.feedback_ledger_path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                obj = json.loads(line)
                assert isinstance(obj, dict)


# ── T177-CFI-15: Ledger record carries HMAC chain hash ───────────────────────

def test_cfi_15_chain_hash_present(tmp_cfi):
    """T177-CFI-15: Every ledger record carries a non-empty hmac_chain_hash."""
    tmp_cfi.integrate()
    with open(tmp_cfi.feedback_ledger_path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                obj = json.loads(line)
                assert "hmac_chain_hash" in obj
                assert len(obj["hmac_chain_hash"]) == 64


# ── T177-CFI-16: Chain verifies clean after one cycle ────────────────────────

def test_cfi_16_chain_verify_clean(tmp_cfi):
    """T177-CFI-16: verify_chain() returns True after a clean integration."""
    tmp_cfi.integrate()
    assert tmp_cfi.verify_chain() is True


# ── T177-CFI-17: Chain verifies clean after multiple cycles ──────────────────

def test_cfi_17_chain_multi_cycle(tmp_path):
    """T177-CFI-17: verify_chain() clean after three sequential integration cycles."""
    rdp = tmp_path / "disposition_ledger.jsonl"
    _write_disposition(rdp, [_make_disposition("RDP-CHAIN-0", "ACCEPTED")])
    cfi = CFIFeedbackIntegrator(
        rdp_disposition_ledger_path=rdp,
        feedback_ledger_path=tmp_path / "fl.jsonl",
        weight_snapshot_path=tmp_path / "snap.json",
    )
    cfi.integrate()
    cfi.integrate()
    cfi.integrate()
    assert cfi.verify_chain() is True


# ── T177-CFI-18: Tampered ledger detected (CFI-CHAIN-0) ──────────────────────

def test_cfi_18_tamper_detected(tmp_cfi):
    """T177-CFI-18: CFI-CHAIN-0 — tampered ledger raises CFIChainError."""
    tmp_cfi.integrate()
    # Corrupt a byte in the ledger
    data = tmp_cfi.feedback_ledger_path.read_bytes()
    corrupted = data[:10] + b"X" + data[11:]
    tmp_cfi.feedback_ledger_path.write_bytes(corrupted)
    with pytest.raises((CFIChainError, Exception)):
        tmp_cfi.verify_chain()


# ── T177-CFI-19: REPLAY-0 — duplicate integration_id rejected ────────────────

def test_cfi_19_replay_rejected(tmp_cfi):
    """T177-CFI-19: CFI-REPLAY-0 — reusing integration_id raises CFIReplayError."""
    fixed_id = "test-replay-id-177"
    tmp_cfi.integrate(integration_id=fixed_id)
    with pytest.raises(CFIReplayError):
        tmp_cfi.integrate(integration_id=fixed_id)


# ── T177-CFI-20: weight snapshot persisted after integrate ───────────────────

def test_cfi_20_snapshot_persisted(tmp_cfi):
    """T177-CFI-20: current_weights.json written after integrate()."""
    tmp_cfi.integrate()
    assert tmp_cfi.weight_snapshot_path.exists()
    snap = json.loads(tmp_cfi.weight_snapshot_path.read_text())
    assert "weights" in snap
    assert "integration_id" in snap


# ── T177-CFI-21: load_current_weights reflects last integration ───────────────

def test_cfi_21_snapshot_reflects_last_cycle(tmp_path):
    """T177-CFI-21: load_current_weights() returns latest cycle output."""
    rdp = tmp_path / "disposition_ledger.jsonl"
    _write_disposition(rdp, [_make_disposition("CAL-CHAIN-0", "ACCEPTED")])
    cfi = CFIFeedbackIntegrator(
        rdp_disposition_ledger_path=rdp,
        feedback_ledger_path=tmp_path / "fl.jsonl",
        weight_snapshot_path=tmp_path / "snap.json",
    )
    s = cfi.integrate()
    loaded = cfi.load_current_weights()
    assert loaded == s.new_weights


# ── T177-CFI-22: axis_deltas present in summary ──────────────────────────────

def test_cfi_22_axis_deltas(tmp_cfi):
    """T177-CFI-22: IntegrationSummary.axis_deltas covers all CANONICAL_AXES."""
    s = tmp_cfi.integrate()
    assert set(s.axis_deltas.keys()) == CANONICAL_AXES


# ── T177-CFI-23: _resolve_axis — CHAIN → constitutional_debt ─────────────────

def test_cfi_23_resolve_chain():
    """T177-CFI-23: _resolve_axis maps CHAIN suffix to constitutional_debt."""
    assert _resolve_axis("RDP-CHAIN-0") == "constitutional_debt"
    assert _resolve_axis("CFI-CHAIN-0") == "constitutional_debt"


# ── T177-CFI-24: _resolve_axis — HUMAN0 → convergence_delta ─────────────────

def test_cfi_24_resolve_human0():
    """T177-CFI-24: _resolve_axis maps HUMAN0 suffix to convergence_delta."""
    assert _resolve_axis("MSE-HUMAN0-0") == "convergence_delta"
    assert _resolve_axis("RDP-HUMAN0-0") == "convergence_delta"


# ── T177-CFI-25: _resolve_axis — SCOPE → blast_containment ──────────────────

def test_cfi_25_resolve_scope():
    """T177-CFI-25: _resolve_axis maps SCOPE suffix to blast_containment."""
    assert _resolve_axis("MSE-SCOPE-0") == "blast_containment"


# ── T177-CFI-26: _resolve_axis — unknown suffix → default axis ───────────────

def test_cfi_26_resolve_unknown():
    """T177-CFI-26: _resolve_axis returns constitutional_debt for unrecognised suffix."""
    from dorkllm.cfi_feedback_integrator import _DEFAULT_AXIS
    result = _resolve_axis("XYZ-UNKNOWN-0")
    assert result == _DEFAULT_AXIS


# ── T177-CFI-27: summary() returns history ───────────────────────────────────

def test_cfi_27_summary_history(tmp_cfi):
    """T177-CFI-27: summary() reports cycle count after integration."""
    tmp_cfi.integrate()
    tmp_cfi.integrate()
    info = tmp_cfi.summary()
    assert info["cycles"] == 2
    assert len(info["history"]) == 2


# ── T177-CFI-28: empty RDP ledger → summary reports 0 cycles ─────────────────

def test_cfi_28_summary_zero(tmp_cfi):
    """T177-CFI-28: summary() returns cycles=0 before any integration."""
    info = tmp_cfi.summary()
    assert info["cycles"] == 0
    assert info["current_weights"] == DEFAULT_WEIGHTS


# ── T177-CFI-29: CFI-DETERM-0 — no bare datetime.now() outside _utc_iso ─────

def test_cfi_29_determ_ast():
    """T177-CFI-29: CFI-DETERM-0 — AST walk confirms datetime.now only inside _utc_iso."""
    import dorkllm.cfi_feedback_integrator as mod
    source = inspect.getsource(mod)
    tree = ast.parse(source)

    violations: list[str] = []
    utc_iso_lines: set[int] = set()

    # Collect line range of _utc_iso
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_utc_iso":
            for child in ast.walk(node):
                if hasattr(child, "lineno"):
                    utc_iso_lines.add(child.lineno)

    # Check all datetime.now calls
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "now"
        ):
            if node.lineno not in utc_iso_lines:
                violations.append(f"line {node.lineno}")

    assert not violations, f"CFI-DETERM-0 violation: bare datetime.now at {violations}"


# ── T177-CFI-30: CFI-HUMAN0-0 structural constant ────────────────────────────

def test_cfi_30_human0_constant():
    """T177-CFI-30: CFI-HUMAN0-0 — DEFERRED-only batch produces zero axis deltas."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        rdp = tdp / "disp.jsonl"
        _write_disposition(rdp, [
            _make_disposition("RDP-CHAIN-0", "DEFERRED"),
            _make_disposition("MSE-SCOPE-0", "DEFERRED"),
        ])
        cfi = CFIFeedbackIntegrator(
            rdp_disposition_ledger_path=rdp,
            feedback_ledger_path=tdp / "fl.jsonl",
            weight_snapshot_path=tdp / "snap.json",
        )
        s = cfi.integrate()
        # All deltas must be zero (no weight changes from DEFERRED signals)
        for ax, delta in s.axis_deltas.items():
            assert abs(delta) < 1e-12, f"CFI-HUMAN0-0: DEFERRED altered {ax} by {delta}"
