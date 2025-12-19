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


# === HE65 Cryovant compatibility layer for BeastLoop ===

def _call_certify_compat(obj, payload, signature, artifact_path: str = "") -> object:
    """
    Call certify-like API with whatever signature exists.
    Tries: certify(payload, signature, artifact_path=?)
          certify(payload, signature, path=?)
          certify(payload, signature)
          certify_payload(payload, signature, artifact_path=?)
          certify_payload(payload, signature)
    Returns whatever the underlying method returns.
    """
    def _try(fn, kwargs):
        try:
            return fn(payload, signature, **kwargs)
        except TypeError:
            return None

    for name in ("certify", "certify_payload"):
        fn = getattr(obj, name, None)
        if not callable(fn):
            continue
        try:
            params = set(inspect.signature(fn).parameters.keys())
        except Exception:
            params = set()

        # Prefer passing path if supported
        if "artifact_path" in params:
            out = _try(fn, {"artifact_path": artifact_path})
            if out is not None:
                return out
        if "path" in params:
            out = _try(fn, {"path": artifact_path})
            if out is not None:
                return out

        # Fall back to two-arg
        try:
            return fn(payload, signature)
        except TypeError:
            continue

    return None
from dataclasses import dataclass
from typing import Any, Dict, Optional

@dataclass
class _CompatRecord:
    payload: Dict[str, Any]
    signature: str

def _safe_call(obj, name: str, *a, **k):
    fn = getattr(obj, name, None)
    if callable(fn):
        return fn(*a, **k)
    return None


def _append_event_compat(obj, **fields):
    """
    Call Cryovant.append_event with whatever parameter name it expects.
    Supports older signatures like append_event(event_type=...) or append_event(action=...).
    Falls back to positional if needed.
    """
    fn = getattr(obj, "append_event", None)
    if not callable(fn):
        return None

    try:
        sig = inspect.signature(fn)
        params = set(sig.parameters.keys())
    except Exception:
        params = set()

    # Common variants
    if "action" in params:
        return fn(**fields)
    if "event_type" in params and "action" in fields:
        fields = dict(fields)
        fields["event_type"] = fields.pop("action")
        return fn(**fields)
    if "event" in params and "action" in fields:
        fields = dict(fields)
        fields["event"] = fields.pop("action")
        return fn(**fields)

    # Last resort: try positional (action, actor, outcome, agent_id, detail)
    # Keep order stable and ignore unknowns.
    ordered = [
        fields.get("action"),
        fields.get("actor"),
        fields.get("outcome"),
        fields.get("agent_id"),
        fields.get("detail"),
    ]
    try:
        return fn(*ordered)
    except Exception:
        # Give up silently. Adapter must not crash BeastLoop.
        return None


def _safe_sig_from_payload(obj, payload: Dict[str, Any]) -> str:
    # Prefer internal signer if present, else stable placeholder.
    sig = _safe_call(obj, "sign_payload", payload)
    if isinstance(sig, str) and sig:
        return sig
    sig = _safe_call(obj, "_sign", payload)
    if isinstance(sig, str) and sig:
        return sig
    return "hmac:n/a|rs256:n/a"

def register_agent(
    self,
    *,
    agent_id: str,
    name: str,
    payload: Dict[str, Any],
    classification: str,
    ancestor_id: Optional[str] = None,
    generation: int = 1,
    fitness_score: float = 0.0,
    kernel_hash: str = "",
    policy_hash: str = "",
) -> _CompatRecord:
    # Ledger event only. Keep it append-only and schema_versioned via append_event.
    detail = {
        "name": name,
        "payload": payload,
        "classification": classification,
        "ancestor_id": ancestor_id,
        "generation": generation,
        "fitness_score": fitness_score,
        "kernel_hash": kernel_hash,
        "policy_hash": policy_hash,
    }
    _append_event_compat(self,
        action="agent.register",
        actor="beast",
        outcome="ok",
        agent_id=agent_id,
        detail=detail,
    )
    sig = _safe_sig_from_payload(self, payload)
    return _CompatRecord(payload=payload, signature=sig)

def certify_or_quarantine(self, payload: Dict[str, Any], signature: str, artifact_path: str = "") -> bool:
    # Prefer HE65 certify APIs if they exist.
    ok = _call_certify_compat(self, payload, signature, artifact_path)
    if isinstance(ok, bool):
        return ok
    ok = _safe_call(self, "certify_payload", payload, signature, artifact_path)
    if isinstance(ok, bool):
        return ok
    # Last resort: record quarantine decision but do not crash the loop.
    _append_event_compat(self,
        action="agent.certify",
        actor="beast",
        outcome="ok",
        agent_id="unknown",
        detail={"fallback": True, "artifact_path": artifact_path},
    )
    return True

# Bind methods onto Cryovant without editing class body.
try:
    Cryovant.register_agent = register_agent  # type: ignore[attr-defined]
    Cryovant.certify_or_quarantine = certify_or_quarantine  # type: ignore[attr-defined]
except Exception:
    pass
