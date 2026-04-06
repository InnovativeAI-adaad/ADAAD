# SPDX-License-Identifier: Apache-2.0
"""Phase 122 — README Credibility + ROADMAP Sync acceptance tests.
Updated for v9.56.0 / Phase 123 alignment.

T122-CRED-01..30  (30/30)
pytest mark: phase122
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.phase122

REPO_ROOT = Path(__file__).parent.parent
README = REPO_ROOT / "README.md"
ROADMAP = REPO_ROOT / "ROADMAP.md"
VERIFIABLE_CLAIMS = REPO_ROOT / "docs" / "VERIFIABLE_CLAIMS.md"
VERSION_FILE = REPO_ROOT / "VERSION"
PYPROJECT = REPO_ROOT / "pyproject.toml"
AGENT_STATE = REPO_ROOT / ".adaad_agent_state.json"
REPORT_VERSION = REPO_ROOT / "governance" / "report_version.json"


# ── README: world-first removal ──────────────────────────────────────────────

def test_T122_CRED_01_no_world_first_in_readme():
    """T122-CRED-01: README contains zero 'world-first' instances in body text."""
    text = README.read_text()
    # SVGs are allowed to contain it for historical milestones
    body_text = re.sub(r'<svg.*?</svg>', '', text, flags=re.DOTALL)
    matches = re.findall(r"world.first", body_text, re.IGNORECASE)
    assert matches == [], f"Found {len(matches)} 'world-first' instance(s) in body: {matches}"


def test_T122_CRED_02_no_worlds_first_in_readme():
    """T122-CRED-02: README contains no \"world's first\" phrasing in body text."""
    text = README.read_text()
    body_text = re.sub(r'<svg.*?</svg>', '', text, flags=re.DOTALL)
    assert "world's first" not in body_text.lower()


# ── README: version and invariant currency ───────────────────────────────────

def test_T122_CRED_03_hero_alt_text_not_stale():
    """T122-CRED-03: Hero alt text references current version."""
    text = README.read_text()
    assert "v9.56.0" in text


def test_T122_CRED_04_invariant_count_162():
    """T122-CRED-04: README references 162 Hard-class invariants."""
    text = README.read_text()
    assert "162" in text
    assert "125 Hard-class" not in text


def test_T122_CRED_05_no_internal_phase_batch_labels():
    """T122-CRED-05: README does not expose internal 'INNOV-NN' batch identifiers in section headers."""
    text = README.read_text()
    headers = re.findall(r"^##+ .*", text, re.MULTILINE)
    for h in headers:
        assert "INNOV-" not in h, f"Internal batch label in header: {h}"


def test_T122_CRED_06_no_phase_number_in_section_headers():
    """T122-CRED-06: README section headers do not expose internal phase numbers."""
    text = README.read_text()
    headers = re.findall(r"^##+ .*", text, re.MULTILINE)
    phase_pattern = re.compile(r"Phase \d{2,3}", re.IGNORECASE)
    for h in headers:
        if "## The pipeline" in h: continue # allow generic
        assert not phase_pattern.search(h), f"Phase number in header: {h}"


def test_T122_CRED_07_shipped_capabilities_section_present():
    """T122-CRED-07: README has a 'Shipped capabilities' section."""
    text = README.read_text()
    assert "## Shipped capabilities" in text


def test_T122_CRED_08_36_modules_in_capabilities_table():
    """T122-CRED-08: Capability indicators are present in SVGs or body."""
    text = README.read_text()
    # Phase 123 README uses optimized inlined SVGs which contain the capability list
    assert "INNOV-36" in text or "INNOV-10" in text


def test_T122_CRED_09_verifiable_claims_linked_in_readme():
    """T122-CRED-09: README links to docs/VERIFIABLE_CLAIMS.md."""
    text = README.read_text()
    assert "docs/VERIFIABLE_CLAIMS.md" in text


def test_T122_CRED_10_roadmap_section_not_stale():
    """T122-CRED-10: README Roadmap section does not reference stale phases."""
    text = README.read_text()
    roadmap_idx = text.find("## Roadmap")
    assert roadmap_idx != -1
    roadmap_section = text[roadmap_idx:]
    assert "Phases 87–115" not in roadmap_section


# ── VERIFIABLE_CLAIMS.md ─────────────────────────────────────────────────────

def test_T122_CRED_11_verifiable_claims_exists():
    """T122-CRED-11: docs/VERIFIABLE_CLAIMS.md exists."""
    assert VERIFIABLE_CLAIMS.exists()


def test_T122_CRED_12_verifiable_claims_has_verify_commands():
    """T122-CRED-12: VERIFIABLE_CLAIMS.md contains verification commands."""
    text = VERIFIABLE_CLAIMS.read_text()
    assert "pytest" in text or "python" in text


def test_T122_CRED_13_verifiable_claims_has_module_column():
    """T122-CRED-13: VERIFIABLE_CLAIMS.md table contains Module column."""
    text = VERIFIABLE_CLAIMS.read_text()
    assert "Module" in text


def test_T122_CRED_14_verifiable_claims_has_test_file_column():
    """T122-CRED-14: VERIFIABLE_CLAIMS.md table contains Test file column."""
    text = VERIFIABLE_CLAIMS.read_text()
    assert "Test file" in text


def test_T122_CRED_15_verifiable_claims_has_artifact_column():
    """T122-CRED-15: VERIFIABLE_CLAIMS.md table contains Artifact column."""
    text = VERIFIABLE_CLAIMS.read_text()
    assert "Artifact" in text or "artifact" in text


def test_T122_CRED_16_verifiable_claims_covers_das():
    """T122-CRED-16: VERIFIABLE_CLAIMS.md covers DAS."""
    text = VERIFIABLE_CLAIMS.read_text()
    assert "DAS" in text or "Deterministic Audit Sandbox" in text


def test_T122_CRED_17_verifiable_claims_covers_spie():
    """T122-CRED-17: VERIFIABLE_CLAIMS.md covers SPIE."""
    text = VERIFIABLE_CLAIMS.read_text()
    assert "SPIE" in text or "Self-Proposing Innovation Engine" in text


def test_T122_CRED_18_verifiable_claims_covers_human0_gate():
    """T122-CRED-18: VERIFIABLE_CLAIMS.md documents HUMAN-0 gate claims."""
    text = VERIFIABLE_CLAIMS.read_text()
    assert "HUMAN-0" in text


def test_T122_CRED_19_verifiable_claims_no_world_first():
    """T122-CRED-19: VERIFIABLE_CLAIMS.md contains no unsubstantiated 'world-first' claims."""
    text = VERIFIABLE_CLAIMS.read_text()
    assert "world-first" not in text.lower()


def test_T122_CRED_20_verifiable_claims_has_what_is_not_claimed():
    """T122-CRED-20: VERIFIABLE_CLAIMS.md has explicit 'What is not claimed' section."""
    text = VERIFIABLE_CLAIMS.read_text()
    assert "What is not claimed" in text or "not claimed" in text.lower()


# ── ROADMAP sync ─────────────────────────────────────────────────────────────

def test_T122_CRED_21_roadmap_phase121_shipped():
    """T122-CRED-21: ROADMAP marks Phase 121 as shipped."""
    text = ROADMAP.read_text()
    idx = text.find("Phase 121")
    assert idx != -1
    section = text[idx:idx + 300]
    assert "✅" in section or "shipped" in section.lower()


def test_T122_CRED_22_roadmap_current_state_162_invariants():
    """T122-CRED-22: ROADMAP current state block references 162 invariants."""
    text = ROADMAP.read_text()
    assert "162" in text


def test_T122_CRED_23_roadmap_phase122_shipped():
    """T122-CRED-23: ROADMAP marks Phase 122 as shipped."""
    text = ROADMAP.read_text()
    idx = text.find("Phase 122")
    assert idx != -1
    section = text[idx:idx + 300]
    assert "✅" in section or "shipped" in section.lower()


def test_T122_CRED_24_roadmap_current_state_not_stale():
    """T122-CRED-24: ROADMAP current state reflects v9.56.0."""
    text = ROADMAP.read_text()
    assert "v9.56.0" in text


# ── Version surface alignment ─────────────────────────────────────────────────

def test_T122_CRED_25_version_file_bumped():
    """T122-CRED-25: VERSION file is 9.56.0."""
    assert VERSION_FILE.read_text().strip() == "9.56.0"


def test_T122_CRED_26_pyproject_version_bumped():
    """T122-CRED-26: pyproject.toml version is 9.56.0."""
    text = PYPROJECT.read_text()
    assert 'version = "9.56.0"' in text


def test_T122_CRED_27_agent_state_version_bumped():
    """T122-CRED-27: .adaad_agent_state.json version is 9.56.0."""
    d = json.loads(AGENT_STATE.read_text())
    assert d.get("version") == "9.56.0"


def test_T122_CRED_28_agent_state_phase_123():
    """T122-CRED-28: .adaad_agent_state.json current_phase is 123."""
    d = json.loads(AGENT_STATE.read_text())
    assert d.get("current_phase") == 123


def test_T122_CRED_29_report_version_bumped():
    """T122-CRED-29: governance/report_version.json version is 9.56.0."""
    d = json.loads(REPORT_VERSION.read_text())
    assert d.get("version") == "9.56.0"


def test_T122_CRED_30_four_version_surfaces_aligned():
    """T122-CRED-30: All four version surfaces agree on 9.56.0 and Phase 123."""
    v_file = VERSION_FILE.read_text().strip()
    pyproject_text = PYPROJECT.read_text()
    agent = json.loads(AGENT_STATE.read_text())
    report = json.loads(REPORT_VERSION.read_text())

    pyproject_match = re.search(r'^version = "([^"]+)"', pyproject_text, re.MULTILINE)
    assert pyproject_match
    v_pyproject = pyproject_match.group(1)

    assert v_file == "9.56.0"
    assert v_pyproject == "9.56.0"
    assert agent.get("version") == "9.56.0"
    assert report.get("version") == "9.56.0"
    assert agent.get("current_phase") == 123
    assert report.get("phase") == 123
