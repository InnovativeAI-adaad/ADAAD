import json
import shutil
import time
from pathlib import Path

from security.contracts import validate_agent_contract
from security.cryovant import secure_write


class DreamMode:
    def __init__(self, base: Path, cryo):
        self.base = Path(base)
        self.cryo = cryo
        self._enabled = False
        self.candidates_root = self.base / "app/agents/candidates"
        self.lineage_root = self.base / "app/agents/lineage"

    def enable(self):
        self._enabled = True

    def disable(self):
        self._enabled = False

    def shutdown(self):
        self._enabled = False

    def discover_tasks(self):
        if not self.candidates_root.exists():
            return []
        return [p for p in self.candidates_root.glob("*") if p.is_dir()]

    def _emit_metric(self, payload: dict):
        if hasattr(self.cryo, "emit_metric"):
            self.cryo.emit_metric(payload)

    def _record_failure(self, agent_dir: Path, *, reason: str, details: dict | None = None):
        payload = {
            "event_type": "MUTANT_FAIL",
            "agent_dir": str(agent_dir),
            "reason": reason,
        }
        if details:
            payload.update(details)
        self._emit_metric(payload)

    def _write_agent_to_lineage(self, agent_dir: Path, lineage_hash: str):
        target_dir = self.lineage_root / agent_dir.name
        for path in agent_dir.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(agent_dir)
            dest = target_dir / relative
            secure_write(self.cryo, dest, path.read_bytes())
        self.cryo.record_lineage(agent_dir.name, lineage_hash, target_dir)
        self._emit_metric(
            {
                "event_type": "MUTANT_SUCCESS",
                "agent_id": agent_dir.name,
                "lineage_hash": lineage_hash,
                "target": str(target_dir),
            }
        )

    def _finalize_candidate(self, agent_dir: Path):
        certificate_path = agent_dir / "certificate.json"
        if not certificate_path.exists():
            self._record_failure(agent_dir, reason="certificate_missing")
            return

        try:
            cert = json.loads(certificate_path.read_text(encoding="utf-8"))
        except Exception as exc:
            self._record_failure(agent_dir, reason="certificate_unreadable", details={"error": str(exc)})
            return

        lineage_hash = self.cryo.compute_lineage_hash(agent_dir)
        cert["lineage_hash"] = lineage_hash

        try:
            secure_write(self.cryo, certificate_path, json.dumps(cert, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        except Exception as exc:
            self._record_failure(agent_dir, reason="certificate_write_denied", details={"error": str(exc)})
            return

        valid, reasons = validate_agent_contract(agent_dir)
        if not valid:
            self._record_failure(agent_dir, reason="AGENT_CONTRACT_FAIL", details={"reasons": reasons})
            return

        try:
            self._write_agent_to_lineage(agent_dir, lineage_hash)
        except Exception as exc:
            self._record_failure(agent_dir, reason="lineage_write_failed", details={"error": str(exc)})
            return

        try:
            shutil.rmtree(agent_dir)
        except Exception:
            # Non-fatal cleanup failure.
            pass

    def background_housekeeping(self):
        while self._enabled:
            for candidate in self.discover_tasks():
                try:
                    self._finalize_candidate(candidate)
                except Exception as exc:
                    self._record_failure(candidate, reason="mutation_exception", details={"error": str(exc)})
            time.sleep(5)
