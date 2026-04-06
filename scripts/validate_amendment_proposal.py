#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
validate_amendment_proposal.py
Phase 125 — Community Governance Infrastructure

Validates constitutional amendment proposal documents against the structural
requirements defined in CONSTITUTION_PROPOSALS.md.

Runs identically in CI (constitution_amendment_validation.yml) and locally.

Usage
-----
    python scripts/validate_amendment_proposal.py --input proposal.md
    python scripts/validate_amendment_proposal.py --input proposal.md --output result.json

Exit codes
----------
    0  All checks passed
    1  One or more checks failed
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RATIONALE_MIN_WORDS: int = 50
INVARIANT_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z][A-Z0-9]*)*-\d+$")

REQUIRED_FIELD_MARKERS = [
    "PROPOSED_INVARIANT_ID",
    "affected modules",
    "conflict analysis",
]

FGCON_CHECKBOXES = [
    "I confirm I am not the ratifying principal",
    "I understand HUMAN-0 ratification",
    "I have read `CONSTITUTION_PROPOSALS.md`",
]

AUTO_RATIFICATION_FORBIDDEN = [
    "auto-ratif",
    "auto_ratif",
    "self-ratif",
    "self_ratif",
    "bypass human",
    "bypass human-0",
    "delegate ratif",
]


# ---------------------------------------------------------------------------
# Validation logic
# ---------------------------------------------------------------------------

def _extract_invariant_id(body: str) -> str | None:
    """Extract the proposed invariant identifier from the proposal body.

    Intentionally permissive: captures any non-whitespace token after the key
    so that malformed (e.g. lowercase) IDs are extracted and then rejected by
    the format check, rather than silently treated as absent.
    """
    match = re.search(r"PROPOSED_INVARIANT_ID:[ \t]*(\S+)", body)
    if match:
        candidate = match.group(1).strip()
        return candidate if candidate else None
    return None


def _extract_rationale(body: str) -> str:
    """Extract the rationale section text."""
    # Between ## Rationale and the next ## header
    match = re.search(
        r"## Rationale\s*\n.*?\n\s*\*\[(.+?)\]\*|## Rationale\s*\n(.*?)(?=\n## )",
        body,
        re.DOTALL,
    )
    if match:
        text = match.group(1) or match.group(2) or ""
        return text.strip()

    # Fallback: grab everything between ## Rationale and next ##
    lines = body.split("\n")
    in_rationale = False
    rationale_lines: list[str] = []
    for line in lines:
        if line.strip().startswith("## Rationale"):
            in_rationale = True
            continue
        if in_rationale and line.strip().startswith("## "):
            break
        if in_rationale:
            rationale_lines.append(line)
    return " ".join(rationale_lines).strip()


def _count_words(text: str) -> int:
    """Count non-empty words in text, stripping markdown."""
    text = re.sub(r"[`*_\[\]()#>|]", " ", text)
    text = re.sub(r"https?://\S+", "", text)
    return len([w for w in text.split() if w.strip()])


def _invariant_class_selected(body: str) -> bool:
    """Check that exactly one invariant class checkbox is checked."""
    hard_checked = bool(re.search(r"\[x\]\s*\*\*Hard\*\*", body, re.IGNORECASE))
    soft_checked = bool(re.search(r"\[x\]\s*\*\*Soft\*\*", body, re.IGNORECASE))
    return hard_checked or soft_checked


def _detect_invariant_class(body: str) -> str:
    """Return 'Hard', 'Soft', or 'unknown'."""
    if re.search(r"\[x\]\s*\*\*Hard\*\*", body, re.IGNORECASE):
        return "Hard"
    if re.search(r"\[x\]\s*\*\*Soft\*\*", body, re.IGNORECASE):
        return "Soft"
    return "unknown"


def _fgcon_checkboxes_checked(body: str) -> list[str]:
    """Return list of unchecked FGCON confirmation items."""
    missing: list[str] = []
    for phrase in FGCON_CHECKBOXES:
        # Pattern: [x] ...phrase...
        pattern = re.compile(
            r"\[x\].*?" + re.escape(phrase[:30]),
            re.IGNORECASE | re.DOTALL,
        )
        if not pattern.search(body):
            missing.append(phrase)
    return missing


def _has_proposed_test(body: str) -> bool:
    """Check that a test ID and description are present."""
    has_id = bool(re.search(r"T\d{3}-[A-Z]+-\d{2}", body))
    has_description = "## Proposed Acceptance Test" in body
    return has_id and has_description


def _has_affected_modules(body: str) -> bool:
    """Check that at least one module path is listed."""
    match = re.search(
        r"## Affected Modules\s*\n(.*?)(?=\n## )", body, re.DOTALL
    )
    if not match:
        return False
    section = match.group(1).strip()
    # Must have at least one non-placeholder line
    lines = [
        ln.strip()
        for ln in section.split("\n")
        if ln.strip() and not ln.strip().startswith("<!--") and "..." not in ln
    ]
    return len(lines) > 0


def _has_conflict_analysis(body: str) -> bool:
    """Check that conflict analysis section is present and non-placeholder."""
    match = re.search(
        r"## Conflict Analysis\s*\n(.*?)(?=\n## )", body, re.DOTALL
    )
    if not match:
        return False
    section = match.group(1).strip()
    return bool(section) and section != "*[Conflict analysis here]*"


def _auto_ratification_claims(body: str) -> list[str]:
    """Return any forbidden auto-ratification phrases found."""
    found: list[str] = []
    body_lower = body.lower()
    for phrase in AUTO_RATIFICATION_FORBIDDEN:
        if phrase in body_lower:
            found.append(phrase)
    return found


# ---------------------------------------------------------------------------
# Main validation runner
# ---------------------------------------------------------------------------

def validate(body: str) -> dict[str, Any]:
    """
    Run all structural checks against a proposal body.

    Returns a result dict with:
        valid (bool)
        checks_passed (list[str])
        checks_failed (list[str])
        proposed_invariant (str | None)
        invariant_class (str)
        rationale_word_count (int)
    """
    checks_passed: list[str] = []
    checks_failed: list[str] = []

    # 1. PROPOSED_INVARIANT_ID present and well-formed
    inv_id = _extract_invariant_id(body)
    if inv_id and INVARIANT_ID_PATTERN.match(inv_id):
        checks_passed.append(f"Invariant ID present and well-formed: {inv_id}")
    elif inv_id:
        checks_failed.append(
            f"Invariant ID '{inv_id}' does not match required pattern "
            "CATEGORY-KEYWORD-N (e.g. MY-FEAT-0)"
        )
    else:
        checks_failed.append(
            "PROPOSED_INVARIANT_ID field is missing or empty — "
            "provide a unique identifier in CATEGORY-KEYWORD-N format"
        )

    # 2. Invariant class selected
    if _invariant_class_selected(body):
        inv_class = _detect_invariant_class(body)
        checks_passed.append(f"Invariant class selected: {inv_class}")
    else:
        inv_class = "unknown"
        checks_failed.append(
            "Invariant class not selected — check [x] Hard or [x] Soft"
        )

    # 3. Rationale word count ≥ 50
    rationale_text = _extract_rationale(body)
    word_count = _count_words(rationale_text)
    if word_count >= RATIONALE_MIN_WORDS:
        checks_passed.append(
            f"Rationale meets word count minimum: {word_count} words (≥{RATIONALE_MIN_WORDS})"
        )
    else:
        checks_failed.append(
            f"Rationale too short: {word_count} words — minimum {RATIONALE_MIN_WORDS} required"
        )

    # 4. Affected modules listed
    if _has_affected_modules(body):
        checks_passed.append("Affected modules section populated")
    else:
        checks_failed.append(
            "Affected modules section missing or contains only placeholders"
        )

    # 5. Proposed test present
    if _has_proposed_test(body):
        checks_passed.append("Proposed acceptance test present with test ID")
    else:
        checks_failed.append(
            "Proposed acceptance test missing or test ID not in format T###-CAT-NN"
        )

    # 6. Conflict analysis present
    if _has_conflict_analysis(body):
        checks_passed.append("Conflict analysis section populated")
    else:
        checks_failed.append(
            "Conflict analysis section missing or contains only placeholder text"
        )

    # 7. FGCON quorum checkboxes
    missing_boxes = _fgcon_checkboxes_checked(body)
    if not missing_boxes:
        checks_passed.append("All three FGCON quorum confirmation checkboxes checked")
    else:
        for item in missing_boxes:
            checks_failed.append(f"FGCON checkbox unchecked: '{item[:60]}...'")

    # 8. No auto-ratification claims
    auto_rat = _auto_ratification_claims(body)
    if not auto_rat:
        checks_passed.append("No auto-ratification claims detected (COMMUNITY-HUMAN0-0 preserved)")
    else:
        for phrase in auto_rat:
            checks_failed.append(
                f"Forbidden auto-ratification claim detected: '{phrase}' "
                "— violates COMMUNITY-HUMAN0-0"
            )

    return {
        "valid": len(checks_failed) == 0,
        "checks_passed": checks_passed,
        "checks_failed": checks_failed,
        "proposed_invariant": inv_id,
        "invariant_class": inv_class,
        "rationale_word_count": word_count,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a constitutional amendment proposal document."
    )
    parser.add_argument(
        "--input", "-i", required=True, help="Path to the proposal markdown file."
    )
    parser.add_argument(
        "--output", "-o", default=None, help="Path to write JSON result (optional)."
    )
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: Input file not found: {input_path}", file=sys.stderr)
        return 1

    body = input_path.read_text(encoding="utf-8")
    result = validate(body)

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    # Human-readable summary
    print("\n" + "=" * 60)
    print("ADAAD Constitutional Amendment Validation")
    print("=" * 60)
    print(f"Result: {'✅ PASSED' if result['valid'] else '❌ FAILED'}")
    if result["proposed_invariant"]:
        print(f"Invariant: {result['proposed_invariant']} ({result['invariant_class']})")
    print(f"Rationale words: {result['rationale_word_count']}")
    print()
    if result["checks_passed"]:
        print("Passed:")
        for c in result["checks_passed"]:
            print(f"  ✅ {c}")
    if result["checks_failed"]:
        print("Failed:")
        for c in result["checks_failed"]:
            print(f"  ❌ {c}")
    print("=" * 60 + "\n")

    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
