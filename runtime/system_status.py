# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

GATE_PROTOCOL = "adaad-gate/1.0"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GATE_LOCK_FILE = REPO_ROOT / "security" / "ledger" / "gate.lock"
DEFAULT_VERSION_PATH = REPO_ROOT / "VERSION"
DEFAULT_REPORT_VERSION_PATH = REPO_ROOT / "governance" / "report_version.json"


def _truthy_env(value: str) -> bool:
    return value.lower() not in {"", "0", "false", "no"}


def read_gate_state(
    *,
    gate_lock_file: Path = DEFAULT_GATE_LOCK_FILE,
    protocol: str = GATE_PROTOCOL,
    environ: Mapping[str, str] | None = None,
    now_provider: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Return gate snapshot. Never raises and never surfaces secrets."""
    scope = environ if environ is not None else {}
    if environ is None:
        import os

        scope = os.environ

    locked = False
    reason: str | None = None
    source = "default"

    env_flag = scope.get("ADAAD_GATE_LOCKED")
    if env_flag:
        locked = _truthy_env(env_flag)
        source = "env"
        reason = scope.get("ADAAD_GATE_REASON") or reason

    if gate_lock_file.exists():
        source = "file"
        locked = True
        try:
            contents = gate_lock_file.read_text(encoding="utf-8").strip()
            if contents:
                reason = contents
        except OSError:
            # Reading the lock file is best-effort: if we cannot read a reason,
            # keep the gate locked but omit the reason rather than raising.
            pass

    if reason:
        reason = reason[:280]

    now = now_provider() if now_provider is not None else datetime.now(timezone.utc)
    return {
        "locked": locked,
        "reason": reason,
        "source": source,
        "checked_at": now.isoformat(),
        "protocol": protocol,
    }


def _load_constitution_version() -> str:
    try:
        from runtime.constitution import CONSTITUTION_VERSION

        return CONSTITUTION_VERSION
    except Exception:  # pragma: no cover
        return "unknown"


def load_live_version(
    *,
    version_path: Path = DEFAULT_VERSION_PATH,
    report_version_path: Path = DEFAULT_REPORT_VERSION_PATH,
    constitution_version_provider: Callable[[], str] = _load_constitution_version,
    protocol: str = GATE_PROTOCOL,
    now_provider: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Read live version snapshot with degraded fallbacks."""
    adaad_version = "unknown"
    try:
        adaad_version = version_path.read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        # Best-effort read: fall back to default "unknown" if version file is missing or unreadable.
        pass

    report: dict[str, Any] = {}
    try:
        loaded = json.loads(report_version_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            report = loaded
    except (OSError, json.JSONDecodeError):
        # Best-effort read: if the report file is missing or invalid, fall back to defaults.
        pass

    constitution_version = constitution_version_provider()
    now = now_provider() if now_provider is not None else datetime.now(timezone.utc)
    return {
        "adaad_version": adaad_version,
        "constitution_version": constitution_version,
        "last_sync_sha": report.get("last_sync_sha", "unknown"),
        "last_sync_date": report.get("last_sync_date", "unknown"),
        "report_version": report.get("report_version", adaad_version),
        "protocol": protocol,
        "checked_at": now.isoformat(),
    }
