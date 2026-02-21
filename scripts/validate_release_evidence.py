#!/usr/bin/env python3
"""Validate claims-to-evidence matrix entries for release readiness."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

MATRIX_PATH = Path("docs/comms/claims_evidence_matrix.md")
REQUIRED_CLAIM_IDS = {
    "ci-status-requirements",
    "replay-proof-outputs",
    "forensic-bundle-examples",
    "codeql-status",
    "versioned-docs-spec-links",
}
DISALLOWED_TOKENS = {"tbd", "todo", "coming soon"}
TABLE_ROW_PATTERN = re.compile(r"^\|\s*`(?P<claim_id>[^`]+)`\s*\|(?P<rest>.*)\|\s*$")
MARKDOWN_LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="Fail unless all required claims are marked Complete.",
    )
    return parser.parse_args()


def _is_http_link(link: str) -> bool:
    return link.startswith("http://") or link.startswith("https://")


def _normalize_local_target(link: str, base_dir: Path) -> Path:
    clean_link = link.split("#", 1)[0]
    return (base_dir / clean_link).resolve()


def main() -> int:
    args = _parse_args()

    if not MATRIX_PATH.exists():
        print(f"ERROR: missing matrix file: {MATRIX_PATH}")
        return 1

    matrix_text = MATRIX_PATH.read_text(encoding="utf-8")
    rows: dict[str, dict[str, str | list[str]]] = {}

    for line in matrix_text.splitlines():
        match = TABLE_ROW_PATTERN.match(line.strip())
        if not match:
            continue
        claim_id = match.group("claim_id").strip()
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        evidence_cell = cells[2]
        status_cell = cells[3]
        links = MARKDOWN_LINK_PATTERN.findall(evidence_cell)
        rows[claim_id] = {"status": status_cell, "links": links, "evidence": evidence_cell}

    errors: list[str] = []

    missing_claims = REQUIRED_CLAIM_IDS - rows.keys()
    if missing_claims:
        errors.append(f"missing required claims: {', '.join(sorted(missing_claims))}")

    repo_root = Path.cwd().resolve()
    matrix_dir = MATRIX_PATH.parent.resolve()

    for claim_id in sorted(REQUIRED_CLAIM_IDS & rows.keys()):
        row = rows[claim_id]
        status = str(row["status"]).strip()
        evidence_cell = str(row["evidence"]).lower()
        links = [str(link).strip() for link in row["links"]]

        if not links:
            errors.append(f"{claim_id}: missing evidence links")

        for token in DISALLOWED_TOKENS:
            if token in evidence_cell:
                errors.append(f"{claim_id}: evidence contains placeholder token '{token}'")

        if args.require_complete and status != "Complete":
            errors.append(f"{claim_id}: status must be 'Complete' (found '{status}')")

        for link in links:
            if _is_http_link(link):
                continue
            target = _normalize_local_target(link, matrix_dir)
            try:
                target.relative_to(repo_root)
            except ValueError:
                errors.append(f"{claim_id}: link escapes repository root: {link}")
                continue
            if not target.exists():
                errors.append(f"{claim_id}: missing linked artifact: {link}")

    if errors:
        print("Release evidence validation failed:")
        for err in errors:
            print(f" - {err}")
        return 1

    print("Release evidence validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
