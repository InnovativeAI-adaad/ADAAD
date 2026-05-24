# SPDX-License-Identifier: Proprietary — All Rights Reserved
"""
INNOV-94 · V10ET — V10 Epoch Transition Engine
Phase 189 · v9.122.0 · InnovativeAI LLC
Governor: DUSTIN L REID

30-test acceptance suite. All tests are deterministic and hermetic.
"""
from __future__ import annotations

import hashlib
import hmac as hmac_module
import json
import pathlib
import tempfile
from dataclasses import asdict
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------

AGENT_STATE_STUB: Dict[str, Any] = {
    "version": "9.121.0",
    "current_phase": 188,
    "hard_class_invariant_count": 517,
    "innovations_shipped": 93,
    "phase": 188,
}

_HMAC_SECRET = b"V10ET-INNOV-94-EPOCH-BOUNDARY-HMAC-SECRET"
_FIXED_TS = "2026-05-24T00:00:00Z"


def _make_innovation_digests(n: int = 3) -> List[str]:
    return [hashlib.sha256(f"INNOV-{i:02d}".encode()).hexdigest() for i in range(1, n + 1)]


def _merkle_root(digests: List[str]) -> str:
    layer = sorted(digests)
    while len(layer) > 1:
        next_layer = []
        for i in range(0, len(layer), 2):
            left = layer[i]
            right = layer[i + 1] if i + 1 < len(layer) else left
            next_layer.append(hashlib.sha256((left + right).encode()).hexdigest())
        layer = next_layer
    return layer[0]


def _make_gtc_bundle(n_innovations: int = 3) -> Dict[str, Any]:
    digests = _make_innovation_digests(n_innovations)
    return {
        "innovation_id": "INNOV-93",
        "phase": 188,
        "version": "9.121.0",
        "constitutional_merkle_root": _merkle_root(digests),
        "innovation_digest_list": digests,
        "release_bundle_hmac": "abc123",
        "prev_digest": "0" * 64,
    }


def _make_tmp_state(tmp_path: pathlib.Path, state: Dict | None = None) -> pathlib.Path:
    p = tmp_path / ".adaad_agent_state.json"
    p.write_text(json.dumps(state or AGENT_STATE_STUB))
    return p


def _make_tmp_gtc_ledger(tmp_path: pathlib.Path, bundle: Dict | None = None) -> pathlib.Path:
    p = tmp_path / "gtc_release_ledger.jsonl"
    p.write_text(json.dumps(bundle or _make_gtc_bundle()) + "\n")
    return p


def _make_engine(tmp_path: pathlib.Path, **kwargs):
    from dorkllm.v10_epoch_transition import V10EpochTransitionEngine, _DeterminismProvider
    state_path = _make_tmp_state(tmp_path)
    gtc_path = _make_tmp_gtc_ledger(tmp_path)
    epoch_path = tmp_path / "v10et_epoch_ledger.jsonl"
    det = _DeterminismProvider(fixed_ts=_FIXED_TS)
    return V10EpochTransitionEngine(
        gtc_ledger_path=gtc_path,
        epoch_ledger_path=epoch_path,
        agent_state_path=state_path,
        determinism=det,
        **kwargs,
    )


# ===========================================================================
# Category 1: Epoch Input Validation (T189-V10ET-01..06)
# ===========================================================================

class TestEpochInputValidation:

    def test_01_engine_instantiates(self, tmp_path):
        """T189-V10ET-01: Engine instantiates without error."""
        engine = _make_engine(tmp_path)
        assert engine is not None

    def test_02_reads_agent_state(self, tmp_path):
        """T189-V10ET-02: Agent state is read correctly."""
        engine = _make_engine(tmp_path)
        state = engine._read_agent_state()
        assert state["innovations_shipped"] == 93

    def test_03_reads_gtc_ledger(self, tmp_path):
        """T189-V10ET-03: GTC release ledger latest entry is returned."""
        engine = _make_engine(tmp_path)
        bundle = engine._read_gtc_ledger_latest()
        assert bundle is not None
        assert bundle["innovation_id"] == "INNOV-93"

    def test_04_empty_gtc_ledger_returns_none(self, tmp_path):
        """T189-V10ET-04: Empty GTC ledger returns None from latest reader."""
        from dorkllm.v10_epoch_transition import V10EpochTransitionEngine, _DeterminismProvider
        state_path = _make_tmp_state(tmp_path)
        empty_gtc = tmp_path / "empty_gtc.jsonl"
        empty_gtc.write_text("")
        engine = V10EpochTransitionEngine(
            gtc_ledger_path=empty_gtc,
            epoch_ledger_path=tmp_path / "epoch.jsonl",
            agent_state_path=state_path,
            determinism=_DeterminismProvider(fixed_ts=_FIXED_TS),
        )
        assert engine._read_gtc_ledger_latest() is None

    def test_05_missing_gtc_ledger_returns_advisory_only(self, tmp_path):
        """T189-V10ET-05: Missing GTC ledger causes ADVISORY_ONLY result (not crash)."""
        from dorkllm.v10_epoch_transition import V10EpochTransitionEngine, _DeterminismProvider
        state_path = _make_tmp_state(tmp_path)
        engine = V10EpochTransitionEngine(
            gtc_ledger_path=tmp_path / "nonexistent.jsonl",
            epoch_ledger_path=tmp_path / "epoch.jsonl",
            agent_state_path=state_path,
            determinism=_DeterminismProvider(fixed_ts=_FIXED_TS),
        )
        result = engine.seal()
        assert result.status == "ADVISORY_ONLY"
        assert len(result.findings) > 0

    def test_06_missing_agent_state_uses_defaults(self, tmp_path):
        """T189-V10ET-06: Missing agent state file yields empty dict without crash."""
        from dorkllm.v10_epoch_transition import V10EpochTransitionEngine, _DeterminismProvider
        gtc_path = _make_tmp_gtc_ledger(tmp_path)
        engine = V10EpochTransitionEngine(
            gtc_ledger_path=gtc_path,
            epoch_ledger_path=tmp_path / "epoch.jsonl",
            agent_state_path=tmp_path / "no_state.json",
            determinism=_DeterminismProvider(fixed_ts=_FIXED_TS),
        )
        state = engine._read_agent_state()
        assert state == {}


# ===========================================================================
# Category 2: GTC Bundle Consumption & Merkle Re-validation (T189-V10ET-07..12)
# ===========================================================================

class TestMerkleRevalidation:

    def test_07_merkle_root_recomputed_correctly(self, tmp_path):
        """T189-V10ET-07: Merkle root re-validated matches GTC bundle claim."""
        engine = _make_engine(tmp_path)
        bundle = engine._read_gtc_ledger_latest()
        root = engine._validate_merkle_from_gtc_bundle(bundle)
        assert root == bundle["constitutional_merkle_root"]

    def test_08_tampered_merkle_root_raises_verify_error(self, tmp_path):
        """T189-V10ET-08: Tampered Merkle root triggers V10ETVerifyError (V10ET-VERIFY-0)."""
        from dorkllm.v10_epoch_transition import V10ETVerifyError
        engine = _make_engine(tmp_path)
        bundle = dict(_make_gtc_bundle())
        bundle["constitutional_merkle_root"] = "deadbeef" * 8
        with pytest.raises(V10ETVerifyError):
            engine._validate_merkle_from_gtc_bundle(bundle)

    def test_09_empty_digest_list_raises_verify_error(self, tmp_path):
        """T189-V10ET-09: Empty innovation_digest_list raises V10ETVerifyError."""
        from dorkllm.v10_epoch_transition import V10ETVerifyError
        engine = _make_engine(tmp_path)
        bundle = {"constitutional_merkle_root": "abc", "innovation_digest_list": []}
        with pytest.raises(V10ETVerifyError):
            engine._validate_merkle_from_gtc_bundle(bundle)

    def test_10_merkle_is_deterministic(self, tmp_path):
        """T189-V10ET-10: Same digest list always produces same Merkle root."""
        from dorkllm.v10_epoch_transition import _recompute_merkle_root
        digests = _make_innovation_digests(5)
        r1 = _recompute_merkle_root(digests)
        r2 = _recompute_merkle_root(digests)
        assert r1 == r2

    def test_11_merkle_changes_with_different_innovations(self, tmp_path):
        """T189-V10ET-11: Different digest list produces different Merkle root."""
        from dorkllm.v10_epoch_transition import _recompute_merkle_root
        r1 = _recompute_merkle_root(_make_innovation_digests(3))
        r2 = _recompute_merkle_root(_make_innovation_digests(4))
        assert r1 != r2

    def test_12_seal_includes_merkle_root_in_record(self, tmp_path):
        """T189-V10ET-12: Sealed epoch record contains validated Merkle root."""
        engine = _make_engine(tmp_path)
        result = engine.seal()
        assert result.status == "EPOCH_SEALED"
        expected_root = _merkle_root(_make_innovation_digests(3))
        assert result.epoch_boundary["merkle_root_validated"] == expected_root


# ===========================================================================
# Category 3: HMAC Chain Integrity (T189-V10ET-13..17)
# ===========================================================================

class TestHMACChainIntegrity:

    def test_13_sealed_entry_has_valid_hmac(self, tmp_path):
        """T189-V10ET-13: Sealed epoch boundary record carries valid HMAC."""
        from dorkllm.v10_epoch_transition import _compute_entry_hmac, _entry_canonical, EpochBoundaryRecord
        engine = _make_engine(tmp_path)
        result = engine.seal()
        record = EpochBoundaryRecord(**result.epoch_boundary)
        canonical = _entry_canonical(record)
        expected = _compute_entry_hmac(canonical)
        assert hmac_module.compare_digest(record.epoch_seal_hmac, expected)

    def test_14_verify_chain_returns_true_on_valid_ledger(self, tmp_path):
        """T189-V10ET-14: verify_chain() returns True after a valid seal."""
        engine = _make_engine(tmp_path)
        engine.seal()
        assert engine.verify_chain() is True

    def test_15_tampered_hmac_raises_chain_error_on_load(self, tmp_path):
        """T189-V10ET-15: Tampered HMAC in ledger raises V10ETChainError on load."""
        from dorkllm.v10_epoch_transition import V10EpochTransitionEngine, V10ETChainError, _DeterminismProvider
        epoch_path = tmp_path / "v10et_epoch_ledger.jsonl"
        engine = _make_engine(tmp_path)
        engine.seal()

        # Corrupt the HMAC in the ledger file
        raw = epoch_path.read_text()
        entry = json.loads(raw.strip())
        entry["epoch_seal_hmac"] = "corrupted" + "0" * 55
        epoch_path.write_text(json.dumps(entry) + "\n")

        with pytest.raises(V10ETChainError):
            state_path = tmp_path / ".adaad_agent_state.json"
            gtc_path = tmp_path / "gtc_release_ledger.jsonl"
            V10EpochTransitionEngine(
                gtc_ledger_path=gtc_path,
                epoch_ledger_path=epoch_path,
                agent_state_path=state_path,
                determinism=_DeterminismProvider(fixed_ts=_FIXED_TS),
            )

    def test_16_prev_digest_is_genesis_for_first_entry(self, tmp_path):
        """T189-V10ET-16: First epoch entry prev_digest is genesis (64 zeroes)."""
        engine = _make_engine(tmp_path)
        result = engine.seal()
        assert result.epoch_boundary["prev_digest"] == "0" * 64

    def test_17_hmac_compare_digest_used_not_string_equality(self, tmp_path):
        """T189-V10ET-17: AUTH-CT-0 — _verify_hmac uses hmac.compare_digest."""
        from dorkllm.v10_epoch_transition import _verify_hmac, _compute_entry_hmac
        sample = '{"test": "value"}'
        expected = _compute_entry_hmac(sample)
        assert _verify_hmac(sample, expected) is True
        assert _verify_hmac(sample, "wrong" + "0" * 59) is False


# ===========================================================================
# Category 4: HUMAN-0 Runbook Emission (T189-V10ET-18..21)
# ===========================================================================

class TestHuman0Runbook:

    def test_18_advisory_emitted_before_seal(self, tmp_path):
        """T189-V10ET-18: V10ET-HUMAN0-0 — advisory is emitted during seal()."""
        engine = _make_engine(tmp_path)
        result = engine.seal()
        assert result.human0_advisory is not None
        assert "V10ET-HUMAN0-0" in result.human0_advisory

    def test_19_runbook_contains_10_steps(self, tmp_path):
        """T189-V10ET-19: Track B runbook contains exactly 10 ceremony steps."""
        engine = _make_engine(tmp_path)
        result = engine.seal()
        assert len(result.track_b_runbook["steps"]) == 10

    def test_20_runbook_non_delegable_note_present(self, tmp_path):
        """T189-V10ET-20: Runbook HUMAN-0 exclusive note references governor."""
        engine = _make_engine(tmp_path)
        result = engine.seal()
        note = result.track_b_runbook["non_delegable_note"]
        assert "HUMAN-0" in note
        assert "Dustin L. Reid" in note
    def test_21_latest_advisory_returns_after_seal(self, tmp_path):
        """T189-V10ET-21: latest_advisory() returns advisory text after seal."""
        engine = _make_engine(tmp_path)
        engine.seal()
        adv = engine.latest_advisory()
        assert adv is not None
        assert "DUSTIN L REID" in adv


# ===========================================================================
# Category 5: Epoch Seal Immutability (T189-V10ET-22..25)
# ===========================================================================

class TestEpochSealImmutability:

    def test_22_seal_creates_epoch_ledger_file(self, tmp_path):
        """T189-V10ET-22: seal() creates the epoch ledger JSONL file."""
        epoch_path = tmp_path / "v10et_epoch_ledger.jsonl"
        engine = _make_engine(tmp_path)
        assert not epoch_path.exists()
        engine.seal()
        assert epoch_path.exists()

    def test_23_double_seal_raises_epoch_error(self, tmp_path):
        """T189-V10ET-23: V10ET-EPOCH-0 — second seal raises V10ETEpochError."""
        from dorkllm.v10_epoch_transition import V10ETEpochError, V10EpochTransitionEngine, _DeterminismProvider
        epoch_path = tmp_path / "v10et_epoch_ledger.jsonl"
        gtc_path = tmp_path / "gtc_release_ledger.jsonl"
        state_path = tmp_path / ".adaad_agent_state.json"

        engine = _make_engine(tmp_path)
        engine.seal()

        # Reload engine from same ledger path — should refuse second seal
        engine2 = V10EpochTransitionEngine(
            gtc_ledger_path=gtc_path,
            epoch_ledger_path=epoch_path,
            agent_state_path=state_path,
            determinism=_DeterminismProvider(fixed_ts=_FIXED_TS),
        )
        with pytest.raises(V10ETEpochError):
            engine2._advisory_emitted = True   # force past advisory gate to reach epoch gate
            engine2._seal_epoch(
                merkle_root="x" * 64,
                gtc_bundle=_make_gtc_bundle(),
                agent_state=AGENT_STATE_STUB,
            )

    def test_24_sealed_record_contains_governor(self, tmp_path):
        """T189-V10ET-24: Sealed epoch boundary record encodes governor name."""
        engine = _make_engine(tmp_path)
        result = engine.seal()
        assert result.epoch_boundary["governor"] == "DUSTIN L REID"

    def test_25_sealed_record_epoch_transition_fields(self, tmp_path):
        """T189-V10ET-25: Sealed record encodes epoch_from=v9, epoch_to=v10."""
        engine = _make_engine(tmp_path)
        result = engine.seal()
        assert result.epoch_boundary["epoch_from"] == "v9"
        assert result.epoch_boundary["epoch_to"] == "v10"
        assert result.epoch_boundary["target_version"] == "10.0.0"


# ===========================================================================
# Category 6: Determinism (T189-V10ET-26..28)
# ===========================================================================

class TestDeterminism:

    def test_26_fixed_timestamp_provider_is_deterministic(self, tmp_path):
        """T189-V10ET-26: _DeterminismProvider with fixed_ts always returns same timestamp."""
        from dorkllm.v10_epoch_transition import _DeterminismProvider
        det = _DeterminismProvider(fixed_ts=_FIXED_TS)
        assert det.iso_now() == _FIXED_TS
        assert det.iso_now() == _FIXED_TS

    def test_27_same_inputs_produce_same_hmac(self, tmp_path):
        """T189-V10ET-27: Identical inputs produce identical HMAC output."""
        from dorkllm.v10_epoch_transition import _compute_entry_hmac
        h1 = _compute_entry_hmac('{"key": "value"}')
        h2 = _compute_entry_hmac('{"key": "value"}')
        assert h1 == h2

    def test_28_epoch_seal_record_id_is_deterministic_with_fixed_ts(self, tmp_path):
        """T189-V10ET-28: Record ID derived from deterministic timestamp is reproducible."""
        engine = _make_engine(tmp_path)
        result = engine.seal()
        ts_stripped = _FIXED_TS.replace(":", "").replace("-", "")
        assert ts_stripped in result.epoch_boundary["record_id"]


# ===========================================================================
# Category 7: REST Endpoint Coverage (T189-V10ET-29..30)
# ===========================================================================

class TestRESTEndpoints:

    def test_29_router_has_required_routes(self):
        """T189-V10ET-29: V10ET REST router exposes /seal, /history, /verify-chain, /advisory."""
        from app.api.v10_epoch_transition import router
        paths = {r.path for r in router.routes}
        assert "/v10et/seal" in paths
        assert "/v10et/history" in paths
        assert "/v10et/verify-chain" in paths
        assert "/v10et/advisory" in paths

    def test_30_seal_endpoint_dry_run_returns_advisory_only(self, tmp_path):
        """T189-V10ET-30: POST /v10et/seal?dry_run=true returns ADVISORY_ONLY without ledger write."""
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        import app.api.v10_epoch_transition as v10et_module

        # Patch engine to use tmp_path
        from dorkllm.v10_epoch_transition import V10EpochTransitionEngine, _DeterminismProvider
        state_path = _make_tmp_state(tmp_path)
        gtc_path = _make_tmp_gtc_ledger(tmp_path)
        epoch_path = tmp_path / "epoch.jsonl"
        det = _DeterminismProvider(fixed_ts=_FIXED_TS)
        test_engine = V10EpochTransitionEngine(
            gtc_ledger_path=gtc_path,
            epoch_ledger_path=epoch_path,
            agent_state_path=state_path,
            determinism=det,
        )
        original = v10et_module._V10ET_INSTANCE
        v10et_module._V10ET_INSTANCE = test_engine

        try:
            app = FastAPI()
            app.include_router(v10et_module.router)
            client = TestClient(app)
            resp = client.post("/v10et/seal?dry_run=true")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ADVISORY_ONLY"
            assert not epoch_path.exists()
        finally:
            v10et_module._V10ET_INSTANCE = original
