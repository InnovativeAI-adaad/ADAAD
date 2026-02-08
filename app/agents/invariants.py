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
Invariant checks for agent metadata.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.agents.discovery import iter_agent_dirs, resolve_agent_id
from runtime import metrics

ERROR_RESOURCE_ENVELOPE = "INV_RESOURCE_ENVELOPE_MISSING"
ERROR_LINEAGE_PARENT = "INV_LINEAGE_PARENT_MISSING"
ERROR_BOOT_SIGNATURE = "INV_BOOT_SIGNATURE_MISSING"
ERROR_MUTABLE_GLOBAL_DEPENDENCIES = "INV_MUTABLE_GLOBAL_DEPENDENCIES"


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _extract_mutable_dependencies(meta: Dict[str, Any]) -> Optional[Any]:
    if "mutable_global_dependencies" in meta:
        return meta.get("mutable_global_dependencies")
    if isinstance(meta.get("global_dependencies"), dict):
        return meta["global_dependencies"].get("mutable")
    return None


def _check_agent_invariants(agent_dir: Path, agents_root: Path) -> List[str]:
    errors: List[str] = []
    meta = _load_json(agent_dir / "meta.json")
    dna = _load_json(agent_dir / "dna.json")
    if meta is None or dna is None:
        return errors

    agent_id = resolve_agent_id(agent_dir, agents_root)

    if meta.get("resource_envelope") is None:
        errors.append(f"{agent_id}:{ERROR_RESOURCE_ENVELOPE}")

    lineage_parent = dna.get("lineage_parent") or dna.get("parent") or meta.get("lineage_parent")
    if not lineage_parent:
        errors.append(f"{agent_id}:{ERROR_LINEAGE_PARENT}")

    boot_signature = meta.get("boot_signature") or dna.get("boot_signature")
    if not boot_signature:
        errors.append(f"{agent_id}:{ERROR_BOOT_SIGNATURE}")

    mutable_deps = _extract_mutable_dependencies(meta)
    if mutable_deps is None:
        errors.append(f"{agent_id}:{ERROR_MUTABLE_GLOBAL_DEPENDENCIES}")
    elif isinstance(mutable_deps, list) and mutable_deps:
        errors.append(f"{agent_id}:{ERROR_MUTABLE_GLOBAL_DEPENDENCIES}")
    elif not isinstance(mutable_deps, list) and mutable_deps:
        errors.append(f"{agent_id}:{ERROR_MUTABLE_GLOBAL_DEPENDENCIES}")

    return errors


def check_invariants(agents_root: Path) -> List[str]:
    errors: List[str] = []
    if not agents_root.exists():
        return errors

    for agent_dir in iter_agent_dirs(agents_root):
        errors.extend(_check_agent_invariants(agent_dir, agents_root))

    if errors:
        metrics.log(
            event_type="agent_invariants_failed",
            payload={"errors": errors},
            level="ERROR",
        )
    else:
        metrics.log(
            event_type="agent_invariants_passed",
            payload={"agents": agents_root.name},
            level="INFO",
        )
    return errors

