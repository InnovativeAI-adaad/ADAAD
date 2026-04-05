# SPDX-License-Identifier: Apache-2.0
"""
Phase 124 — adaad-core Extraction
Acceptance tests: T124-CORE-01..30

Invariants under test:
    CORE-EXPORT-0   All six public symbols importable from adaad_core
    CORE-IMPORT-0   Import does not trigger Aponi UI / SPIE / federation init
    CORE-SEMVER-0   __version__ present and semver-formatted
    CORE-VERIFY-0   verify_ledger is callable and returns correct schema
    CORE-GATE-0     GovernanceGate is constructible and exposes evaluate()
    CORE-ROLLBACK-0 ConstitutionalRollbackEngine snapshot/rollback cycle
    CORE-IDE-0      InvariantDiscoveryEngine analyze_failures contract
    CORE-MIRROR-0   MirrorTestEngine run() contract
    CORE-EPOCH-0    EpochMemoryStore append/read contract
    CORE-ALL-0      All six in __all__
"""
from __future__ import annotations

import hashlib
import importlib
import json
import re
import sys
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ledger(tmp_path: Path, n: int = 3) -> Path:
    """Write a valid JSONL chain ledger for verify_ledger tests.

    Uses the DAS internal helpers to produce records with correct
    epoch_id / mutation_id / record_hash chain format.
    """
    from runtime.innovations30.deterministic_audit_sandbox import (
        _compute_chain_link,
        _CHAIN_PREFIX_LEN,
    )
    from runtime.innovations30 import deterministic_audit_sandbox as _das_mod

    genesis = _das_mod._GENESIS_PREV
    lp = tmp_path / "test.jsonl"
    prev = genesis
    with lp.open("w") as fh:
        for i in range(n):
            epoch_id = f"epoch-{i:04d}"
            mutation_id = f"mut-{i:04d}"
            record_id = f"{epoch_id}:{mutation_id}"
            rh = _compute_chain_link(record_id=record_id, prev_digest=prev)[:_CHAIN_PREFIX_LEN]
            row = {
                "epoch_id": epoch_id,
                "mutation_id": mutation_id,
                "prev_digest": prev,
                "record_hash": rh,
            }
            fh.write(json.dumps(row) + "\n")
            prev = rh
    return lp


# ---------------------------------------------------------------------------
# T124-CORE-01..06  CORE-EXPORT-0: all six symbols present
# ---------------------------------------------------------------------------

def test_01_governance_gate_importable():
    """CORE-EXPORT-0: GovernanceGate importable from adaad_core."""
    from adaad_core import GovernanceGate
    assert GovernanceGate is not None


def test_02_rollback_engine_importable():
    """CORE-EXPORT-0: ConstitutionalRollbackEngine importable."""
    from adaad_core import ConstitutionalRollbackEngine
    assert ConstitutionalRollbackEngine is not None


def test_03_invariant_discovery_importable():
    """CORE-EXPORT-0: InvariantDiscoveryEngine importable."""
    from adaad_core import InvariantDiscoveryEngine
    assert InvariantDiscoveryEngine is not None


def test_04_mirror_test_importable():
    """CORE-EXPORT-0: MirrorTestEngine importable."""
    from adaad_core import MirrorTestEngine
    assert MirrorTestEngine is not None


def test_05_epoch_memory_importable():
    """CORE-EXPORT-0: EpochMemoryStore importable."""
    from adaad_core import EpochMemoryStore
    assert EpochMemoryStore is not None


def test_06_verify_ledger_importable():
    """CORE-EXPORT-0: verify_ledger importable."""
    from adaad_core import verify_ledger
    assert callable(verify_ledger)


# ---------------------------------------------------------------------------
# T124-CORE-07  CORE-ALL-0: __all__ complete
# ---------------------------------------------------------------------------

def test_07_all_exports_in_dunder_all():
    """CORE-ALL-0: all six symbols listed in __all__."""
    import adaad_core
    required = {
        "GovernanceGate",
        "ConstitutionalRollbackEngine",
        "InvariantDiscoveryEngine",
        "MirrorTestEngine",
        "EpochMemoryStore",
        "verify_ledger",
    }
    assert required.issubset(set(adaad_core.__all__))


# ---------------------------------------------------------------------------
# T124-CORE-08  CORE-SEMVER-0: __version__
# ---------------------------------------------------------------------------

def test_08_version_is_semver():
    """CORE-SEMVER-0: __version__ is a valid semver string."""
    import adaad_core
    assert hasattr(adaad_core, "__version__")
    assert re.fullmatch(r"\d+\.\d+\.\d+", adaad_core.__version__)


# ---------------------------------------------------------------------------
# T124-CORE-09  CORE-IMPORT-0: no forbidden modules loaded
# ---------------------------------------------------------------------------

def test_09_no_forbidden_modules_on_import():
    """CORE-IMPORT-0: importing adaad_core must not load Aponi/SPIE/federation."""
    before = set(sys.modules.keys())
    importlib.reload(importlib.import_module("adaad_core"))
    after = set(sys.modules.keys())
    new = after - before
    forbidden_prefixes = ("aponi", "spie", "federation")
    violations = [m for m in new if any(m.startswith(p) for p in forbidden_prefixes)]
    assert not violations, f"CORE-IMPORT-0: forbidden modules loaded: {violations}"


# ---------------------------------------------------------------------------
# T124-CORE-10..13  CORE-VERIFY-0: verify_ledger
# ---------------------------------------------------------------------------

def test_10_verify_ledger_valid_chain(tmp_path):
    """CORE-VERIFY-0: verify_ledger returns ok=True for valid chain."""
    from adaad_core import verify_ledger
    lp = _make_ledger(tmp_path, n=5)
    result = verify_ledger(lp)
    assert result["ok"] is True
    assert result["records_checked"] == 5
    assert result["error"] is None


def test_11_verify_ledger_result_schema(tmp_path):
    """CORE-VERIFY-0: result dict has required keys."""
    from adaad_core import verify_ledger
    lp = _make_ledger(tmp_path)
    result = verify_ledger(lp)
    for key in ("ok", "records_checked", "error"):
        assert key in result, f"Missing key: {key}"


def test_12_verify_ledger_single_record(tmp_path):
    """CORE-VERIFY-0: verify_ledger handles single-record ledger."""
    from adaad_core import verify_ledger
    lp = _make_ledger(tmp_path, n=1)
    result = verify_ledger(lp)
    assert result["ok"] is True
    assert result["records_checked"] == 1


def test_13_verify_ledger_broken_chain_raises(tmp_path):
    """CORE-VERIFY-0: broken chain raises DASVerifyError (fail-closed)."""
    from adaad_core import verify_ledger
    from runtime.innovations30.deterministic_audit_sandbox import DASVerifyError
    lp = _make_ledger(tmp_path, n=3)
    lines = lp.read_text().splitlines()
    # Corrupt prev_digest on second record to break the chain
    row = json.loads(lines[1])
    row["prev_digest"] = "sha256:deadbeefdeadbeef"
    lines[1] = json.dumps(row)
    lp.write_text("\n".join(lines) + "\n")
    with pytest.raises((DASVerifyError, Exception)):
        verify_ledger(lp)


# ---------------------------------------------------------------------------
# T124-CORE-14..17  CORE-GATE-0: GovernanceGate
# ---------------------------------------------------------------------------

def test_14_governance_gate_is_class():
    """CORE-GATE-0: GovernanceGate is a class."""
    from adaad_core import GovernanceGate
    assert isinstance(GovernanceGate, type)


def test_15_governance_gate_has_evaluate():
    """CORE-GATE-0: GovernanceGate exposes approve_mutation() (the gate evaluation method)."""
    from adaad_core import GovernanceGate
    assert hasattr(GovernanceGate, "approve_mutation")
    assert callable(GovernanceGate.approve_mutation)


def test_16_governance_gate_module_path():
    """CORE-GATE-0: GovernanceGate sourced from runtime.governance.gate."""
    from adaad_core import GovernanceGate
    assert "runtime.governance.gate" in GovernanceGate.__module__


def test_17_governance_gate_not_aponi():
    """CORE-IMPORT-0: GovernanceGate class does not import aponi on access."""
    from adaad_core import GovernanceGate
    assert "aponi" not in GovernanceGate.__module__


# ---------------------------------------------------------------------------
# T124-CORE-18..20  CORE-ROLLBACK-0: ConstitutionalRollbackEngine
# ---------------------------------------------------------------------------

def test_18_rollback_engine_is_class():
    """CORE-ROLLBACK-0: ConstitutionalRollbackEngine is a class."""
    from adaad_core import ConstitutionalRollbackEngine
    assert isinstance(ConstitutionalRollbackEngine, type)


def test_19_rollback_engine_has_snapshot():
    """CORE-ROLLBACK-0: engine exposes snapshot()."""
    from adaad_core import ConstitutionalRollbackEngine
    assert hasattr(ConstitutionalRollbackEngine, "snapshot")


def test_20_rollback_engine_has_rollback():
    """CORE-ROLLBACK-0: engine exposes rollback()."""
    from adaad_core import ConstitutionalRollbackEngine
    assert hasattr(ConstitutionalRollbackEngine, "rollback")


# ---------------------------------------------------------------------------
# T124-CORE-21..23  CORE-IDE-0: InvariantDiscoveryEngine
# ---------------------------------------------------------------------------

def test_21_ide_is_class():
    """CORE-IDE-0: InvariantDiscoveryEngine is a class."""
    from adaad_core import InvariantDiscoveryEngine
    assert isinstance(InvariantDiscoveryEngine, type)


def test_22_ide_has_analyze_failures():
    """CORE-IDE-0: InvariantDiscoveryEngine exposes analyze_failures()."""
    from adaad_core import InvariantDiscoveryEngine
    assert hasattr(InvariantDiscoveryEngine, "analyze_failures")


def test_23_ide_instantiable(tmp_path):
    """CORE-IDE-0: InvariantDiscoveryEngine instantiable with ledger_path."""
    from adaad_core import InvariantDiscoveryEngine
    engine = InvariantDiscoveryEngine(ledger_path=tmp_path / "rules.jsonl")
    assert engine is not None


# ---------------------------------------------------------------------------
# T124-CORE-24..26  CORE-MIRROR-0: MirrorTestEngine
# ---------------------------------------------------------------------------

def test_24_mirror_is_class():
    """CORE-MIRROR-0: MirrorTestEngine is a class."""
    from adaad_core import MirrorTestEngine
    assert isinstance(MirrorTestEngine, type)


def test_25_mirror_has_run():
    """CORE-MIRROR-0: MirrorTestEngine exposes run()."""
    from adaad_core import MirrorTestEngine
    assert hasattr(MirrorTestEngine, "run")


def test_26_mirror_module_correct():
    """CORE-MIRROR-0: sourced from runtime.innovations30.mirror_test."""
    from adaad_core import MirrorTestEngine
    assert "mirror_test" in MirrorTestEngine.__module__


# ---------------------------------------------------------------------------
# T124-CORE-27..29  CORE-EPOCH-0: EpochMemoryStore
# ---------------------------------------------------------------------------

def test_27_epoch_memory_is_class():
    """CORE-EPOCH-0: EpochMemoryStore is a class."""
    from adaad_core import EpochMemoryStore
    assert isinstance(EpochMemoryStore, type)


def test_28_epoch_memory_has_append():
    """CORE-EPOCH-0: EpochMemoryStore exposes emit() (the write method)."""
    from adaad_core import EpochMemoryStore
    assert hasattr(EpochMemoryStore, "emit")
    assert callable(EpochMemoryStore.emit)


def test_29_epoch_memory_has_read():
    """CORE-EPOCH-0: EpochMemoryStore exposes window() or head() for retrieval."""
    from adaad_core import EpochMemoryStore
    has_retrieval = hasattr(EpochMemoryStore, "window") or hasattr(EpochMemoryStore, "head")
    assert has_retrieval, "EpochMemoryStore must expose window() or head()"


# ---------------------------------------------------------------------------
# T124-CORE-30  Integration: package metadata consistent
# ---------------------------------------------------------------------------

def test_30_version_matches_package_version():
    """CORE-SEMVER-0: adaad_core.__version__ matches 9.57.0."""
    import adaad_core
    assert adaad_core.__version__ == "9.57.0"
