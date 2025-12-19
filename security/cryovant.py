from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from security.schema_versions import LEDGER_SCHEMA_VERSION, LINEAGE_SCHEMA_VERSION

LEDGER_PATH = Path("security/ledger/events.jsonl")
LEDGER_DIR = LEDGER_PATH.parent
KEYS_DIR = Path("security/keys")
REQUIRED_AGENT_FILES = ("meta.json", "dna.json", "certificate.json")


class CryovantError(Exception):
    """Raised when Cryovant gatekeeping fails."""


class Cryovant:
    def __init__(self, ledger_path: Path | None = None, keys_dir: Path | None = None) -> None:
        self.ledger_path = Path(ledger_path) if ledger_path else LEDGER_PATH
        self.keys_dir = Path(keys_dir) if keys_dir else KEYS_DIR

        if self.ledger_path != LEDGER_PATH:
            raise CryovantError("Ledger path must remain security/ledger/events.jsonl")
        if self.keys_dir != KEYS_DIR:
            raise CryovantError("Keys directory must remain security/keys")

        self._prepare_filesystem()

    def _prepare_filesystem(self) -> None:
        if LEDGER_DIR.exists() and not LEDGER_DIR.is_dir():
            raise CryovantError("Ledger path must be a directory")
        if LEDGER_DIR.is_symlink():
            raise CryovantError("Ledger directory cannot be a symlink")
        if self.keys_dir.exists() and not self.keys_dir.is_dir():
            raise CryovantError("Keys path must be a directory")
        if self.keys_dir.is_symlink():
            raise CryovantError("Keys directory cannot be a symlink")

        LEDGER_DIR.mkdir(parents=True, exist_ok=True)
        self.keys_dir.mkdir(parents=True, exist_ok=True)
        if not self.ledger_path.exists():
            self.ledger_path.touch()
        (LEDGER_DIR / ".keep").touch(exist_ok=True)
        keep = self.keys_dir / ".keep"
        keep.touch(exist_ok=True)
        try:
            self.keys_dir.chmod(0o700)
        except PermissionError:
            # Android shells may ignore chmod; continue best-effort.
            pass

    def touch_ledger(self) -> Path:
        return self.ledger_path

    def _ensure_writable(self) -> None:
        try:
            with self.ledger_path.open("a", encoding="utf-8"):
                return
        except OSError as exc:  # pragma: no cover - filesystem safeguard
            raise CryovantError(f"Ledger not writable: {exc}") from exc

    def _append_event(self, record: Dict[str, Any]) -> Path:
        payload = {"ts": datetime.now(timezone.utc).isoformat(), **record}
        with self.ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return self.ledger_path

    def append_event(self, record: Dict[str, Any]) -> Path:
        record.setdefault("detail", {})
        self._validate_record(record)
        self._ensure_writable()
        return self._append_event(record)

    def _validate_record(self, record: Dict[str, Any]) -> None:
        schema_version = record.get("schema_version", LEDGER_SCHEMA_VERSION)
        if schema_version != LEDGER_SCHEMA_VERSION:
            raise CryovantError(f"Ledger schema_version must be {LEDGER_SCHEMA_VERSION}")
        record["schema_version"] = schema_version
        required = {"action", "actor", "outcome"}
        missing = [k for k in required if k not in record]
        if missing:
            raise CryovantError(f"Ledger record missing required fields: {missing}")
        action = record.get("action")
        if action in {"certify", "promotion", "gate_cycle"}:
            agent_fields = ["agent_id", "lineage_hash", "signature_id"]
            agent_missing = [k for k in agent_fields if not record.get(k)]
            if agent_missing:
                raise CryovantError(f"Ledger record missing agent fields: {agent_missing}")
        detail = record.get("detail", {})
        if not isinstance(detail, dict):
            raise CryovantError("Ledger detail must be a dict")

    def _missing_agent_files(self, agent_dir: Path) -> List[str]:
        missing: List[str] = []
        for required in REQUIRED_AGENT_FILES:
            if not (agent_dir / required).exists():
                missing.append(required)
        return missing

    def _schema_violations(self, agent_dir: Path) -> List[str]:
        violations: List[str] = []
        for filename in REQUIRED_AGENT_FILES:
            path = agent_dir / filename
            if not path.exists():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                violations.append(f"{filename}:invalid_json")
                continue
            version = payload.get("schema_version")
            if version != LINEAGE_SCHEMA_VERSION:
                violations.append(f"{filename}:schema_version:{version or 'missing'}")
        return violations

    def _canonical_lineage_payload(self, path: Path) -> bytes:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            raise CryovantError(f"Invalid JSON in {path}: {exc}") from exc
        version = payload.get("schema_version")
        if version != LINEAGE_SCHEMA_VERSION:
            raise CryovantError(f"{path} schema_version must be {LINEAGE_SCHEMA_VERSION}, found {version}")
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def _gate_rejection_event(self, agent_id: str, reason: str, detail: Dict[str, Any]) -> Dict[str, Any]:
        payload = {"reason": reason, **detail}
        rejection_seed = json.dumps({"agent_id": agent_id, "reason": reason, "detail": payload}, sort_keys=True)
        rejection_hash = hashlib.sha256(rejection_seed.encode("utf-8")).hexdigest()
        return {
            "action": "gate_cycle",
            "actor": "cryovant",
            "outcome": "rejected",
            "agent_id": agent_id,
            "lineage_hash": rejection_hash,
            "signature_id": f"{agent_id}-{rejection_hash[:12]}",
            "schema_version": LEDGER_SCHEMA_VERSION,
            "detail": payload,
        }

    def _lineage_hash(self, agent_dir: Path) -> str:
        digest = hashlib.sha256()
        for filename in REQUIRED_AGENT_FILES:
            path = agent_dir / filename
            digest.update(filename.encode("utf-8"))
            try:
                digest.update(self._canonical_lineage_payload(path))
            except OSError as exc:  # pragma: no cover - filesystem safeguard
                raise CryovantError(f"Cannot read {path}: {exc}") from exc
        return digest.hexdigest()

    def gate_cycle(self, agent_roots: Iterable[Path]) -> None:
        self._ensure_writable()
        agent_list = list(agent_roots)
        missing: Dict[str, List[str]] = {}
        schema_violations: Dict[str, List[str]] = {}
        events: List[Dict[str, Any]] = []

        if not agent_list:
            events.append(self._gate_rejection_event("no_active_agents", "no_active_agents", {}))
            for event in events:
                self.append_event(event)
            raise CryovantError("No active agents present")

        for agent_root in agent_list:
            if not agent_root.exists():
                missing[agent_root.name] = list(REQUIRED_AGENT_FILES)
                continue

            missing_files = self._missing_agent_files(agent_root)
            if missing_files:
                missing[agent_root.name] = missing_files
                continue

            violations = self._schema_violations(agent_root)
            if violations:
                schema_violations[agent_root.name] = violations

        if missing or schema_violations:
            for agent_root in agent_list:
                agent_id = agent_root.name
                missing_files = missing.get(agent_id, [])
                violations = schema_violations.get(agent_id, [])
                if not missing_files and not violations:
                    continue
                events.append(
                    self._gate_rejection_event(
                        agent_id,
                        "metadata_invalid",
                        {"missing": missing_files, "schema_violations": violations, "path": str(agent_root)},
                    )
                )
            for event in events:
                self.append_event(event)
            raise CryovantError(f"Agent metadata missing or invalid: {missing or schema_violations}")

        for agent_root in agent_list:
            lineage_hash = self._lineage_hash(agent_root)
            events.append(
                {
                    "action": "gate_cycle",
                    "actor": "cryovant",
                    "outcome": "accepted",
                    "agent_id": agent_root.name,
                    "lineage_hash": lineage_hash,
                    "signature_id": f"{agent_root.name}-{lineage_hash}",
                    "schema_version": LEDGER_SCHEMA_VERSION,
                    "detail": {"path": str(agent_root)},
                }
            )

        for event in events:
            self.append_event(event)

    def certify(self, agent_id: str, lineage_hash: str, outcome: str, actor: str = "cryovant") -> Path:
        return self.append_event(
            {
                "action": "certify",
                "actor": actor,
                "outcome": outcome,
                "agent_id": agent_id,
                "lineage_hash": lineage_hash,
                "signature_id": f"{agent_id}-{lineage_hash}",
                "schema_version": LEDGER_SCHEMA_VERSION,
            }
        )

    def promotion(
        self,
        ticket_id: str,
        deliverable: str,
        agent_id: str,
        lineage_hash: str,
        outcome: str,
        actor: str = "gatekeeper",
        detail: Dict[str, Any] | None = None,
    ) -> Path:
        base_detail = {"ticket_id": ticket_id, "deliverable": deliverable}
        if detail:
            base_detail.update(detail)
        return self.append_event(
            {
                "action": "promotion",
                "actor": actor,
                "outcome": outcome,
                "agent_id": agent_id,
                "lineage_hash": lineage_hash,
                "signature_id": f"{ticket_id}-{agent_id}-{lineage_hash}",
                "schema_version": LEDGER_SCHEMA_VERSION,
                "detail": base_detail,
            }
        )

    def ledger_probe(self, actor: str = "system") -> Path:
        return self.append_event(
            {
                "action": "ledger_probe",
                "actor": actor,
                "outcome": "ok",
                "schema_version": LEDGER_SCHEMA_VERSION,
                "detail": {"path": str(self.ledger_path)},
            }
        )

    def record_gate_rejection(self, agent_id: str, reason: str, detail: Dict[str, Any] | None = None) -> Path:
        return self.append_event(self._gate_rejection_event(agent_id, reason, detail or {}))


__all__ = [
    "Cryovant",
    "CryovantError",
    "LEDGER_PATH",
    "LEDGER_DIR",
    "KEYS_DIR",
    "REQUIRED_AGENT_FILES",
    "LEDGER_SCHEMA_VERSION",
    "LINEAGE_SCHEMA_VERSION",
]
