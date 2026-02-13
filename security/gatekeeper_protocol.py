# SPDX-License-Identifier: Apache-2.0
"""
Gatekeeper protocol stub for Phase-2 drift detection.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, List

REQUIRED_DIRS = [
    Path("app"),
    Path("runtime"),
    Path("security"),
    Path("security/ledger"),
    Path("security/keys"),
]


def run_gatekeeper() -> Dict[str, object]:
    missing: List[str] = []
    for path in REQUIRED_DIRS:
        if not path.exists():
            missing.append(str(path))

    manifest: List[Dict[str, str]] = []
    app_root = Path("app")
    for p in sorted(app_root.rglob("*")):
        if p.is_dir():
            continue
        # Exclude dotfiles and .gitkeep placeholders to avoid false positives from
        # local/editor metadata and empty-directory sentinels.
        if p.name.startswith(".") or p.name.endswith(".gitkeep"):
            continue
        rel_path = p.relative_to(app_root.parent).as_posix()
        file_hash = hashlib.sha256(p.read_bytes()).hexdigest()
        manifest.append({"path": rel_path, "sha256": file_hash})

    manifest_payload = json.dumps(sorted(manifest, key=lambda item: item["path"]), sort_keys=True)
    digest = hashlib.sha256(manifest_payload.encode("utf-8")).hexdigest()
    ledger_hash_file = Path("security/ledger/gate_hash.txt")
    prev = ledger_hash_file.read_text(encoding="utf-8").strip() if ledger_hash_file.exists() else None
    drift = prev is not None and prev != digest

    try:
        ledger_hash_file.parent.mkdir(parents=True, exist_ok=True)
        ledger_hash_file.write_text(digest, encoding="utf-8")
    except Exception:
        pass

    ok = not missing and not drift
    payload = {"ok": ok, "missing": missing, "hash": digest}
    if drift:
        payload["drift"] = True
    return payload


__all__ = ["run_gatekeeper"]
