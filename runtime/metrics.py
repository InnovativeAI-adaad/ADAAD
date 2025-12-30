# SPDX-License-Identifier: Apache-2.0
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Centralized JSONL metrics writer.
"""

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from runtime import ROOT_DIR

ELEMENT_ID = "Earth"

METRICS_PATH = ROOT_DIR / "reports" / "metrics.jsonl"


def _ensure_metrics_file() -> None:
    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not METRICS_PATH.exists():
        METRICS_PATH.touch()


def log(
    event_type: str,
    payload: Optional[Dict[str, Any]] = None,
    level: str = "INFO",
    element_id: Optional[str] = None,
) -> None:
    """
    Append a structured JSON line to the metrics file.
    """
    _ensure_metrics_file()
    record = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": event_type,
        "level": level,
        "element": element_id or ELEMENT_ID,
        "payload": payload or {},
    }
    with METRICS_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def tail(limit: int = 100) -> List[Dict[str, Any]]:
    """
    Return the most recent entries from the metrics log.
    """
    _ensure_metrics_file()
    raw_lines, _ = _read_last_lines(METRICS_PATH, limit)
    entries: List[Dict[str, Any]] = []
    for line in raw_lines:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def _read_last_lines(path: Path, limit: int, chunk_size: int = 4096) -> Tuple[List[str], int]:
    """
    Read only the last `limit` lines from a UTF-8 file without loading it fully
    into memory. Returns the decoded lines (newlines stripped) and the number of
    bytes read to satisfy the request.
    """
    decoded: List[str] = []
    bytes_read = 0
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        buffer = b""
        lines_found = 0
        position = handle.tell()
        while position > 0 and lines_found < limit + 1:
            step = min(chunk_size, position)
            position -= step
            handle.seek(position)
            chunk = handle.read(step)
            bytes_read += len(chunk)
            buffer = chunk + buffer
            lines_found = buffer.count(b"\n")
            if lines_found >= limit + 1:
                break

    if buffer:
        decoded = [line.decode("utf-8", errors="ignore") for line in buffer.splitlines()[-limit:]]
    return decoded, bytes_read
