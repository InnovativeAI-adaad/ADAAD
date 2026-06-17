# SPDX-License-Identifier: Apache-2.0
# INNOV-119 · CGVE — Constitutional Governance Version Enforcer — Test Suite
# Phase 214 · v10.25.0 · InnovativeAI LLC · Governor: DUSTIN L REID
"""
30-test acceptance suite for CGVE.

T214-CGVE-01..30 — covers: surface reading, drift detection, atomic repair,
HMAC chain, invariant enforcement, REST endpoints, human0 advisory, and
edge cases (missing files, corrupt surfaces, chain replay).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_repo(tmp_path: Path) -> Path:
    """Create a minimal repo structure with aligned versions."""
    ver = "10.25.0"
    (tmp_path / "VERSION").write_text(ver + "\n")
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "adaad"\nversion = "{ver}"\n'
    )
    core_dir = tmp_path / "adaad_core"
    core_dir.mkdir()
    (core_dir / "__init__.py").write_text(f'__version__ = "{ver}"\n')
    (core_dir / "pyproject.toml").write_text(
        f'[project]\nname = "adaad-core"\nversion = "{ver}"\n'
    )
    return tmp_path


@pytest.fixture()
def drifted_repo(tmp_path: Path) -> Path:
    """Repo with drift in sub-package surfaces only."""
    ver = "10.25.0"
    (tmp_path / "VERSION").write_text(ver + "\n")
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "adaad"\nversion = "{ver}"\n'
    )
    core_dir = tmp_path / "adaad_core"
    core_dir.mkdir()
    (core_dir / "__init__.py").write_text('__version__ = "10.23.0"\n')
    (core_dir / "pyproject.toml").write_text(
        '[project]\nname = "adaad-core"\nversion = "9.121.0"\n'
    )
    return tmp_path


@pytest.fixture()
def enforcer_clean(tmp_repo: Path, tmp_path: Path):
    from dorkllm.constitutional_governance_version_enforcer import (
        ConstitutionalGovernanceVersionEnforcer,
    )
    ledger = tmp_path / "test_ledger.jsonl"
    return ConstitutionalGovernanceVersionEnforcer(
        repo_root=tmp_repo, ledger_path=ledger, auto_repair=True
    )


@pytest.fixture()
def enforcer_drifted(drifted_repo: Path, tmp_path: Path):
    from dorkllm.constitutional_governance_version_enforcer import (
        ConstitutionalGovernanceVersionEnforcer,
    )
    ledger = tmp_path / "drifted_ledger.jsonl"
    return ConstitutionalGovernanceVersionEnforcer(
        repo_root=drifted_repo, ledger_path=ledger, auto_repair=True
    )


@pytest.fixture()
def client():
    from server import app
    return TestClient(app)


# ── T214-CGVE-01: Module imports cleanly ─────────────────────────────────────

def test_cgve_01_import():
    from dorkllm.constitutional_governance_version_enforcer import (
        ConstitutionalGovernanceVersionEnforcer,
        EnforcementStatus,
        SurfaceReading,
        SurfaceDrift,
        RepairAction,
        EnforcementRecord,
    )
    assert ConstitutionalGovernanceVersionEnforcer is not None


# ── T214-CGVE-02: Compliant repo returns COMPLIANT ───────────────────────────

def test_cgve_02_compliant(enforcer_clean):
    record = enforcer_clean.enforce()
    assert record.status == "COMPLIANT"


# ── T214-CGVE-03: Drifted repo returns REPAIRED ──────────────────────────────

def test_cgve_03_drifted_repaired(enforcer_drifted):
    record = enforcer_drifted.enforce()
    assert record.status == "REPAIRED"


# ── T214-CGVE-04: Drifts detected correctly ──────────────────────────────────

def test_cgve_04_drifts_count(enforcer_drifted):
    record = enforcer_drifted.enforce()
    assert len(record.drifts_detected) == 2  # CORE_INIT + CORE_PYPROJECT


# ── T214-CGVE-05: Sub-package files repaired to canonical ────────────────────

def test_cgve_05_files_repaired(drifted_repo: Path, tmp_path: Path):
    from dorkllm.constitutional_governance_version_enforcer import (
        ConstitutionalGovernanceVersionEnforcer,
    )
    ledger = tmp_path / "l.jsonl"
    eng = ConstitutionalGovernanceVersionEnforcer(
        repo_root=drifted_repo, ledger_path=ledger, auto_repair=True
    )
    eng.enforce()
    init_ver = re.search(
        r'__version__\s*=\s*["\']([^"\']+)["\']',
        (drifted_repo / "adaad_core" / "__init__.py").read_text(),
    ).group(1)
    core_ver = None
    import tomllib
    with open(drifted_repo / "adaad_core" / "pyproject.toml", "rb") as f:
        core_ver = tomllib.load(f)["project"]["version"]
    assert init_ver == "10.25.0"
    assert core_ver == "10.25.0"


# ── T214-CGVE-06: Canonical version is root VERSION ──────────────────────────

def test_cgve_06_canonical_is_root(enforcer_clean):
    record = enforcer_clean.enforce()
    assert record.canonical_version == "10.25.0"


# ── T214-CGVE-07: run_id is deterministic SHA-256 ────────────────────────────

def test_cgve_07_run_id_is_hex(enforcer_clean):
    record = enforcer_clean.enforce()
    assert len(record.run_id) == 64
    int(record.run_id, 16)  # must be valid hex


# ── T214-CGVE-08: HMAC digest is present and non-empty ───────────────────────

def test_cgve_08_hmac_present(enforcer_clean):
    record = enforcer_clean.enforce()
    assert len(record.hmac_digest) == 64


# ── T214-CGVE-09: Ledger file created on first run ───────────────────────────

def test_cgve_09_ledger_created(enforcer_clean, tmp_path: Path):
    enforcer_clean.enforce()
    ledger = tmp_path / "test_ledger.jsonl"
    assert ledger.exists()
    assert ledger.stat().st_size > 0


# ── T214-CGVE-10: Ledger entry is valid JSON ─────────────────────────────────

def test_cgve_10_ledger_json(enforcer_clean, tmp_path: Path):
    enforcer_clean.enforce()
    ledger = tmp_path / "test_ledger.jsonl"
    line = ledger.read_text().strip().splitlines()[-1]
    record = json.loads(line)
    assert "run_id" in record
    assert "canonical_version" in record
    assert "hmac_digest" in record


# ── T214-CGVE-11: Chain verify passes on single entry ────────────────────────

def test_cgve_11_chain_single(enforcer_clean):
    enforcer_clean.enforce()
    result = enforcer_clean.verify_chain()
    assert result["valid"] is True
    assert result["entries"] == 1


# ── T214-CGVE-12: Chain verify passes on multiple entries ────────────────────

def test_cgve_12_chain_multiple(enforcer_clean):
    enforcer_clean.enforce()
    enforcer_clean.enforce()
    enforcer_clean.enforce()
    result = enforcer_clean.verify_chain()
    assert result["valid"] is True
    assert result["entries"] == 3


# ── T214-CGVE-13: Chain breaks when tampered ─────────────────────────────────

def test_cgve_13_chain_tamper(enforcer_clean, tmp_path: Path):
    enforcer_clean.enforce()
    ledger = tmp_path / "test_ledger.jsonl"
    content = ledger.read_text()
    lines = content.strip().splitlines()
    record = json.loads(lines[0])
    record["prev_hmac"] = "TAMPERED" + "0" * 57
    ledger.write_text(json.dumps(record) + "\n")
    enforcer_clean.enforce()
    result = enforcer_clean.verify_chain()
    assert result["valid"] is False


# ── T214-CGVE-14: CGVE-SURFACES-0 — exactly 4 surfaces read ─────────────────

def test_cgve_14_surfaces_count(enforcer_clean):
    record = enforcer_clean.enforce()
    assert len(record.surfaces_read) == 4


# ── T214-CGVE-15: Status endpoint returns correct compliant state ─────────────

def test_cgve_15_status_compliant(enforcer_clean):
    snap = enforcer_clean.status()
    assert snap["compliant"] is True
    assert snap["canonical_version"] == "10.25.0"
    assert len(snap["surfaces"]) == 4


# ── T214-CGVE-16: Status on drifted repo reports non-compliant ───────────────

def test_cgve_16_status_drifted(enforcer_drifted):
    snap = enforcer_drifted.status()
    assert snap["compliant"] is False


# ── T214-CGVE-17: human0_advisory False on sub-package-only drift ────────────

def test_cgve_17_no_human0_on_subpkg(enforcer_drifted):
    record = enforcer_drifted.enforce()
    assert record.human0_advisory is False


# ── T214-CGVE-18: human0_advisory True when root pyproject drifts ────────────

def test_cgve_18_human0_on_root_drift(tmp_path: Path):
    from dorkllm.constitutional_governance_version_enforcer import (
        ConstitutionalGovernanceVersionEnforcer,
    )
    ver = "10.25.0"
    (tmp_path / "VERSION").write_text(ver + "\n")
    # Deliberately drift root pyproject (blast_radius=0)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "adaad"\nversion = "9.0.0"\n'
    )
    core = tmp_path / "adaad_core"
    core.mkdir()
    (core / "__init__.py").write_text(f'__version__ = "{ver}"\n')
    (core / "pyproject.toml").write_text(
        f'[project]\nname = "adaad-core"\nversion = "{ver}"\n'
    )
    ledger = tmp_path / "h0.jsonl"
    eng = ConstitutionalGovernanceVersionEnforcer(
        repo_root=tmp_path, ledger_path=ledger, auto_repair=True
    )
    record = eng.enforce()
    assert record.human0_advisory is True
    assert "HUMAN-0" in (record.human0_message or "")


# ── T214-CGVE-19: BLOCKED status when only root drift and no sub-pkg drift ───

def test_cgve_19_blocked_status(tmp_path: Path):
    from dorkllm.constitutional_governance_version_enforcer import (
        ConstitutionalGovernanceVersionEnforcer,
    )
    ver = "10.25.0"
    (tmp_path / "VERSION").write_text(ver + "\n")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "adaad"\nversion = "9.0.0"\n'
    )
    core = tmp_path / "adaad_core"
    core.mkdir()
    (core / "__init__.py").write_text(f'__version__ = "{ver}"\n')
    (core / "pyproject.toml").write_text(
        f'[project]\nname = "adaad-core"\nversion = "{ver}"\n'
    )
    ledger = tmp_path / "blocked.jsonl"
    eng = ConstitutionalGovernanceVersionEnforcer(
        repo_root=tmp_path, ledger_path=ledger, auto_repair=True
    )
    record = eng.enforce()
    assert record.status == "BLOCKED"


# ── T214-CGVE-20: auto_repair=False leaves files unchanged ───────────────────

def test_cgve_20_no_auto_repair(drifted_repo: Path, tmp_path: Path):
    from dorkllm.constitutional_governance_version_enforcer import (
        ConstitutionalGovernanceVersionEnforcer,
    )
    ledger = tmp_path / "norepair.jsonl"
    eng = ConstitutionalGovernanceVersionEnforcer(
        repo_root=drifted_repo, ledger_path=ledger, auto_repair=False
    )
    eng.enforce()
    init_text = (drifted_repo / "adaad_core" / "__init__.py").read_text()
    assert "10.23.0" in init_text  # unchanged


# ── T214-CGVE-21: Atomic write uses os.replace (no tmp left behind) ──────────

def test_cgve_21_no_tmp_files(drifted_repo: Path, tmp_path: Path):
    from dorkllm.constitutional_governance_version_enforcer import (
        ConstitutionalGovernanceVersionEnforcer,
    )
    ledger = tmp_path / "atomic.jsonl"
    eng = ConstitutionalGovernanceVersionEnforcer(
        repo_root=drifted_repo, ledger_path=ledger, auto_repair=True
    )
    eng.enforce()
    tmps = list(drifted_repo.rglob("*.tmp"))
    assert len(tmps) == 0


# ── T214-CGVE-22: Missing VERSION raises RuntimeError ────────────────────────

def test_cgve_22_missing_version_raises(tmp_path: Path):
    from dorkllm.constitutional_governance_version_enforcer import (
        ConstitutionalGovernanceVersionEnforcer,
    )
    ver = "10.25.0"
    # No VERSION file
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "adaad"\nversion = "{ver}"\n'
    )
    core = tmp_path / "adaad_core"
    core.mkdir()
    (core / "__init__.py").write_text(f'__version__ = "{ver}"\n')
    (core / "pyproject.toml").write_text(
        f'[project]\nname = "adaad-core"\nversion = "{ver}"\n'
    )
    ledger = tmp_path / "miss.jsonl"
    eng = ConstitutionalGovernanceVersionEnforcer(
        repo_root=tmp_path, ledger_path=ledger
    )
    with pytest.raises(RuntimeError, match="CGVE-CANONICAL-0"):
        eng.enforce()


# ── T214-CGVE-23: Two back-to-back runs on compliant repo — both COMPLIANT ───

def test_cgve_23_idempotent_compliant(enforcer_clean):
    r1 = enforcer_clean.enforce()
    r2 = enforcer_clean.enforce()
    assert r1.status == "COMPLIANT"
    assert r2.status == "COMPLIANT"


# ── T214-CGVE-24: Two back-to-back runs on drifted — 2nd is COMPLIANT ────────

def test_cgve_24_idempotent_repair(drifted_repo: Path, tmp_path: Path):
    from dorkllm.constitutional_governance_version_enforcer import (
        ConstitutionalGovernanceVersionEnforcer,
    )
    ledger = tmp_path / "idem.jsonl"
    eng = ConstitutionalGovernanceVersionEnforcer(
        repo_root=drifted_repo, ledger_path=ledger, auto_repair=True
    )
    r1 = eng.enforce()
    r2 = eng.enforce()
    assert r1.status == "REPAIRED"
    assert r2.status == "COMPLIANT"


# ── T214-CGVE-25: run_ids are unique across runs ─────────────────────────────

def test_cgve_25_unique_run_ids(enforcer_clean):
    r1 = enforcer_clean.enforce()
    time.sleep(0.01)
    r2 = enforcer_clean.enforce()
    assert r1.run_id != r2.run_id


# ── T214-CGVE-26: prev_hmac chain linkage correct ────────────────────────────

def test_cgve_26_hmac_linkage(enforcer_clean, tmp_path: Path):
    r1 = enforcer_clean.enforce()
    r2 = enforcer_clean.enforce()
    assert r2.prev_hmac == r1.hmac_digest


# ── T214-CGVE-27: REST POST /cgve/enforce returns 200 ───────────────────────

def test_cgve_27_rest_enforce(client):
    resp = client.post("/cgve/enforce", json={"auto_repair": False})
    assert resp.status_code == 200
    data = resp.json()
    assert "run_id" in data
    assert "status" in data


# ── T214-CGVE-28: REST GET /cgve/status returns surfaces ────────────────────

def test_cgve_28_rest_status(client):
    resp = client.get("/cgve/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "canonical_version" in data
    assert "compliant" in data
    assert len(data["surfaces"]) == 4


# ── T214-CGVE-29: REST GET /cgve/verify-chain returns valid ─────────────────

def test_cgve_29_rest_verify_chain(client):
    resp = client.get("/cgve/verify-chain")
    assert resp.status_code == 200
    data = resp.json()
    assert "valid" in data
    assert "message" in data


# ── T214-CGVE-30: REST GET /cgve/history returns list ───────────────────────

def test_cgve_30_rest_history(client):
    resp = client.get("/cgve/history?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
