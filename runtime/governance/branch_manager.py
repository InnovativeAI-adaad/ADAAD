from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Sequence

from runtime import REPO_ROOT

DEFAULT_SOURCES: Sequence[str] = ("app", "runtime", "security", "server.py")
EXCLUDE_PATTERNS: Sequence[str] = (".git", ".pytest_cache", "__pycache__", "*.log", "*.pyc", "node_modules")

ALLOWED_PROMOTE_ROOTS = {"app", "runtime", "security", "ui", "tools"}
FORBIDDEN_SUBPATHS = {"security/keys"}


def json_dump(payload: object) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)


def _atomic_copy(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    shutil.copy2(src, tmp)
    os.replace(tmp, dest)


def _is_forbidden(rel: str) -> bool:
    rel_norm = rel.replace("\\", "/").lstrip("/")
    if not rel_norm:
        return True
    if rel_norm.startswith("../") or "/../" in rel_norm or rel_norm == "..":
        return True
    parts = Path(rel_norm).parts
    if not parts:
        return True
    if parts[0] not in ALLOWED_PROMOTE_ROOTS:
        return True
    for forb in FORBIDDEN_SUBPATHS:
        if rel_norm.startswith(forb + "/") or rel_norm == forb:
            return True
    return False


@dataclass
class BranchManager:
    repo_root: Path = REPO_ROOT
    branches_dir: Path = field(default_factory=lambda: REPO_ROOT / "experiments" / "branches")
    sources: Sequence[str] = DEFAULT_SOURCES

    def _source_paths(self) -> Iterable[Path]:
        for rel in self.sources:
            p = self.repo_root / rel
            if p.exists():
                yield p

    def _ignore(self, _src: str, names: List[str]) -> List[str]:
        ignored: List[str] = []
        src_path = Path(_src).as_posix().replace("\\", "/")
        if src_path.endswith("/security") and "keys" in names:
            ignored.append("keys")
        for pattern in EXCLUDE_PATTERNS:
            ignored.extend([name for name in names if Path(name).match(pattern)])
        return ignored

    def create_branch(self, branch_name: str) -> Path:
        branch_path = self.branches_dir / branch_name
        if branch_path.exists():
            shutil.rmtree(branch_path)
        branch_path.mkdir(parents=True, exist_ok=True)

        manifest = {"created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "sources": []}
        for src_path in self._source_paths():
            dest = branch_path / src_path.relative_to(self.repo_root)
            if src_path.is_dir():
                shutil.copytree(src_path, dest, ignore=self._ignore)
            else:
                _atomic_copy(src_path, dest)
            manifest["sources"].append(str(src_path.relative_to(self.repo_root)))

        (branch_path / ".manifest.json").write_text(json_dump(manifest), encoding="utf-8")
        return branch_path

    def promote(self, branch_name: str, relative_paths: Sequence[str]) -> List[Path]:
        if not relative_paths:
            raise ValueError("Promotion requires explicit targets.")

        branch_path = self.branches_dir / branch_name
        if not branch_path.exists():
            raise FileNotFoundError(f"branch not found: {branch_path}")

        promoted: List[Path] = []
        for rel in relative_paths:
            rel_str = str(rel)
            if _is_forbidden(rel_str):
                raise PermissionError(f"Forbidden promotion path: {rel_str}")

            src = branch_path / rel_str
            if not src.exists() or src.is_dir():
                continue

            dest = self.repo_root / rel_str
            _atomic_copy(src, dest)
            promoted.append(dest)

        return promoted


__all__ = ["BranchManager"]
