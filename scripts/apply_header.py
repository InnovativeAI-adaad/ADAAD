#!/usr/bin/env python3
# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved
import io
import os
import pathlib
import re
import sys

TAG = "# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved"
SKIP = {".git", "__pycache__", "venv", ".venv", "node_modules", "reports/cryovant.db"}
EXTS = {".py", ".sh", ".ps1", ".json", ".jsonl", ".yml", ".yaml", ".md", ".html", ".css", ".js", ".ts"}


def tagged(text: str) -> bool:
    lines = text.splitlines()
    return TAG in lines[:5] or TAG in lines[-5:]


def add_tag(path: pathlib.Path) -> None:
    text = path.read_text(encoding="utf-8", errors="ignore")
    if tagged(text):
        return
    if path.suffix in {".md", ".html"}:
        updated = text.rstrip() + "\n\n" + TAG + "\n"
    else:
        updated = TAG + "\n" + text
    path.write_text(updated, encoding="utf-8")


def should_skip(path: pathlib.Path, rel_parts: tuple[str, ...]) -> bool:
    if any(part in SKIP for part in rel_parts):
        return True
    rel = path.as_posix()
    return rel in SKIP


def main(root: str = ".") -> None:
    base = pathlib.Path(root).resolve()
    for dirpath, dirnames, filenames in os.walk(base):
        rel_parts = pathlib.Path(dirpath).relative_to(base).parts
        if should_skip(pathlib.Path(dirpath), rel_parts):
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if not should_skip(pathlib.Path(dirpath) / d, rel_parts + (d,))]
        for name in filenames:
            path = pathlib.Path(dirpath) / name
            if should_skip(path, rel_parts + (name,)):
                continue
            if path.suffix.lower() in EXTS and path.is_file():
                add_tag(path)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
