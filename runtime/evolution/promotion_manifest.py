# SPDX-License-Identifier: Apache-2.0
"""Promotion manifest writer for mutation promotion audit trails."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict

from runtime import ROOT_DIR

PROMOTION_MANIFESTS_DIR = ROOT_DIR / "security" / "promotion_manifests"


class PromotionManifestWriter:
    """Write one JSON manifest per promoted mutation."""

    def __init__(self, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir or PROMOTION_MANIFESTS_DIR

    @staticmethod
    def _canonical_hash(payload: Dict[str, Any]) -> str:
        material = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(material).hexdigest()

    def write(self, payload: Dict[str, Any]) -> Dict[str, str]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d%H%M%S", time.gmtime())
        parent_id = str(payload.get("parent_id") or "unknown")
        child_id = str(payload.get("child_id") or "unknown")
        label = f"{ts}_{parent_id.replace(':', '_').replace('/', '_')}__{child_id.replace(':', '_').replace('/', '_')}"
        manifest_path = self.output_dir / f"{label}.json"
        manifest_payload = dict(payload)
        manifest_payload["manifest_schema_version"] = "1.0"
        manifest_payload["written_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        manifest_hash = self._canonical_hash(manifest_payload)
        manifest_payload["manifest_hash"] = f"sha256:{manifest_hash}"
        manifest_path.write_text(json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return {
            "manifest_path": str(manifest_path),
            "manifest_hash": manifest_payload["manifest_hash"],
        }


__all__ = ["PromotionManifestWriter", "PROMOTION_MANIFESTS_DIR"]
