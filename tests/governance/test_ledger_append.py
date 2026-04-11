# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import multiprocessing
from pathlib import Path

import pytest

from security.ledger.append import _read_last_entry_hash, append_entry

pytestmark = pytest.mark.governance_gate


def _read_entries(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _append_entries_worker(path: str, worker_id: int, count: int, queue: object) -> None:
    from security.ledger.append import append_entry as _append_entry

    try:
        for idx in range(count):
            _append_entry({"event_type": "concurrent", "worker_id": worker_id, "index": idx}, path=path)
    except Exception as exc:  # pragma: no cover - surfaced via queue assertion below
        queue.put(repr(exc))
        return
    queue.put(None)


def test_append_entry_chain_continuity(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"

    first = append_entry({"event_type": "alpha"}, path=str(ledger_path))
    second = append_entry({"event_type": "beta"}, path=str(ledger_path))

    assert first["prev_entry_hash"] == "0" * 64
    assert second["prev_entry_hash"] == first["entry_hash"]

    entries = _read_entries(ledger_path)
    assert entries[1]["prev_entry_hash"] == entries[0]["entry_hash"]


def test_append_entry_rejects_malformed_tail(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    ledger_path.write_text('{"event_type":"ok","entry_hash":"' + ("a" * 64) + '"}\nnot-json\n', encoding="utf-8")

    with pytest.raises(ValueError, match="^ledger_tail_invalid$"):
        append_entry({"event_type": "gamma"}, path=str(ledger_path))

    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    assert lines[-1] == "not-json"


def test_append_entry_preserves_genesis_for_empty_file(tmp_path: Path) -> None:
    missing_path = tmp_path / "new-ledger.jsonl"
    created = append_entry({"event_type": "genesis"}, path=str(missing_path))
    assert created["prev_entry_hash"] == "0" * 64

    empty_path = tmp_path / "empty-ledger.jsonl"
    empty_path.write_text("\n", encoding="utf-8")
    appended = append_entry({"event_type": "genesis-2"}, path=str(empty_path))
    assert appended["prev_entry_hash"] == "0" * 64


def test_tail_hash_reader_handles_large_file(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger-large.jsonl"
    for idx in range(3000):
        append_entry({"event_type": "bulk", "index": idx}, path=str(ledger_path))

    entries = _read_entries(ledger_path)
    assert _read_last_entry_hash(str(ledger_path)) == entries[-1]["entry_hash"]


def test_append_entry_is_atomic_under_multiprocess_contention(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger-concurrent.jsonl"
    process_count = 4
    appends_per_process = 40
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    procs = [
        ctx.Process(target=_append_entries_worker, args=(str(ledger_path), proc_idx, appends_per_process, queue))
        for proc_idx in range(process_count)
    ]
    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join(timeout=60)
        assert proc.exitcode == 0

    worker_errors = [queue.get(timeout=2) for _ in procs]
    assert worker_errors == [None] * process_count

    entries = _read_entries(ledger_path)
    assert len(entries) == process_count * appends_per_process
    assert entries[0]["prev_entry_hash"] == "0" * 64
    for idx in range(1, len(entries)):
        assert entries[idx]["prev_entry_hash"] == entries[idx - 1]["entry_hash"]


def test_read_last_entry_hash_rejects_malformed_tail_after_whitespace(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger-tail-invalid.jsonl"
    append_entry({"event_type": "ok"}, path=str(ledger_path))
    with ledger_path.open("ab") as handle:
        handle.write(b"\n\nnot-json\n\n")

    with pytest.raises(ValueError, match="^ledger_tail_invalid$"):
        _read_last_entry_hash(str(ledger_path))
