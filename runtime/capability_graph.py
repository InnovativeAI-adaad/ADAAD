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
Graph-backed capability registry enforcing dependencies and monotonic scores.
"""

from __future__ import annotations

import fcntl
import json
import tempfile
import time
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Tuple

from runtime import ROOT_DIR, metrics

CAPABILITIES_PATH = ROOT_DIR / "data" / "capabilities.json"
_CONFLICT_RETRIES = 5


def _lock_path() -> Path:
    return CAPABILITIES_PATH.parent / f"{CAPABILITIES_PATH.name}.lock"


@contextmanager
def _capabilities_lock() -> Iterator[None]:
    lock_path = _lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _file_state(path: Path) -> Tuple[int | None, str]:
    if not path.exists():
        return None, sha256(b"{}").hexdigest()
    raw = path.read_bytes()
    return path.stat().st_mtime_ns, sha256(raw).hexdigest()


def _load() -> Dict[str, Dict[str, Any]]:
    if not CAPABILITIES_PATH.exists():
        return {}
    try:
        return json.loads(CAPABILITIES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save(data: Dict[str, Dict[str, Any]]) -> None:
    CAPABILITIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=CAPABILITIES_PATH.parent,
        prefix=f".{CAPABILITIES_PATH.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(payload)
        handle.flush()
        temp_path = Path(handle.name)
    temp_path.replace(CAPABILITIES_PATH)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _missing_dependencies(registry: Dict[str, Dict[str, Any]], requires: Iterable[str]) -> List[str]:
    return [req for req in requires if req not in registry]


def register_capability(
    name: str,
    version: str,
    score: float,
    owner_element: str,
    requires: List[str] | None = None,
    evidence: Dict[str, Any] | None = None,
) -> Tuple[bool, str]:
    """
    Register or update a capability while enforcing dependency presence and monotonic score.
    """

    requires = requires or []

    for attempt in range(1, _CONFLICT_RETRIES + 1):
        previous_mtime, previous_digest = _file_state(CAPABILITIES_PATH)
        registry = _load()

        missing = _missing_dependencies(registry, requires)
        if missing:
            message = f"missing dependencies for {name}: {','.join(missing)}"
            metrics.log(
                event_type="capability_graph_rejected",
                payload={"name": name, "score": score, "reason": "missing_dependencies", "missing": missing},
                level="ERROR",
                element_id=owner_element,
            )
            return False, message

        existing = registry.get(name, {})
        try:
            existing_score = float(existing.get("score", -1))
        except (TypeError, ValueError):
            existing_score = -1

        if score < existing_score:
            message = f"score regression prevented for {name}"
            metrics.log(
                event_type="capability_graph_rejected",
                payload={
                    "name": name,
                    "score": score,
                    "reason": "score_regression",
                    "previous": existing_score,
                },
                level="ERROR",
                element_id=owner_element,
            )
            return False, message

        registry[name] = {
            "name": name,
            "version": version,
            "score": score,
            "owner": owner_element,
            "requires": list(requires),
            "evidence": evidence or {},
            "updated_at": _now(),
        }

        with _capabilities_lock():
            current_mtime, current_digest = _file_state(CAPABILITIES_PATH)
            if (current_mtime, current_digest) != (previous_mtime, previous_digest):
                metrics.log(
                    event_type="capability_graph_conflict",
                    payload={
                        "name": name,
                        "attempt": attempt,
                        "outcome": "conflict_detected",
                        "retries_remaining": _CONFLICT_RETRIES - attempt,
                    },
                    level="WARNING",
                    element_id=owner_element,
                )
                continue
            _save(registry)

        metrics.log(
            event_type="capability_graph_conflict",
            payload={
                "name": name,
                "attempt": attempt,
                "outcome": "commit_success",
                "retries_used": attempt - 1,
            },
            level="INFO",
            element_id=owner_element,
        )
        break
    else:
        metrics.log(
            event_type="capability_graph_conflict",
            payload={"name": name, "outcome": "retry_exhausted", "attempts": _CONFLICT_RETRIES},
            level="ERROR",
            element_id=owner_element,
        )
        return False, f"conflict retries exhausted for {name}"

    metrics.log(
        event_type="capability_graph_registered",
        payload={
            "name": name,
            "version": version,
            "score": score,
            "owner": owner_element,
            "requires": list(requires),
        },
        level="INFO",
        element_id=owner_element,
    )
    return True, "ok"


def get_capabilities() -> Dict[str, Dict[str, Any]]:
    return _load()
