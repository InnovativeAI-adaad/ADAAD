# SPDX-License-Identifier: Apache-2.0
"""
Module: migration
Purpose: Migrate deterministic JSON state stores to SQLite with idempotent reporting.
Author: ADAAD / InnovativeAI-adaad
Integration points:
  - Imports from: runtime.state.{registry_store,ledger_store}
  - Consumed by: operators/tests validating state backend parity
  - Governance impact: medium — enables policy-controlled backend transition without changing behavior
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from runtime.state.ledger_store import ScoringLedgerStore
from runtime.state.registry_store import CryovantRegistryStore


def migrate_registry_json_to_sqlite(json_path: Path, sqlite_path: Path) -> dict[str, Any]:
    source = CryovantRegistryStore(json_path=json_path, backend="json")
    target = CryovantRegistryStore(json_path=json_path, sqlite_path=sqlite_path, backend="sqlite")
    source_registry = source.load_registry()
    target_registry = target.load_registry()
    if source_registry == target_registry:
        return {"store": "registry", "idempotent": True, "migrated_records": 0, "total_records": len(target_registry)}
    target.save_registry(source_registry)
    return {
        "store": "registry",
        "idempotent": False,
        "migrated_records": max(0, len(source_registry) - len(target_registry)),
        "total_records": len(source_registry),
    }


def migrate_ledger_json_to_sqlite(json_path: Path, sqlite_path: Path) -> dict[str, Any]:
    """Migrate JSON ledger to SQLite.

    This migration path is the only allowed truncation path for SQLite ledger reseeding.
    The table clear below is intentional and scoped to migration operations only.
    """

    source = ScoringLedgerStore(path=json_path, backend="json")
    target = ScoringLedgerStore(path=json_path, sqlite_path=sqlite_path, backend="sqlite")
    source_records = list(source.iter_records())
    target_records = list(target.iter_records())

    source_canonical = [json.dumps(record, sort_keys=True, ensure_ascii=False) for record in source_records]
    target_canonical = [json.dumps(record, sort_keys=True, ensure_ascii=False) for record in target_records]
    if source_canonical == target_canonical:
        return {"store": "ledger", "idempotent": True, "migrated_records": 0, "total_records": len(target_records)}

    # Migration-only reseed: intentional truncation prior to deterministic replay of source records.
    with sqlite3.connect(target.sqlite_path) as conn:
        conn.execute("DELETE FROM scoring_ledger")

    for record in source_records:
        target.append(dict(record.get("scoring_result") or {}))

    return {
        "store": "ledger",
        "idempotent": False,
        "migrated_records": max(0, len(source_records) - len(target_records)),
        "total_records": len(source_records),
    }


def migrate_json_state_to_sqlite(
    *,
    registry_json_path: Path,
    registry_sqlite_path: Path,
    ledger_json_path: Path,
    ledger_sqlite_path: Path,
) -> dict[str, Any]:
    registry_report = migrate_registry_json_to_sqlite(registry_json_path, registry_sqlite_path)
    ledger_report = migrate_ledger_json_to_sqlite(ledger_json_path, ledger_sqlite_path)
    idempotent = bool(registry_report["idempotent"] and ledger_report["idempotent"])
    return {
        "idempotent": idempotent,
        "registry": registry_report,
        "ledger": ledger_report,
    }
