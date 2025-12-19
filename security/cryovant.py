from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

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

    def _lineage_hash(self, agent_dir: Path) -> str:
        digest = hashlib.sha256()
        for filename in REQUIRED_AGENT_FILES:
            path = agent_dir / filename
            try:
                digest.update(path.read_bytes())
            except OSError as exc:  # pragma: no cover - filesystem safeguard
                raise CryovantError(f"Cannot read {path}: {exc}") from exc
        return digest.hexdigest()

    def gate_cycle(self, agent_roots: Iterable[Path]) -> None:
        self._ensure_writable()
        agent_list = list(agent_roots)
        missing: Dict[str, List[str]] = {}
        events: List[Dict[str, Any]] = []

        for agent_root in agent_list:
            if not agent_root.exists():
                missing[agent_root.name] = list(REQUIRED_AGENT_FILES)
                continue

            missing_files = self._missing_agent_files(agent_root)
            if missing_files:
                missing[agent_root.name] = missing_files

        if missing:
            for agent_root in agent_list:
                agent_id = agent_root.name
                missing_files = missing.get(agent_id, [])
                if not missing_files:
                    continue
                miss_str = ",".join(sorted(missing_files))
                rejection_hash = hashlib.sha256(f"{agent_id}|missing:{miss_str}".encode("utf-8")).hexdigest()
                events.append(
                    {
                        "action": "gate_cycle",
                        "actor": "cryovant",
                        "outcome": "rejected",
                        "agent_id": agent_id,
                        "lineage_hash": rejection_hash,
                        "signature_id": f"{agent_id}-{rejection_hash[:12]}",
                        "detail": {
                            "missing": missing_files,
                            "path": str(agent_root),
                        },
                    }
                )
            for event in events:
                self.append_event(event)
            raise CryovantError(f"Agent metadata missing or invalid: {missing}")

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
            }
        )

    def promotion(
        self, ticket_id: str, deliverable: str, agent_id: str, lineage_hash: str, outcome: str, actor: str = "gatekeeper"
    ) -> Path:
        return self.append_event(
            {
                "action": "promotion",
                "actor": actor,
                "outcome": outcome,
                "agent_id": agent_id,
                "lineage_hash": lineage_hash,
                "signature_id": f"{ticket_id}-{agent_id}-{lineage_hash}",
                "detail": {"ticket_id": ticket_id, "deliverable": deliverable},
            }
        )


__all__ = ["Cryovant", "CryovantError", "LEDGER_PATH", "LEDGER_DIR", "KEYS_DIR", "REQUIRED_AGENT_FILES"]
