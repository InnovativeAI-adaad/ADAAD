# SPDX-License-Identifier: Apache-2.0

from runtime.state.ledger_store import ScoringLedgerStore


def test_ledger_store_append_and_verify_json(tmp_path) -> None:
    ledger = ScoringLedgerStore(path=tmp_path / "scoring.jsonl", backend="json")
    ledger.append({"mutation": "a", "score": 0.9})
    ledger.append({"mutation": "b", "score": 0.95})

    report = ledger.verify_chain()

    assert report["ok"] is True
    assert report["count"] == 2


def test_ledger_store_detects_hash_chain_tamper(tmp_path) -> None:
    ledger_path = tmp_path / "scoring.jsonl"
    ledger = ScoringLedgerStore(path=ledger_path, backend="json")
    ledger.append({"mutation": "a", "score": 0.9})
    ledger.append({"mutation": "b", "score": 0.95})

    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    lines[1] = lines[1].replace('"prev_hash": "', '"prev_hash": "sha256:deadbeef')
    ledger_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = ledger.verify_chain()

    assert report["ok"] is False
    assert report["error"] == "prev_hash_mismatch"


def test_ledger_store_json_sqlite_parity(tmp_path) -> None:
    json_path = tmp_path / "scoring.jsonl"
    sqlite_path = tmp_path / "scoring.sqlite"
    json_ledger = ScoringLedgerStore(path=json_path, backend="json")
    sqlite_ledger = ScoringLedgerStore(path=json_path, sqlite_path=sqlite_path, backend="sqlite")

    events = [{"mutation": "a", "score": 0.9}, {"mutation": "b", "score": 0.95}, {"mutation": "c", "score": 1.0}]
    for event in events:
        json_ledger.append(event)
        sqlite_ledger.append(event)

    assert json_ledger.iter_records() == sqlite_ledger.iter_records()
    assert sqlite_ledger.verify_chain()["ok"] is True
