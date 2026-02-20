# SPDX-License-Identifier: Apache-2.0

from runtime.state.ledger_store import ScoringLedgerStore
from runtime.state.migration import migrate_json_state_to_sqlite
from runtime.state.registry_store import CryovantRegistryStore


def test_state_migration_and_idempotency_report(tmp_path) -> None:
    registry_json = tmp_path / "capabilities.json"
    registry_sqlite = tmp_path / "capabilities.sqlite"
    ledger_json = tmp_path / "scoring.jsonl"
    ledger_sqlite = tmp_path / "scoring.sqlite"

    registry_store = CryovantRegistryStore(registry_json, backend="json")
    registry_store.save_registry({"capability-a": {"score": 1.0, "owner": "Earth"}})

    ledger_store = ScoringLedgerStore(path=ledger_json, backend="json")
    ledger_store.append({"mutation": "m1", "score": 0.9})

    first_report = migrate_json_state_to_sqlite(
        registry_json_path=registry_json,
        registry_sqlite_path=registry_sqlite,
        ledger_json_path=ledger_json,
        ledger_sqlite_path=ledger_sqlite,
    )
    second_report = migrate_json_state_to_sqlite(
        registry_json_path=registry_json,
        registry_sqlite_path=registry_sqlite,
        ledger_json_path=ledger_json,
        ledger_sqlite_path=ledger_sqlite,
    )

    assert first_report["idempotent"] is False
    assert second_report["idempotent"] is True
    assert second_report["registry"]["migrated_records"] == 0
    assert second_report["ledger"]["migrated_records"] == 0
