# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import hashlib
import json
import os
import string
import time
from contextlib import contextmanager
from typing import IO
from typing import Any, Dict

LEDGER_PATH = os.path.join("security", "ledger", "ledger.jsonl")
_LOCK_POLL_SECONDS = 0.01
_TAIL_READ_CHUNK_SIZE = 8192


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _read_last_nonempty_jsonl_line(handle: IO[bytes], chunk_size: int = _TAIL_READ_CHUNK_SIZE) -> bytes | None:
    handle.seek(0, os.SEEK_END)
    end = handle.tell()
    if end <= 0:
        return None

    tail = b""
    seen_non_whitespace = False
    while end > 0:
        start = max(0, end - chunk_size)
        handle.seek(start, os.SEEK_SET)
        block = handle.read(end - start)
        end = start

        if not seen_non_whitespace:
            i = len(block) - 1
            while i >= 0 and block[i : i + 1].isspace():
                i -= 1
            if i < 0:
                continue
            block = block[: i + 1]
            seen_non_whitespace = True

        newline_pos = block.rfind(b"\n")
        if newline_pos >= 0:
            tail = block[newline_pos + 1 :] + tail
            break
        tail = block + tail

    if not seen_non_whitespace:
        return None
    line = tail.strip()
    return line or None


def _read_last_entry_hash(path: str) -> str:
    if not os.path.exists(path):
        return "0" * 64
    with open(path, "rb") as f:
        return _read_last_entry_hash_from_handle(f)


def _read_last_entry_hash_from_handle(handle: IO[bytes]) -> str:
    last = _read_last_nonempty_jsonl_line(handle)
    if last is None:
        return "0" * 64
    try:
        obj = json.loads(last.decode("utf-8"))
    except Exception as exc:
        raise ValueError("ledger_tail_invalid") from exc

    entry_hash = obj.get("entry_hash")
    if not isinstance(entry_hash, str) or len(entry_hash) != 64 or any(ch not in string.hexdigits for ch in entry_hash):
        raise ValueError("ledger_tail_invalid")
    return entry_hash


@contextmanager
def _locked_handle(path: str) -> IO[bytes]:
    with open(path, "a+b") as handle:
        if os.name == "posix":
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield handle
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            return

        if os.name == "nt":
            import msvcrt

            handle.seek(0, os.SEEK_SET)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield handle
            finally:
                handle.seek(0, os.SEEK_SET)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            return

        lock_path = f"{path}.lock"
        while True:
            try:
                fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
                break
            except FileExistsError:
                time.sleep(_LOCK_POLL_SECONDS)
        try:
            yield handle
        finally:
            os.close(fd)
            try:
                os.unlink(lock_path)
            except FileNotFoundError:
                pass


def _fsync_parent_directory(path: str) -> None:
    if os.name != "posix":
        return
    directory = os.path.dirname(path) or "."
    try:
        dir_fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def append_entry(entry: Dict[str, Any], path: str = LEDGER_PATH) -> Dict[str, Any]:
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with _locked_handle(path) as f:
        prev = _read_last_entry_hash_from_handle(f)
        entry = dict(entry)
        entry["prev_entry_hash"] = prev

        canonical = json.dumps(entry, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        entry_hash = _sha256_hex(canonical)
        entry["entry_hash"] = entry_hash

        line = (json.dumps(entry, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
        f.seek(0, os.SEEK_END)
        f.write(line)
        f.flush()
        os.fsync(f.fileno())
    _fsync_parent_directory(path)

    return entry


__all__ = ["append_entry", "LEDGER_PATH"]
