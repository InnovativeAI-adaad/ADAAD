#!/usr/bin/env python3
"""Validate that Git SHAs referenced in release artifacts resolve locally."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

HEX_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
TEXT_SHA_RE = re.compile(
    r"(?i)(?:\b(?:commit|merge|release|head|base)[_ -]?sha\b|\bsha\b(?!256|512))"
    r"[^\n]{0,32}?\b([0-9a-f]{7,40})\b"
)


def _git_ref_resolves(ref: str) -> bool:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{ref}^{{commit}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _iter_json_sha_refs(payload: Any, path: tuple[str, ...] = ()) -> Iterable[tuple[str, str]]:
    if isinstance(payload, dict):
        for key, value in payload.items():
            next_path = (*path, str(key))
            key_lc = str(key).lower()
            if isinstance(value, str):
                value_lc = value.lower().strip()
                if (
                    "sha" in key_lc
                    and "sha256" not in key_lc
                    and "sha512" not in key_lc
                    and "digest" not in key_lc
                    and "hash" not in key_lc
                    and HEX_SHA_RE.match(value_lc)
                ):
                    yield (".".join(next_path), value_lc)
            yield from _iter_json_sha_refs(value, next_path)
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            yield from _iter_json_sha_refs(item, (*path, str(index)))


def _iter_text_sha_refs(text: str) -> Iterable[str]:
    for match in TEXT_SHA_RE.finditer(text):
        candidate = match.group(1).lower()
        if HEX_SHA_RE.match(candidate):
            yield candidate


def _validate_file(path: Path) -> list[tuple[str, str]]:
    unresolved: list[tuple[str, str]] = []
    suffix = path.suffix.lower()

    if suffix == ".json":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return unresolved
        for pointer, ref in _iter_json_sha_refs(payload):
            if not _git_ref_resolves(ref):
                unresolved.append((f"{path.as_posix()}::{pointer}", ref))
        return unresolved

    if suffix in {".md", ".txt", ".jsonl", ".yml", ".yaml"}:
        for ref in sorted(set(_iter_text_sha_refs(path.read_text(encoding="utf-8")))):
            if not _git_ref_resolves(ref):
                unresolved.append((path.as_posix(), ref))
    return unresolved


def _iter_files(roots: Iterable[Path]) -> Iterable[Path]:
    allowed = {".json", ".md", ".txt", ".jsonl", ".yml", ".yaml"}
    for root in roots:
        if root.is_file() and root.suffix.lower() in allowed:
            yield root
            continue
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in allowed:
                yield path


def _git_diff_paths(base_ref: str | None, pathspecs: list[str]) -> list[Path]:
    diff_cmd = ["git", "diff", "--name-only", "--diff-filter=ACMRTUXB"]
    diff_cmd.append(base_ref or "HEAD~1..HEAD")
    diff_cmd.extend(["--", *pathspecs])
    result = subprocess.run(diff_cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return []
    files: list[Path] = []
    for line in result.stdout.splitlines():
        path = Path(line.strip())
        if path.exists() and path.is_file():
            files.append(path)
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate release artifact Git SHA references.")
    parser.add_argument(
        "--base-ref",
        default=None,
        help="Optional git diff range when mode=changed (for example: origin/main...HEAD).",
    )
    parser.add_argument(
        "--mode",
        choices=["changed", "roots"],
        default="changed",
        help="Validation scope: changed files or explicit roots.",
    )
    parser.add_argument(
        "--roots",
        nargs="+",
        default=[
            "docs/releases",
            "artifacts/release_decisions",
            "reports",
        ],
        help="Paths to scan for release metadata references.",
    )
    args = parser.parse_args()

    if args.mode == "changed":
        files = sorted(
            set(
                _git_diff_paths(
                    args.base_ref,
                    ["docs/releases", "artifacts", "reports", "docs/governance/POST_PIPELINE_STRATEGIC_PLAN.md"],
                )
            )
        )
    else:
        files = sorted(set(_iter_files(Path(root) for root in args.roots)))

    if not files:
        print("no changed release artifact files detected; skipping Git SHA resolution check")
        return 0

    unresolved: list[tuple[str, str]] = []
    for path in files:
        unresolved.extend(_validate_file(path))

    if unresolved:
        print("unresolvable Git SHA references found:")
        for location, ref in unresolved:
            print(f" - {location}: {ref}")
        return 1

    print(f"validated {len(files)} artifact files: all referenced Git SHAs are resolvable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
