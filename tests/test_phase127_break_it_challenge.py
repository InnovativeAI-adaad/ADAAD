# SPDX-License-Identifier: Apache-2.0
"""
Phase 127 — Break-It Challenge Infrastructure
Tests T127-BRK-01 through T127-BRK-30

Categories:
  DOC  — break-it challenge document structure and content
  LOG  — break_it_log public log structure and policy
  TMPL — GitHub Issue template structure and required fields
  CONT — CONTRIBUTORS.md structure and recognition policy
  INV  — invariant coverage and cross-reference integrity
  PROC — process and policy enforcement properties
"""

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
CHALLENGE_DOC = REPO / "docs" / "BREAK_IT_CHALLENGE.md"
LOG_DOC = REPO / "docs" / "break_it_log" / "README.md"
TEMPLATE = REPO / ".github" / "ISSUE_TEMPLATE" / "break_it_submission.md"
CONTRIBUTORS = REPO / "CONTRIBUTORS.md"
INVARIANT_MATRIX = REPO / "docs" / "governance" / "V8_CONSTITUTIONAL_INVARIANTS_MATRIX.md"


# ---------------------------------------------------------------------------
# DOC — Break-It Challenge document
# ---------------------------------------------------------------------------

@pytest.mark.phase127
def test_T127_BRK_01_challenge_doc_exists():
    """T127-BRK-01: docs/BREAK_IT_CHALLENGE.md exists."""
    assert CHALLENGE_DOC.exists(), "docs/BREAK_IT_CHALLENGE.md not found"


@pytest.mark.phase127
def test_T127_BRK_02_challenge_doc_has_version_header():
    """T127-BRK-02: Challenge doc declares version and phase."""
    content = CHALLENGE_DOC.read_text()
    assert "v9.60.0" in content, "Version header missing"
    assert "Phase 127" in content, "Phase declaration missing"


@pytest.mark.phase127
def test_T127_BRK_03_challenge_doc_lists_primary_targets():
    """T127-BRK-03: Challenge doc lists high-value invariant targets table."""
    content = CHALLENGE_DOC.read_text()
    required = ["GOV-SOLE-0", "AFRT-0", "CEL-EVIDENCE-0", "CEL-REPLAY-0",
                "LSME-0", "HUMAN-0", "CJS-QUORUM-0", "COMMUNITY-HUMAN0-0"]
    for inv in required:
        assert inv in content, f"Invariant {inv} missing from primary targets"


@pytest.mark.phase127
def test_T127_BRK_04_challenge_doc_has_scope_section():
    """T127-BRK-04: Challenge doc has explicit in-scope / out-of-scope sections."""
    content = CHALLENGE_DOC.read_text()
    assert "In scope" in content or "in scope" in content.lower()
    assert "Out of scope" in content or "out of scope" in content.lower()


@pytest.mark.phase127
def test_T127_BRK_05_challenge_doc_has_submission_instructions():
    """T127-BRK-05: Challenge doc provides submission method and required fields."""
    content = CHALLENGE_DOC.read_text()
    assert "How to Submit" in content or "How to submit" in content
    assert "Invariant targeted" in content or "Invariant ID" in content
    assert "Reproduction steps" in content or "reproduction" in content.lower()
    assert "Evidence" in content


@pytest.mark.phase127
def test_T127_BRK_06_challenge_doc_has_result_classifications():
    """T127-BRK-06: Challenge doc defines all three result classifications."""
    content = CHALLENGE_DOC.read_text()
    assert "BYPASS_CONFIRMED" in content
    assert "GUARANTEE_HOLDS" in content
    assert "PARTIAL_BYPASS" in content


@pytest.mark.phase127
def test_T127_BRK_07_challenge_doc_has_recognition_policy():
    """T127-BRK-07: Challenge doc explains recognition policy."""
    content = CHALLENGE_DOC.read_text()
    assert "Recognition" in content or "CONTRIBUTORS" in content


@pytest.mark.phase127
def test_T127_BRK_08_challenge_doc_has_verification_environment():
    """T127-BRK-08: Challenge doc provides exact verification environment commands."""
    content = CHALLENGE_DOC.read_text()
    assert "git clone" in content
    assert "ADAAD_SEED=42" in content
    assert "PYTHONHASHSEED=0" in content


@pytest.mark.phase127
def test_T127_BRK_09_challenge_doc_links_invariant_matrix():
    """T127-BRK-09: Challenge doc links to the full invariants matrix."""
    content = CHALLENGE_DOC.read_text()
    assert "V8_CONSTITUTIONAL_INVARIANTS_MATRIX" in content


@pytest.mark.phase127
def test_T127_BRK_10_challenge_doc_states_167_invariants():
    """T127-BRK-10: Challenge doc correctly states 167 Hard-class invariants."""
    content = CHALLENGE_DOC.read_text()
    assert "167" in content, "Invariant count 167 not stated in challenge doc"


# ---------------------------------------------------------------------------
# LOG — break_it_log public submission log
# ---------------------------------------------------------------------------

@pytest.mark.phase127
def test_T127_BRK_11_break_it_log_dir_exists():
    """T127-BRK-11: docs/break_it_log/ directory exists."""
    assert (REPO / "docs" / "break_it_log").is_dir()


@pytest.mark.phase127
def test_T127_BRK_12_break_it_log_readme_exists():
    """T127-BRK-12: docs/break_it_log/README.md exists."""
    assert LOG_DOC.exists(), "docs/break_it_log/README.md not found"


@pytest.mark.phase127
def test_T127_BRK_13_log_has_summary_table():
    """T127-BRK-13: Log README contains summary metrics table."""
    content = LOG_DOC.read_text()
    assert "BYPASS_CONFIRMED" in content
    assert "GUARANTEE_HOLDS" in content
    assert "Total submissions" in content or "submissions received" in content.lower()


@pytest.mark.phase127
def test_T127_BRK_14_log_states_zero_submissions_at_launch():
    """T127-BRK-14: Log README initializes with 0 submissions at launch."""
    content = LOG_DOC.read_text()
    # Must contain 0 for bypass confirmed count
    assert "| 0 |" in content or "0 bypass" in content.lower() or "| 0" in content


@pytest.mark.phase127
def test_T127_BRK_15_log_documents_entry_format():
    """T127-BRK-15: Log README specifies the standard entry format."""
    content = LOG_DOC.read_text()
    assert "BREAK-" in content, "BREAK-<N> ID format not documented"
    assert "Submitted by" in content
    assert "Result" in content


@pytest.mark.phase127
def test_T127_BRK_16_log_links_challenge_doc():
    """T127-BRK-16: Log README links back to challenge rules."""
    content = LOG_DOC.read_text()
    assert "BREAK_IT_CHALLENGE" in content


@pytest.mark.phase127
def test_T127_BRK_17_log_states_active_invariant_count():
    """T127-BRK-17: Log README states the count of active invariants."""
    content = LOG_DOC.read_text()
    assert "167" in content


# ---------------------------------------------------------------------------
# TMPL — GitHub Issue template
# ---------------------------------------------------------------------------

@pytest.mark.phase127
def test_T127_BRK_18_issue_template_exists():
    """T127-BRK-18: .github/ISSUE_TEMPLATE/break_it_submission.md exists."""
    assert TEMPLATE.exists(), "break_it_submission.md template not found"


@pytest.mark.phase127
def test_T127_BRK_19_template_has_yaml_frontmatter():
    """T127-BRK-19: Template has valid YAML frontmatter with name, about, labels."""
    content = TEMPLATE.read_text()
    assert content.startswith("---"), "YAML frontmatter missing"
    assert "name:" in content
    assert "about:" in content
    assert "labels:" in content


@pytest.mark.phase127
def test_T127_BRK_20_template_has_break_it_label():
    """T127-BRK-20: Template applies break-it-challenge label."""
    content = TEMPLATE.read_text()
    assert "break-it-challenge" in content


@pytest.mark.phase127
def test_T127_BRK_21_template_requires_all_mandatory_fields():
    """T127-BRK-21: Template requires all mandatory submission fields."""
    content = TEMPLATE.read_text()
    required_fields = [
        "Invariant",
        "Method",
        "Reproduction",
        "Evidence",
        "Environment",
    ]
    for field in required_fields:
        assert field in content, f"Mandatory field '{field}' missing from template"


@pytest.mark.phase127
def test_T127_BRK_22_template_has_result_checkboxes():
    """T127-BRK-22: Template includes result classification checkboxes."""
    content = TEMPLATE.read_text()
    assert "BYPASS_CONFIRMED" in content
    assert "GUARANTEE_HOLDS" in content
    assert "PARTIAL_BYPASS" in content
    assert "- [ ]" in content, "Markdown checkboxes not present"


@pytest.mark.phase127
def test_T127_BRK_23_template_requires_clean_clone_reproduction():
    """T127-BRK-23: Template instructs submitter to reproduce from clean git clone."""
    content = TEMPLATE.read_text()
    assert "git clone" in content
    assert "ADAAD_SEED=42" in content


# ---------------------------------------------------------------------------
# CONT — CONTRIBUTORS.md
# ---------------------------------------------------------------------------

@pytest.mark.phase127
def test_T127_BRK_24_contributors_exists():
    """T127-BRK-24: CONTRIBUTORS.md exists at repo root."""
    assert CONTRIBUTORS.exists(), "CONTRIBUTORS.md not found"


@pytest.mark.phase127
def test_T127_BRK_25_contributors_has_human0_section():
    """T127-BRK-25: CONTRIBUTORS.md lists HUMAN-0 governor."""
    content = CONTRIBUTORS.read_text()
    assert "Dustin L. Reid" in content
    assert "HUMAN-0" in content


@pytest.mark.phase127
def test_T127_BRK_26_contributors_has_break_it_section():
    """T127-BRK-26: CONTRIBUTORS.md has Constitutional Auditors section for Break-It."""
    content = CONTRIBUTORS.read_text()
    assert "Break-It" in content or "Constitutional Auditor" in content


@pytest.mark.phase127
def test_T127_BRK_27_contributors_has_recognition_policy():
    """T127-BRK-27: CONTRIBUTORS.md states recognition is permanent."""
    content = CONTRIBUTORS.read_text()
    assert "permanent" in content.lower(), "Permanence of recognition not stated"


# ---------------------------------------------------------------------------
# INV / PROC — Invariant coverage and process properties
# ---------------------------------------------------------------------------

@pytest.mark.phase127
def test_T127_BRK_28_challenge_doc_does_not_promise_monetary_bounty():
    """T127-BRK-28: Challenge doc explicitly states no monetary bounty (policy alignment)."""
    content = CHALLENGE_DOC.read_text()
    # Must mention no monetary bounty
    assert "no monetary bounty" in content.lower() or "no bounty" in content.lower() or \
           "There is no monetary bounty" in content or "No monetary bounty" in content


@pytest.mark.phase127
def test_T127_BRK_29_log_disclosure_policy_stated():
    """T127-BRK-29: Log README states coordinated disclosure policy for confirmed bypasses."""
    content = LOG_DOC.read_text()
    assert "coordinated" in content.lower() or "disclosure" in content.lower() or \
           "coordination" in content.lower()


@pytest.mark.phase127
def test_T127_BRK_30_challenge_doc_not_in_scope_includes_gpg_key():
    """T127-BRK-30: Challenge doc out-of-scope includes GPG private key attacks (non-bypassable)."""
    content = CHALLENGE_DOC.read_text()
    assert "GPG" in content or "private key" in content.lower(), \
        "GPG key scope boundary not documented"
