# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List

from tools.codex.validators import normalize_rel_path


HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class DiffFile:
    a_path: str
    b_path: str
    is_new: bool
    is_deleted: bool
    hunks: List[List[str]]


def _parse_diff_files(diff_text: str) -> List[DiffFile]:
    lines = diff_text.splitlines()
    i = 0
    files: List[DiffFile] = []

    while i < len(lines):
        line = lines[i]
        if not line.startswith("diff --git "):
            i += 1
            continue

        parts = line.split()
        if len(parts) < 4:
            raise ValueError("malformed diff header")
        a_raw = parts[2]
        b_raw = parts[3]
        a_path = normalize_rel_path(a_raw.replace("a/", "", 1))
        b_path = normalize_rel_path(b_raw.replace("b/", "", 1))

        i += 1
        while i < len(lines):
            if lines[i].startswith("--- "):
                break
            i += 1
        if i >= len(lines):
            raise ValueError("missing --- header")
        a_mark = lines[i]
        i += 1
        if i >= len(lines) or not lines[i].startswith("+++ "):
            raise ValueError("missing +++ header")
        b_mark = lines[i]
        i += 1

        is_new = (a_mark.strip() == "--- /dev/null")
        is_deleted = (b_mark.strip() == "+++ /dev/null")

        hunks: List[List[str]] = []
        cur: List[str] = []
        while i < len(lines):
            if lines[i].startswith("diff --git "):
                break
            if lines[i].startswith("@@ "):
                if cur:
                    hunks.append(cur)
                cur = [lines[i]]
            else:
                if cur:
                    cur.append(lines[i])
            i += 1
        if cur:
            hunks.append(cur)

        files.append(DiffFile(a_path=a_path, b_path=b_path, is_new=is_new, is_deleted=is_deleted, hunks=hunks))

    return files


def touched_paths(diff_text: str) -> List[str]:
    files = _parse_diff_files(diff_text)
    out: List[str] = []
    for f in files:
        out.append(f.b_path if not f.is_deleted else f.a_path)
    return sorted(set(out))


def _apply_hunks_to_lines(orig: List[str], hunks: List[List[str]]) -> List[str]:
    out = orig[:]
    line_offset = 0

    for h in hunks:
        if not h:
            continue
        m = HUNK_RE.match(h[0])
        if not m:
            raise ValueError("malformed hunk header")
        old_start = int(m.group(1))
        old_len = int(m.group(2) or "1")
        new_start = int(m.group(3))

        idx = (old_start - 1) + line_offset

        expected_old: List[str] = []
        replacement: List[str] = []
        for ln in h[1:]:
            if not ln:
                ch = " "
                body = ""
            else:
                ch = ln[0]
                body = ln[1:] if len(ln) > 1 else ""
            if ch == " ":
                expected_old.append(body)
                replacement.append(body)
            elif ch == "-":
                expected_old.append(body)
            elif ch == "+":
                replacement.append(body)
            elif ch == "\\":
                continue
            else:
                raise ValueError("unknown hunk line prefix")

        existing = out[idx : idx + len(expected_old)]
        if existing != expected_old:
            found = -1
            for probe in range(max(0, idx - 5), min(len(out), idx + 6)):
                if out[probe : probe + len(expected_old)] == expected_old:
                    found = probe
                    break
            if found == -1:
                raise ValueError("hunk context mismatch")
            idx = found
            existing = out[idx : idx + len(expected_old)]
            if existing != expected_old:
                raise ValueError("hunk context mismatch")

        out[idx : idx + len(expected_old)] = replacement
        line_offset += (len(replacement) - len(expected_old))

    return out


def apply_unified_diff_to_repo(*, repo_root: Path, diff_text: str) -> List[str]:
    files = _parse_diff_files(diff_text)
    touched: List[str] = []

    for f in files:
        rel_a = normalize_rel_path(f.a_path)
        rel_b = normalize_rel_path(f.b_path)

        if f.is_deleted:
            target = repo_root / rel_a
            if target.exists():
                target.unlink()
            touched.append(rel_a)
            continue

        target_rel = rel_b
        target = repo_root / target_rel
        target.parent.mkdir(parents=True, exist_ok=True)

        if f.is_new and not target.exists():
            orig_lines: List[str] = []
        else:
            try:
                orig_text = target.read_text(encoding="utf-8", errors="ignore")
            except FileNotFoundError:
                orig_text = ""
            orig_lines = orig_text.splitlines()

        new_lines = _apply_hunks_to_lines(orig_lines, f.hunks)
        target.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        touched.append(target_rel)

    return sorted(set(touched))


def clone_repo_subset(*, src_root: Path, dst_root: Path) -> None:
    if dst_root.exists():
        shutil.rmtree(dst_root)
    dst_root.mkdir(parents=True, exist_ok=True)

    include = [
        "app",
        "runtime",
        "security",
        "tools",
        "ui",
        "tests",
        "reports",
        "data",
        "scripts",
        "docs",
        "experiments",
    ]

    for name in include:
        src = src_root / name
        if not src.exists():
            continue
        dst = dst_root / name
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def promote_changes(*, scratch_root: Path, repo_root: Path, touched: List[str]) -> None:
    for rel in touched:
        reln = normalize_rel_path(rel)
        src = scratch_root / reln
        dst = repo_root / reln
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        else:
            if dst.exists():
                dst.unlink()
