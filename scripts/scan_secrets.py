# SPDX-License-Identifier: Apache-2.0
#!/usr/bin/env python3
"""Deterministic repository secret scanner for high-risk plaintext credential patterns."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

TEXT_EXTENSIONS = {
    ".py",
    ".md",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".env",
    ".sh",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".html",
    ".css",
    ".xml",
    ".csv",
}

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "dist",
    "build",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
}

SKIP_FILES = {
    ".env.example",
    ".env.github_app",
}


@dataclass(frozen=True)
class SecretRule:
    name: str
    pattern: re.Pattern[str]


SECRET_RULES = (
    SecretRule("private_key_block", re.compile(r"-----BEGIN(?: RSA| EC| OPENSSH)? PRIVATE KEY-----")),
    SecretRule("github_pat", re.compile(r"\bghp_[A-Za-z0-9]{36}\b")),
    SecretRule("github_fine_grained_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{80,}\b")),
    SecretRule("generic_api_key_assignment", re.compile(r"(?i)\b(api[_-]?key|client[_-]?secret|oauth[_-]?client[_-]?secret)\b\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}")),
    SecretRule("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    SecretRule("stripe_live_key", re.compile(r"\bsk_live_[A-Za-z0-9]{16,}\b")),
    SecretRule("aws_access_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
)

ALLOWLIST_FINDINGS = {
    ("docs/ADAADCHAT_SETUP.md", "private_key_block"),
}


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str


def _is_text_candidate(path: Path) -> bool:
    if path.name in SKIP_FILES:
        return False
    if path.suffix in TEXT_EXTENSIONS:
        return True
    if path.suffixes[-2:] == [".json", ".template"]:
        return True
    return path.suffix == ""


def iter_candidate_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        if _is_text_candidate(path):
            files.append(path)
    return files


def scan_file(path: Path) -> list[Finding]:
    findings: list[Finding] = []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return findings

    for line_no, line in enumerate(text.splitlines(), start=1):
        for rule in SECRET_RULES:
            if rule.pattern.search(line):
                findings.append(Finding(path=str(path), line=line_no, rule=rule.name))
    return findings


def scan_path(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for file_path in iter_candidate_files(root):
        findings.extend(scan_file(file_path))
    filtered: list[Finding] = []
    for finding in findings:
        relative_path = Path(finding.path).resolve().relative_to(root).as_posix()
        if (relative_path, finding.rule) in ALLOWLIST_FINDINGS:
            continue
        filtered.append(finding)
    return filtered


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan repository content for obvious plaintext secrets.")
    parser.add_argument("--path", default=".", help="Directory to scan (default: current directory)")
    args = parser.parse_args(argv)

    root = Path(args.path).resolve()
    findings = scan_path(root)
    if findings:
        print("[secret-scan] plaintext secret pattern(s) detected:")
        for finding in findings:
            print(f" - {finding.path}:{finding.line} [{finding.rule}]")
        return 1

    print("[secret-scan] no plaintext secret patterns detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
