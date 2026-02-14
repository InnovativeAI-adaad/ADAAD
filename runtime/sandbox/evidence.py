# SPDX-License-Identifier: Apache-2.0
"""Sandbox evidence generation and append-only ledger."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from runtime import ROOT_DIR
from runtime.governance.foundation import ZERO_HASH, canonical_json, sha256_prefixed_digest

SANDBOX_EVIDENCE_PATH = ROOT_DIR / "security" / "ledger" / "sandbox_evidence.jsonl"


def build_sandbox_evidence(
    *,
    manifest: Dict[str, Any],
    result: Dict[str, Any],
    policy_hash: str,
    syscall_trace: tuple[str, ...] = (),
    provider_ts: str,
) -> Dict[str, Any]:
    stdout = str(result.get("stdout", ""))
    stderr = str(result.get("stderr", ""))
    resource_usage = {
        "duration_s": float(result.get("duration_s", 0.0) or 0.0),
        "memory_mb": float(result.get("memory_mb", 0.0) or 0.0),
        "disk_mb": float(result.get("disk_mb", 0.0) or 0.0),
    }
    payload = {
        "manifest_hash": sha256_prefixed_digest(manifest),
        "policy_hash": policy_hash,
        "stdout_hash": sha256_prefixed_digest(stdout),
        "stderr_hash": sha256_prefixed_digest(stderr),
        "syscall_trace_hash": sha256_prefixed_digest(list(syscall_trace)),
        "resource_usage": resource_usage,
        "exit_code": result.get("returncode"),
        "replay_seed": str(manifest.get("replay_seed") or ""),
        "timestamp": provider_ts,
        "manifest": dict(manifest),
    }
    payload["evidence_hash"] = sha256_prefixed_digest(payload)
    return payload


class SandboxEvidenceLedger:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or SANDBOX_EVIDENCE_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")

    def _last_hash(self) -> str:
        lines = self.path.read_text(encoding="utf-8").splitlines()
        if not lines:
            return ZERO_HASH
        last = json.loads(lines[-1])
        return str(last.get("hash") or ZERO_HASH)

    def append(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        prev_hash = self._last_hash()
        entry = {"payload": dict(payload), "prev_hash": prev_hash}
        entry["hash"] = sha256_prefixed_digest(entry)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(canonical_json(entry) + "\n")
        return entry


__all__ = ["SANDBOX_EVIDENCE_PATH", "SandboxEvidenceLedger", "build_sandbox_evidence"]
