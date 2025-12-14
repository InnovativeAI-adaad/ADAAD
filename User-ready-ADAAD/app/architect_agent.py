from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Iterable, Tuple

from security.cryovant import secure_write


SAFE_PREFIXES = (
    "app/",
    "runtime/",
    "ui/",
    "reports/",
    "security/ledger/",
)


FORBIDDEN_PREFIXES = (
    "security/keys/",
)


class ArchitectAgent:
    def __init__(self, base: Path):
        self.base = Path(base)
        self.proposals_dir = self.base / "reports/proposals"
        self.archive_dir = self.base / "reports/archive"
        self._enabled = False

    def enable(self):
        self._enabled = True

    def disable(self):
        self._enabled = False

    def quick_scan(self) -> dict:
        return {
            "status": "ok",
            "agents_root": str(self.base / "app/agents"),
        }

    def engine_state_audit(self, engines: dict, *, cert_ok: bool, health_ok: bool) -> dict:
        """
        WOOD audit.
        Reports the active engine registry and hard-gate state before main loop.
        """
        engine_names = sorted(list(engines.keys()))
        missing = [name for name in ("architect", "dream", "beast") if name not in engines]
        audit_ok = (not missing) and bool(health_ok is True)

        # Contract hints only. Do not mutate. Do not write files here.
        compliance = {
            "has_required_engines": (len(missing) == 0),
            "missing_engines": missing,
            "cert_ok": bool(cert_ok),
            "health_ok": bool(health_ok),
        }

        return {
            "status": "ok" if audit_ok else "warn",
            "engine_registry": engine_names,
            "compliance": compliance,
        }

    def _emit_metric(self, cryo, payload: dict):
        if cryo and hasattr(cryo, "emit_metric"):
            cryo.emit_metric(payload)

    def _archive_proposal(self, proposal_path: Path):
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path = self.archive_dir / proposal_path.name
        secure_write(None, archive_path, proposal_path.read_bytes())
        try:
            proposal_path.unlink()
        except Exception:
            pass

    def _collect_paths_from_diff(self, diff_text: str) -> Tuple[bool, list[str], str | None]:
        paths: list[str] = []
        for line in diff_text.splitlines():
            if line.startswith("+++") or line.startswith("---"):
                path = line[4:].strip()
                if path in {"/dev/null", "a/dev/null", "b/dev/null"}:
                    continue
                if path.startswith("a/") or path.startswith("b/"):
                    path = path[2:]
                normalized = path.lstrip("./")
                if any(normalized.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
                    return False, [], f"forbidden_path:{normalized}"
                if not any(normalized.startswith(prefix) for prefix in SAFE_PREFIXES):
                    return False, [], f"unsafe_path:{normalized}"
                paths.append(normalized)
        return True, paths, None

    def execute_proposal(self, proposal: dict, *, cryo) -> dict:
        diff_text = proposal.get("unified_diff")
        schema = proposal.get("schema") or proposal.get("$schema")
        if not diff_text or not isinstance(diff_text, str):
            return {"status": "failed", "reason": "missing_diff"}
        if schema and schema != "he65.blueprint_proposal.v1":
            return {"status": "failed", "reason": "schema_mismatch"}

        safe, paths, reason = self._collect_paths_from_diff(diff_text)
        if not safe:
            return {"status": "failed", "reason": reason or "unsafe_diff"}

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_base = Path(tmpdir) / "repo"
            shutil.copytree(self.base, tmp_base)
            proc = subprocess.run(
                ["patch", "-p0", "-d", str(tmp_base)],
                input=diff_text,
                text=True,
                capture_output=True,
            )
            if proc.returncode != 0:
                return {
                    "status": "failed",
                    "reason": "patch_failed",
                    "stderr": proc.stderr.strip(),
                }

            for rel_path in paths:
                target_path = self.base / rel_path
                patched_file = tmp_base / rel_path
                if not patched_file.exists():
                    continue
                try:
                    secure_write(cryo, target_path, patched_file.read_bytes())
                except Exception as exc:
                    return {"status": "failed", "reason": "secure_write_denied", "error": str(exc)}

        return {"status": "applied", "paths": paths}

    def _handle_proposal_file(self, proposal_path: Path, cryo):
        try:
            data = json.loads(proposal_path.read_text(encoding="utf-8"))
        except Exception as exc:
            self._emit_metric(cryo, {"event_type": "PROPOSAL_FAIL", "path": str(proposal_path), "reason": "invalid_json", "error": str(exc)})
            self._archive_proposal(proposal_path)
            return

        result = self.execute_proposal(data, cryo=cryo)
        payload = {
            "event_type": "PROPOSAL_RESULT",
            "path": str(proposal_path),
            "status": result.get("status"),
            "reason": result.get("reason"),
        }
        self._emit_metric(cryo, payload)

        if result.get("status") == "applied":
            self._archive_proposal(proposal_path)

    def process_pending_proposals(self, cryo):
        while self._enabled:
            if self.proposals_dir.exists():
                for proposal_path in self.proposals_dir.glob("*.json"):
                    self._handle_proposal_file(proposal_path, cryo)
            time.sleep(5)
