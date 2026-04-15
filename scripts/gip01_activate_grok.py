#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Governed activation flow for Grok integrator runtime profile state."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime.preflight import _validate_against_schema, migrate_runtime_profile_lock
from security.ledger import journal

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PROFILE_PATH = REPO_ROOT / "governance_runtime_profile.lock.json"
RUNTIME_PROFILE_SCHEMA_PATH = REPO_ROOT / "schemas" / "governance_runtime_profile.lock.v1.json"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_profile(profile: dict[str, Any]) -> list[str]:
    schema = _read_json(RUNTIME_PROFILE_SCHEMA_PATH)
    return _validate_against_schema(schema, profile)


def _update_grok_state(*, enabled: bool, vault_file: Path, operator_id: str, confirmed: bool) -> dict[str, Any]:
    profile = _read_json(RUNTIME_PROFILE_PATH)
    migrated = migrate_runtime_profile_lock(profile)
    updated_profile = migrated["profile"]

    agents = dict(updated_profile.get("agents") or {})
    grok = dict(agents.get("grok-integrator") or {})
    metadata = dict(grok.get("metadata") or {})

    metadata["vault_file"] = str(vault_file)
    metadata["operator_id"] = operator_id
    metadata["operator_confirmed"] = bool(confirmed)
    metadata["activation_updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    grok.update(
        {
            "enabled": enabled,
            "provider": str(grok.get("provider") or "xai"),
            "profile": str(grok.get("profile") or "governance-observer"),
            "metadata": metadata,
        }
    )
    agents["grok-integrator"] = grok
    updated_profile["agents"] = agents

    schema_errors = _validate_profile(updated_profile)
    if schema_errors:
        raise ValueError(f"runtime_profile_schema_invalid:{';'.join(schema_errors)}")

    RUNTIME_PROFILE_PATH.write_text(json.dumps(updated_profile, indent=2) + "\n", encoding="utf-8")
    return updated_profile


def _emit_activation_event(*, enabled: bool, vault_file: Path, operator_id: str, confirmed: bool) -> None:
    journal.append_tx(
        tx_type="grok_activation_status.v1",
        payload={
            "status": "enabled" if enabled else "disabled",
            "enabled": enabled,
            "vault_file": str(vault_file),
            "vault_present": vault_file.exists(),
            "operator_id": operator_id,
            "operator_confirmed": confirmed,
            "runtime_profile": str(RUNTIME_PROFILE_PATH),
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Activate or deactivate Grok runtime profile state.")
    parser.add_argument("--vault-file", default="security/ledger/credentials/grok_pat.vault")
    parser.add_argument("--operator-id", required=True)
    parser.add_argument("--enable", action="store_true")
    parser.add_argument("--disable", action="store_true")
    parser.add_argument("--confirm-enable", action="store_true")
    args = parser.parse_args()

    if args.enable == args.disable:
        raise SystemExit("exactly_one_of_enable_disable_required")

    if args.enable and not args.confirm_enable:
        raise SystemExit("operator_confirmation_required:pass --confirm-enable")

    vault_path = Path(args.vault_file)
    if not vault_path.is_absolute():
        vault_path = REPO_ROOT / vault_path

    if args.enable and not vault_path.exists():
        raise SystemExit(f"vault_missing:{vault_path}")

    _update_grok_state(
        enabled=args.enable,
        vault_file=vault_path.relative_to(REPO_ROOT) if vault_path.is_relative_to(REPO_ROOT) else vault_path,
        operator_id=args.operator_id.strip(),
        confirmed=args.confirm_enable,
    )
    _emit_activation_event(
        enabled=args.enable,
        vault_file=vault_path,
        operator_id=args.operator_id.strip(),
        confirmed=args.confirm_enable,
    )

    print(
        "gip01_activate_grok_state_success"
        f" enabled={str(args.enable).lower()}"
        f" vault_file={vault_path}"
        f" operator_id={args.operator_id.strip()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
