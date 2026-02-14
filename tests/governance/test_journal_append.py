# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from security.ledger import journal


def _set_temp_paths(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    original_journal = journal.JOURNAL_PATH
    original_genesis = journal.GENESIS_PATH
    original_tail = journal.TAIL_STATE_PATH
    original_lock = journal.LOCK_PATH
    journal.JOURNAL_PATH = tmp_path / "cryovant_journal.jsonl"  # type: ignore
    journal.GENESIS_PATH = tmp_path / "cryovant_journal.genesis.jsonl"  # type: ignore
    journal.TAIL_STATE_PATH = tmp_path / "cryovant_journal.tail.json"  # type: ignore
    journal.LOCK_PATH = tmp_path / "cryovant_journal.lock"  # type: ignore
    return original_journal, original_genesis, original_tail, original_lock


def _restore_paths(paths: tuple[Path, Path, Path, Path]) -> None:
    journal.JOURNAL_PATH = paths[0]  # type: ignore
    journal.GENESIS_PATH = paths[1]  # type: ignore
    journal.TAIL_STATE_PATH = paths[2]  # type: ignore
    journal.LOCK_PATH = paths[3]  # type: ignore


def test_journal_hash_chaining(tmp_path: Path) -> None:
    original_paths = _set_temp_paths(tmp_path)
    try:
        first = journal.append_tx("test", {"i": 1}, tx_id="TX-1")
        second = journal.append_tx("test", {"i": 2}, tx_id="TX-2")
        assert second["prev_hash"] == first["hash"]
    finally:
        _restore_paths(original_paths)


def test_concurrent_thread_appends_preserve_chain(tmp_path: Path) -> None:
    original_paths = _set_temp_paths(tmp_path)
    try:
        workers = 8
        per_worker = 25

        def _append(worker_id: int, index: int) -> None:
            tx_id = f"T-{worker_id}-{index}"
            journal.append_tx("thread", {"worker": worker_id, "index": index}, tx_id=tx_id)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for worker_id in range(workers):
                for index in range(per_worker):
                    pool.submit(_append, worker_id, index)

        journal.verify_journal_integrity()
        lines = [line for line in journal.JOURNAL_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(lines) == workers * per_worker
    finally:
        _restore_paths(original_paths)


def _process_append(journal_path: str, genesis_path: str, tail_path: str, lock_path: str, tx_id: str) -> None:
    journal.JOURNAL_PATH = Path(journal_path)  # type: ignore
    journal.GENESIS_PATH = Path(genesis_path)  # type: ignore
    journal.TAIL_STATE_PATH = Path(tail_path)  # type: ignore
    journal.LOCK_PATH = Path(lock_path)  # type: ignore
    journal.append_tx("process", {"tx": tx_id}, tx_id=tx_id)


def test_concurrent_process_appends_preserve_chain(tmp_path: Path) -> None:
    original_paths = _set_temp_paths(tmp_path)
    try:
        tx_count = 24
        args = [
            (
                str(journal.JOURNAL_PATH),
                str(journal.GENESIS_PATH),
                str(journal.TAIL_STATE_PATH),
                str(journal.LOCK_PATH),
                f"P-{index}",
            )
            for index in range(tx_count)
        ]

        with multiprocessing.get_context("spawn").Pool(processes=6) as pool:
            pool.starmap(_process_append, args)

        journal.verify_journal_integrity()
        entries = [json.loads(line) for line in journal.JOURNAL_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(entries) == tx_count
        assert len({entry["tx"] for entry in entries}) == tx_count
    finally:
        _restore_paths(original_paths)
