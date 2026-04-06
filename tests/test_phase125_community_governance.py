# SPDX-License-Identifier: Apache-2.0
"""
Phase 125 — Community Governance Infrastructure
Acceptance tests: T125-COMM-01..30

Invariants under test:
    COMMUNITY-FGCON-0   Community amendments are subject to FGCON-QUORUM-0;
                        no single contributor can ratify.
    COMMUNITY-HUMAN0-0  HUMAN-0 ratification cannot be delegated via any
                        community governance workflow.

Test categories:
    COMM  — validate_amendment_proposal.py logic (01–12)
    TMPL  — Issue template structure and required fields (13–17)
    WFLOW — CI workflow structural integrity (18–22)
    DOCS  — CONSTITUTION_PROPOSALS.md and GOVERNANCE_PARTICIPATION.md (23–27)
    INV   — Constitutional invariant assertions (28–30)
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

ROOT = Path(__file__).parent.parent

VALIDATOR = ROOT / "scripts" / "validate_amendment_proposal.py"

ISSUE_TEMPLATE = ROOT / ".github" / "ISSUE_TEMPLATE" / "constitution_amendment.md"
WORKFLOW = (
    ROOT / ".github" / "workflows" / "constitution_amendment_validation.yml"
)
PROPOSALS_DOC = ROOT / "CONSTITUTION_PROPOSALS.md"
GOV_GUIDE = ROOT / "docs" / "GOVERNANCE_PARTICIPATION.md"


def _valid_body(
    *,
    inv_id: str = "TEST-VALID-0",
    inv_class: str = "Hard",
    rationale: str = (
        "This invariant is constitutionally necessary because it prevents a class of "
        "failure where an unchecked subsystem can promote mutations without passing "
        "the shadow execution gate. Without this constraint, an adversary could craft "
        "a mutation that bypasses LSME and enters the live runtime unvetted. The CEL "
        "relies on every promotion being shadow-validated. This invariant closes that gap."
    ),
    modules: str = "- `runtime/innovations30/lsme.py`",
    test_line: str = "**Test ID:** `T125-TEST-01`",
    conflict: str = "No conflicts identified with existing invariants.",
    checkboxes: bool = True,
) -> str:
    """Return a minimal structurally-valid proposal body."""
    checkbox_mark = "x" if checkboxes else " "
    cls_hard = f"[{checkbox_mark}] **Hard**" if inv_class == "Hard" else "[ ] **Hard**"
    cls_soft = f"[{checkbox_mark}] **Soft**" if inv_class == "Soft" else "[ ] **Soft**"
    return f"""
## Proposed Invariant Identifier

```
PROPOSED_INVARIANT_ID: {inv_id}
```

## Invariant Class

{cls_hard} — Constitutional violation blocks mutation promotion
{cls_soft} — Constitutional violation triggers governance alert (non-blocking)

## Rationale

{rationale}

## Affected Modules

{modules}

## Proposed Acceptance Test

{test_line}

**Description:** Verifies that the invariant is enforced at promotion time.

## Conflict Analysis

{conflict}

## FGCON Quorum Confirmation

- [{checkbox_mark}] I confirm I am not the ratifying principal for this proposal
- [{checkbox_mark}] I understand HUMAN-0 ratification (GPG-signed) is required and cannot be automated
- [{checkbox_mark}] I have read `CONSTITUTION_PROPOSALS.md` and understand the full amendment lifecycle
"""


def _run_validator(body: str, tmp_path: Path) -> dict:
    """Write body to tmp file, run validator, return parsed JSON result."""
    infile = tmp_path / "proposal.md"
    outfile = tmp_path / "result.json"
    infile.write_text(body, encoding="utf-8")
    subprocess.run(
        [sys.executable, str(VALIDATOR), "--input", str(infile), "--output", str(outfile)],
        capture_output=True,
        text=True,
    )
    return json.loads(outfile.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# COMM — Validator logic tests (01–12)
# ---------------------------------------------------------------------------


@pytest.mark.phase125
def test_T125_COMM_01_validator_script_exists():
    """T125-COMM-01: validate_amendment_proposal.py exists and is executable."""
    assert VALIDATOR.exists(), "scripts/validate_amendment_proposal.py not found"
    content = VALIDATOR.read_text()
    assert "def validate(" in content


@pytest.mark.phase125
def test_T125_COMM_02_valid_proposal_passes(tmp_path):
    """T125-COMM-02: A fully-populated valid proposal returns valid=True."""
    result = _run_validator(_valid_body(), tmp_path)
    assert result["valid"] is True, f"Expected valid=True, got: {result['checks_failed']}"
    assert len(result["checks_failed"]) == 0


@pytest.mark.phase125
def test_T125_COMM_03_missing_invariant_id_fails(tmp_path):
    """T125-COMM-03: Proposal without PROPOSED_INVARIANT_ID fails validation."""
    body = _valid_body().replace("PROPOSED_INVARIANT_ID: TEST-VALID-0", "PROPOSED_INVARIANT_ID: ")
    result = _run_validator(body, tmp_path)
    assert result["valid"] is False
    assert any("PROPOSED_INVARIANT_ID" in f for f in result["checks_failed"])


@pytest.mark.phase125
def test_T125_COMM_04_malformed_invariant_id_fails(tmp_path):
    """T125-COMM-04: Invariant ID not matching CATEGORY-KEYWORD-N pattern fails."""
    body = _valid_body(inv_id="invalid-id-format")
    result = _run_validator(body, tmp_path)
    assert result["valid"] is False
    assert any("pattern" in f.lower() or "well-formed" in f.lower() or "invalid" in f.lower()
               for f in result["checks_failed"])


@pytest.mark.phase125
def test_T125_COMM_05_rationale_below_minimum_fails(tmp_path):
    """T125-COMM-05: Rationale with fewer than 50 words fails validation."""
    body = _valid_body(rationale="This is too short and does not meet the minimum word count.")
    result = _run_validator(body, tmp_path)
    assert result["valid"] is False
    assert any("rationale" in f.lower() or "word" in f.lower() for f in result["checks_failed"])


@pytest.mark.phase125
def test_T125_COMM_06_rationale_exactly_50_words_passes(tmp_path):
    """T125-COMM-06: Rationale with exactly 50 words passes the word count check."""
    # 50-word rationale
    words = " ".join(["word"] * 50)
    body = _valid_body(rationale=words)
    result = _run_validator(body, tmp_path)
    assert result["rationale_word_count"] >= 50
    # rationale check should pass
    assert not any("rationale" in f.lower() and "short" in f.lower() for f in result["checks_failed"])


@pytest.mark.phase125
def test_T125_COMM_07_invariant_class_not_selected_fails(tmp_path):
    """T125-COMM-07: Proposal with no invariant class checkbox checked fails."""
    body = _valid_body(checkboxes=False)
    result = _run_validator(body, tmp_path)
    assert result["valid"] is False
    assert any("class" in f.lower() for f in result["checks_failed"])


@pytest.mark.phase125
def test_T125_COMM_08_hard_class_detected(tmp_path):
    """T125-COMM-08: Hard class selection is correctly detected in result."""
    result = _run_validator(_valid_body(inv_class="Hard"), tmp_path)
    assert result["invariant_class"] == "Hard"


@pytest.mark.phase125
def test_T125_COMM_09_soft_class_detected(tmp_path):
    """T125-COMM-09: Soft class selection is correctly detected in result."""
    result = _run_validator(_valid_body(inv_class="Soft"), tmp_path)
    assert result["invariant_class"] == "Soft"


@pytest.mark.phase125
def test_T125_COMM_10_missing_fgcon_checkboxes_fails(tmp_path):
    """T125-COMM-10: Unchecked FGCON confirmation checkboxes cause failure."""
    body = _valid_body(checkboxes=False)
    result = _run_validator(body, tmp_path)
    assert result["valid"] is False
    # Should have failures related to FGCON or checkbox
    fgcon_failures = [f for f in result["checks_failed"] if "fgcon" in f.lower() or "checkbox" in f.lower() or "ratifying" in f.lower()]
    assert len(fgcon_failures) >= 1, f"Expected FGCON-related failures, got: {result['checks_failed']}"


@pytest.mark.phase125
def test_T125_COMM_11_auto_ratification_claim_fails(tmp_path):
    """T125-COMM-11: Proposal claiming auto-ratification violates COMMUNITY-HUMAN0-0."""
    body = _valid_body() + "\nThis proposal enables auto-ratification of amendments."
    result = _run_validator(body, tmp_path)
    assert result["valid"] is False
    assert any("auto-ratif" in f.lower() or "COMMUNITY-HUMAN0-0" in f for f in result["checks_failed"])


@pytest.mark.phase125
def test_T125_COMM_12_result_json_schema(tmp_path):
    """T125-COMM-12: Validator output JSON contains all required schema fields."""
    result = _run_validator(_valid_body(), tmp_path)
    required_keys = {"valid", "checks_passed", "checks_failed", "proposed_invariant",
                     "invariant_class", "rationale_word_count"}
    assert required_keys.issubset(result.keys()), (
        f"Missing keys: {required_keys - result.keys()}"
    )


# ---------------------------------------------------------------------------
# TMPL — Issue template structure tests (13–17)
# ---------------------------------------------------------------------------


@pytest.mark.phase125
def test_T125_TMPL_13_issue_template_exists():
    """T125-TMPL-13: constitution_amendment.md issue template exists."""
    assert ISSUE_TEMPLATE.exists(), (
        ".github/ISSUE_TEMPLATE/constitution_amendment.md not found"
    )


@pytest.mark.phase125
def test_T125_TMPL_14_issue_template_frontmatter():
    """T125-TMPL-14: Issue template has valid YAML frontmatter with name and labels."""
    content = ISSUE_TEMPLATE.read_text()
    assert content.startswith("---"), "Missing YAML frontmatter"
    assert "constitutional-amendment" in content
    assert "governance-review" in content
    assert "name:" in content


@pytest.mark.phase125
def test_T125_TMPL_15_issue_template_required_sections():
    """T125-TMPL-15: Issue template contains all required section headers."""
    content = ISSUE_TEMPLATE.read_text()
    required_sections = [
        "Proposed Invariant Identifier",
        "Invariant Class",
        "Rationale",
        "Affected Modules",
        "Proposed Acceptance Test",
        "Conflict Analysis",
        "FGCON Quorum Confirmation",
    ]
    for section in required_sections:
        assert section in content, f"Missing required section: '{section}'"


@pytest.mark.phase125
def test_T125_TMPL_16_issue_template_fgcon_checkboxes():
    """T125-TMPL-16: Issue template includes all three FGCON quorum checkboxes."""
    content = ISSUE_TEMPLATE.read_text()
    assert "I confirm I am not the ratifying principal" in content
    assert "HUMAN-0 ratification" in content
    assert "CONSTITUTION_PROPOSALS.md" in content
    # Must be checkboxes (- [ ])
    assert content.count("- [ ]") >= 3


@pytest.mark.phase125
def test_T125_TMPL_17_issue_template_no_auto_merge_instructions():
    """T125-TMPL-17: Issue template contains no auto-merge or auto-ratification instructions."""
    content = ISSUE_TEMPLATE.read_text().lower()
    forbidden = ["auto-merge", "auto_merge", "auto-ratif", "auto_ratif", "self-ratif"]
    for phrase in forbidden:
        assert phrase not in content, (
            f"Forbidden phrase '{phrase}' found in issue template — COMMUNITY-HUMAN0-0 violation"
        )


# ---------------------------------------------------------------------------
# WFLOW — CI workflow structural integrity tests (18–22)
# ---------------------------------------------------------------------------


@pytest.mark.phase125
def test_T125_WFLOW_18_workflow_file_exists():
    """T125-WFLOW-18: constitution_amendment_validation.yml workflow file exists."""
    assert WORKFLOW.exists(), (
        ".github/workflows/constitution_amendment_validation.yml not found"
    )


@pytest.mark.phase125
def test_T125_WFLOW_19_workflow_triggers_on_issues():
    """T125-WFLOW-19: Workflow triggers on issue opened and edited events."""
    content = WORKFLOW.read_text()
    assert "issues:" in content
    assert "opened" in content
    assert "edited" in content


@pytest.mark.phase125
def test_T125_WFLOW_20_workflow_calls_validator_script():
    """T125-WFLOW-20: Workflow invokes validate_amendment_proposal.py."""
    content = WORKFLOW.read_text()
    assert "validate_amendment_proposal.py" in content


@pytest.mark.phase125
def test_T125_WFLOW_21_workflow_posts_failure_comment():
    """T125-WFLOW-21: Workflow has a failure branch that adds needs-revision label."""
    content = WORKFLOW.read_text()
    assert "needs-revision" in content
    assert "failure" in content or "failed" in content.lower()


@pytest.mark.phase125
def test_T125_WFLOW_22_workflow_fgcon_quorum_job():
    """T125-WFLOW-22: Workflow contains a FGCON quorum simulation job."""
    content = WORKFLOW.read_text()
    assert "fgcon" in content.lower() or "quorum" in content.lower()
    assert "COMMUNITY-FGCON-0" in content or "COMMUNITY-HUMAN0-0" in content


# ---------------------------------------------------------------------------
# DOCS — Documentation integrity tests (23–27)
# ---------------------------------------------------------------------------


@pytest.mark.phase125
def test_T125_DOCS_23_constitution_proposals_exists():
    """T125-DOCS-23: CONSTITUTION_PROPOSALS.md exists at repository root."""
    assert PROPOSALS_DOC.exists(), "CONSTITUTION_PROPOSALS.md not found at repository root"


@pytest.mark.phase125
def test_T125_DOCS_24_constitution_proposals_lifecycle():
    """T125-DOCS-24: CONSTITUTION_PROPOSALS.md documents the full amendment lifecycle."""
    content = PROPOSALS_DOC.read_text()
    lifecycle_steps = [
        "Community opens Issue",
        "CI validation",
        "HUMAN-0",
        "FGCON",
        "ratif",
    ]
    for step in lifecycle_steps:
        assert step in content, f"Lifecycle step '{step}' not documented in CONSTITUTION_PROPOSALS.md"


@pytest.mark.phase125
def test_T125_DOCS_25_constitution_proposals_invariants():
    """T125-DOCS-25: CONSTITUTION_PROPOSALS.md defines both Phase 125 invariants."""
    content = PROPOSALS_DOC.read_text()
    assert "COMMUNITY-FGCON-0" in content
    assert "COMMUNITY-HUMAN0-0" in content


@pytest.mark.phase125
def test_T125_DOCS_26_governance_participation_guide_exists():
    """T125-DOCS-26: docs/GOVERNANCE_PARTICIPATION.md exists."""
    assert GOV_GUIDE.exists(), "docs/GOVERNANCE_PARTICIPATION.md not found"


@pytest.mark.phase125
def test_T125_DOCS_27_governance_participation_guide_content():
    """T125-DOCS-27: GOVERNANCE_PARTICIPATION.md covers lifecycle, hierarchy, and invariants."""
    content = GOV_GUIDE.read_text()
    required_topics = [
        "HUMAN-0",
        "FGCON",
        "COMMUNITY-FGCON-0",
        "COMMUNITY-HUMAN0-0",
        "ratif",
        "lifecycle",
    ]
    for topic in required_topics:
        assert topic.lower() in content.lower(), (
            f"Required topic '{topic}' missing from GOVERNANCE_PARTICIPATION.md"
        )


# ---------------------------------------------------------------------------
# INV — Constitutional invariant assertions (28–30)
# ---------------------------------------------------------------------------


@pytest.mark.phase125
def test_T125_INV_28_fgcon_0_no_self_ratification_path():
    """T125-INV-28: COMMUNITY-FGCON-0 — no self-ratification path exists in any workflow."""
    workflows_dir = ROOT / ".github" / "workflows"
    violations: list[str] = []
    for wf in workflows_dir.glob("*.yml"):
        content = wf.read_text().lower()
        for phrase in ["auto-merge", "auto_merge", "self-ratif", "self_ratif"]:
            if phrase in content:
                violations.append(f"{wf.name}: contains '{phrase}'")
    assert len(violations) == 0, (
        f"COMMUNITY-FGCON-0 violation — self-ratification paths detected:\n"
        + "\n".join(violations)
    )


@pytest.mark.phase125
def test_T125_INV_29_human0_0_ratification_not_delegatable():
    """T125-INV-29: COMMUNITY-HUMAN0-0 — no workflow job merges or ratifies autonomously."""
    content = WORKFLOW.read_text().lower()
    # Workflow must not contain merge steps targeting main
    forbidden_merge_patterns = [
        "git merge",
        "git push origin main",
        "auto-merge: true",
        "merge_method",
    ]
    violations = [p for p in forbidden_merge_patterns if p in content]
    assert len(violations) == 0, (
        f"COMMUNITY-HUMAN0-0 violation — autonomous merge patterns in workflow:\n"
        + "\n".join(violations)
    )


@pytest.mark.phase125
def test_T125_INV_30_governance_artifacts_phase125_present():
    """T125-INV-30: Phase 125 governance artifact directory and sign-off file exist."""
    artifact_dir = ROOT / "artifacts" / "governance" / "phase125"
    assert artifact_dir.exists(), "artifacts/governance/phase125/ directory not found"
    sign_off = artifact_dir / "phase125_sign_off.json"
    assert sign_off.exists(), "phase125_sign_off.json not found"
    data = json.loads(sign_off.read_text())
    assert data["phase"] == 125
    assert data["status"] == "ratified"
    assert "COMMUNITY-FGCON-0" in data["invariants"]
    assert "COMMUNITY-HUMAN0-0" in data["invariants"]
    assert data["cumulative_hard_invariants"] == 167
