# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List


REPO_ROOT_ALLOWED_TOPLEVEL = {
    "app",
    "runtime",
    "security",
    "tests",
    "docs",
    "data",
    "reports",
    "releases",
    "experiments",
    "scripts",
    "ui",
    "tools",
    "archives",
}


FORBIDDEN_DEFAULT = (
    "security/keys/",
    "security/ledger/",
)


ABS_PATH_PATTERNS = (
    "/home/",
    "C\\\\",
    "D\\\\",
    "from /",
    "import /",
)


@dataclass
class ValidationIssue:
    path: str
    reason: str


def normalize_rel_path(p: str) -> str:
    p = p.replace("\\", "/").lstrip("/")
    while p.startswith("./"):
        p = p[2:]
    return p


def validate_paths(files: Iterable[str], allowed: List[str], forbidden: List[str]) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    allow_norm = [normalize_rel_path(x) for x in allowed]
    forbid_norm = [normalize_rel_path(x) for x in forbidden] + [normalize_rel_path(x) for x in FORBIDDEN_DEFAULT]

    for f in files:
        rel = normalize_rel_path(f)

        top = rel.split("/", 1)[0] if rel else ""
        if top and top not in REPO_ROOT_ALLOWED_TOPLEVEL:
            issues.append(ValidationIssue(rel, "touches non-canonical top-level directory"))

        for fx in forbid_norm:
            if fx and rel.startswith(fx):
                issues.append(ValidationIssue(rel, f"forbidden path: {fx}"))

        ok = False
        for ax in allow_norm:
            axn = ax.rstrip("/")
            if rel == axn or rel.startswith(axn + "/") or (ax.endswith("/") and rel.startswith(ax)):
                ok = True
                break
        if not ok:
            issues.append(ValidationIssue(rel, "not in allowed_paths"))

    return issues


def validate_canonical_imports(py_text: str) -> str | None:
    if "from .." in py_text or "import .." in py_text:
        return "relative import detected"
    for pat in ABS_PATH_PATTERNS:
        if pat in py_text:
            return f"absolute path pattern detected: {pat}"
    return None


def scan_python_files_for_import_violations(repo_root: Path, files: Iterable[str]) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for rel in files:
        reln = normalize_rel_path(rel)
        if not reln.endswith(".py"):
            continue
        p = (repo_root / reln).resolve()
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            issues.append(ValidationIssue(reln, "cannot read file for import validation"))
            continue
        reason = validate_canonical_imports(text)
        if reason:
            issues.append(ValidationIssue(reln, reason))
    return issues
