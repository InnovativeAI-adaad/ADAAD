# SPDX-License-Identifier: Apache-2.0
"""Phase 85 Track B — Governance State Sync constitutional tests. T85-GSYNC-01..12"""
from __future__ import annotations
import json, re, sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.phase85


@pytest.fixture
def tmp_repo(tmp_path):
    (tmp_path / "VERSION").write_text("9.17.0\n")
    (tmp_path / "CHANGELOG.md").write_text(
        "## [9.17.0] — 2026-03-21 — Phase 85 · KMS/HSM + Governance Sync\n\n"
        "## [9.16.0] — 2026-03-20 — Phases 81–84 · Evolution Engine Core\n"
    )
    state = {
        "schema_version": "1.5.0", "current_version": "9.12.1",
        "software_version": "9.12.1", "active_phase": "old",
        "last_invocation": "2026-01-01", "last_sync_sha": "abc1234",
        "last_completed_phase": "old phase", "last_gate_results": {
            "tier_0": "pass", "tier_1": "pass", "tier_2": "pass", "tier_3": "pass"},
        "open_findings": [], "value_checkpoints_reached": [],
        "pending_evidence_rows": [], "next_pr": "PR-TBD",
        "blocked_reason": None, "blocked_at_gate": None, "blocked_at_tier": None,
    }
    (tmp_path / ".adaad_agent_state.json").write_text(json.dumps(state))
    return tmp_path


def _import_sync(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "sync_agent_state_on_merge", ROOT / "scripts" / "sync_agent_state_on_merge.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    mod.ROOT = tmp_path
    mod.STATE_PATH = tmp_path / ".adaad_agent_state.json"
    mod.VERSION_PATH = tmp_path / "VERSION"
    mod.CHANGELOG_PATH = tmp_path / "CHANGELOG.md"
    mod._git_sha = lambda: "deadbee"
    return mod


def _import_drift(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "validate_governance_state_drift", ROOT / "scripts" / "validate_governance_state_drift.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    mod.ROOT = tmp_path
    mod.STATE_PATH = tmp_path / ".adaad_agent_state.json"
    mod.VERSION_PATH = tmp_path / "VERSION"
    mod.CHANGELOG_PATH = tmp_path / "CHANGELOG.md"
    return mod


def test_current_version_updated(tmp_repo):
    """T85-GSYNC-01: current_version set to VERSION after sync."""
    mod = _import_sync(tmp_repo)
    mod.sync_agent_state(dry_run=False)
    state = json.loads((tmp_repo / ".adaad_agent_state.json").read_text())
    assert state["current_version"] == "9.17.0"


def test_software_version_updated(tmp_repo):
    """T85-GSYNC-02: software_version updated."""
    mod = _import_sync(tmp_repo)
    mod.sync_agent_state(dry_run=False)
    state = json.loads((tmp_repo / ".adaad_agent_state.json").read_text())
    assert state["software_version"] == "9.17.0"


def test_schema_version_not_overwritten(tmp_repo):
    """T85-GSYNC-03: schema_version remains 1.5.0."""
    mod = _import_sync(tmp_repo)
    mod.sync_agent_state(dry_run=False)
    state = json.loads((tmp_repo / ".adaad_agent_state.json").read_text())
    assert state["schema_version"] == "1.5.0"


def test_dry_run_no_write(tmp_repo):
    """T85-GSYNC-04: dry_run does not write file."""
    mod = _import_sync(tmp_repo)
    original = (tmp_repo / ".adaad_agent_state.json").read_text()
    mod.sync_agent_state(dry_run=True)
    assert (tmp_repo / ".adaad_agent_state.json").read_text() == original


def test_idempotent(tmp_repo):
    """T85-GSYNC-05: second run produces zero changes."""
    mod = _import_sync(tmp_repo)
    mod.sync_agent_state(dry_run=False)
    changes = mod.sync_agent_state(dry_run=False)
    non_schema = [c for c in changes if c.get("invariant") != "GSYNC-SCHEMA-0-correction"]
    assert non_schema == []


def test_missing_version_exits_1(tmp_repo):
    """T85-GSYNC-06: missing VERSION file exits 1."""
    (tmp_repo / "VERSION").unlink()
    mod = _import_sync(tmp_repo)
    with pytest.raises(SystemExit) as e:
        mod.sync_agent_state(dry_run=False)
    assert e.value.code == 1


def test_phase_derived_from_changelog(tmp_repo):
    """T85-GSYNC-07: last_completed_phase derived from CHANGELOG."""
    mod = _import_sync(tmp_repo)
    mod.sync_agent_state(dry_run=False)
    state = json.loads((tmp_repo / ".adaad_agent_state.json").read_text())
    assert "85" in state["last_completed_phase"] or state["last_completed_phase"]


def test_drift_caught_before_sync(tmp_repo):
    """T85-GSYNC-08: drift validator detects version drift."""
    mod = _import_drift(tmp_repo)
    violations = mod.validate()
    codes = {v.code for v in violations}
    assert "GOVERNANCE_DRIFT_CURRENT_VERSION" in codes


def test_no_drift_after_sync(tmp_repo):
    """T85-GSYNC-09: drift validator passes after sync."""
    _import_sync(tmp_repo).sync_agent_state(dry_run=False)
    violations = _import_drift(tmp_repo).validate()
    assert violations == []


def test_legacy_semver_schema_corrected(tmp_repo):
    """T85-GSYNC-10: semver written to schema_version gets corrected to 1.5.0."""
    sp = tmp_repo / ".adaad_agent_state.json"
    state = json.loads(sp.read_text())
    state["schema_version"] = "9.16.0"
    sp.write_text(json.dumps(state))
    _import_sync(tmp_repo).sync_agent_state(dry_run=False)
    assert json.loads(sp.read_text())["schema_version"] == "1.5.0"


def test_sync_script_exists():
    """T85-GSYNC-11: sync script present in repo."""
    assert (ROOT / "scripts" / "sync_agent_state_on_merge.py").exists()


def test_drift_validator_exists():
    """T85-GSYNC-12: drift validator script present."""
    assert (ROOT / "scripts" / "validate_governance_state_drift.py").exists()
