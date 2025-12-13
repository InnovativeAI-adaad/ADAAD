from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable, Iterable, Optional

from security.policy import evaluate as policy_eval


def secure_write(cryo, path: Path, data: bytes):
    ctx = {"cert_ok": getattr(cryo, "cert_ok", False)}
    decision = policy_eval({"type": "write", "path": str(path)}, subject="cryovant", resource=str(path), context=ctx)
    if not decision["allow"]:
        raise PermissionError(f"Policy denied: {decision}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def secure_append_jsonl(cryo, path: Path, payload: dict):
    ctx = {"cert_ok": getattr(cryo, "cert_ok", False)}
    decision = policy_eval({"type": "write", "path": str(path)}, subject="cryovant", resource=str(path), context=ctx)
    if not decision["allow"]:
        raise PermissionError(f"Policy denied: {decision}")
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)


class Cryovant:
    def __init__(
        self,
        ledger_dir: Path,
        keys_dir: Path,
        metrics_sink: Optional[Callable[[dict], None]] = None,
    ):
        self.ledger_dir = Path(ledger_dir)
        self.keys_dir = Path(keys_dir)
        self.events_path = self.ledger_dir / "events.jsonl"
        self.cert_ok = True
        self._metrics_sink = metrics_sink
        self.ledger_dir.mkdir(parents=True, exist_ok=True)
        self.keys_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.keys_dir, 0o700)
        except Exception as exc:  # pragma: no cover - platform guard
            # fail closed at orchestrator level by surfacing error event
            self.append_event({"event_type": "KEYS_CHMOD_FAIL", "error": str(exc)})
        self.touch_ledger()

    def state(self) -> dict:
        return {"cert_ok": self.cert_ok, "ledger": str(self.ledger_dir)}

    def touch_ledger(self):
        self.ledger_dir.mkdir(parents=True, exist_ok=True)
        self.keys_dir.mkdir(parents=True, exist_ok=True)
        if not self.events_path.exists():
            secure_write(self, self.events_path, b"")

    def append_event(self, payload: dict):
        self.touch_ledger()
        secure_append_jsonl(self, self.events_path, payload)
        return payload

    def gate_cycle(self, agent_dirs: Iterable[Path]):
        self.touch_ledger()
        cert_ok = all(Path(p).exists() for p in agent_dirs) if agent_dirs else True
        self.cert_ok = bool(cert_ok)
        if not self.cert_ok:
            evt = {"event_type": "AGENT_CERT_FAIL", "reason": "missing_agent_dirs", "count": len(list(agent_dirs))}
            self.append_event(evt)
            if self._metrics_sink:
                try:
                    self._metrics_sink(evt)
                except Exception:
                    pass
        return self.cert_ok
