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
ERROR_RESOURCE_PROFILE_INVALID = "INV_RESOURCE_PROFILE_INVALID"
ERROR_LINEAGE_PARENT = "INV_LINEAGE_PARENT_MISSING"
ERROR_LINEAGE_PARENT_INVALID = "INV_LINEAGE_PARENT_INVALID"
ERROR_BOOT_SIGNATURE = "INV_BOOT_SIGNATURE_MISSING"
ERROR_BOOT_SIGNATURE_DRIFT = "INV_BOOT_SIGNATURE_DRIFT"
ERROR_MUTABLE_GLOBAL_DEPENDENCIES = "INV_MUTABLE_GLOBAL_DEPENDENCIES"
ERROR_DREAM_SCOPE_ALLOW = "INV_DREAM_SCOPE_ALLOW_MISSING"

ALLOWED_RESOURCE_PROFILES = {"default", "sandbox", "privileged"}


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


def _check_agent_invariants(
    agent_dir: Path,
    agents_root: Path,
    lineage_roots: set[str],
    boot_signatures: Dict[str, str],
) -> List[str]:
    errors: List[str] = []
    meta = _load_json(agent_dir / "meta.json")
    dna = _load_json(agent_dir / "dna.json")
    if meta is None or dna is None:
        return errors

    agent_id = resolve_agent_id(agent_dir, agents_root)

    resource_envelope = meta.get("resource_envelope")
    if resource_envelope is None:
        errors.append(f"{agent_id}:{ERROR_RESOURCE_ENVELOPE}")
    elif isinstance(resource_envelope, dict):
        profile = resource_envelope.get("profile")
        if profile not in ALLOWED_RESOURCE_PROFILES:
            errors.append(f"{agent_id}:{ERROR_RESOURCE_PROFILE_INVALID}")
    else:
        errors.append(f"{agent_id}:{ERROR_RESOURCE_PROFILE_INVALID}")

    lineage_parent = dna.get("lineage_parent") or dna.get("parent") or meta.get("lineage_parent")
    if not lineage_parent:
        errors.append(f"{agent_id}:{ERROR_LINEAGE_PARENT}")
    elif lineage_parent not in lineage_roots:
        errors.append(f"{agent_id}:{ERROR_LINEAGE_PARENT_INVALID}")

    boot_signature = meta.get("boot_signature") or dna.get("boot_signature")
    if not boot_signature:
        errors.append(f"{agent_id}:{ERROR_BOOT_SIGNATURE}")
    elif lineage_parent and lineage_parent in boot_signatures:
        parent_signature = boot_signatures[lineage_parent]
        override_reason = meta.get("boot_signature_override_reason")
        if parent_signature and boot_signature != parent_signature and not override_reason:
            errors.append(f"{agent_id}:{ERROR_BOOT_SIGNATURE_DRIFT}")

    mutable_deps = _extract_mutable_dependencies(meta)
    if mutable_deps is None:
        errors.append(f"{agent_id}:{ERROR_MUTABLE_GLOBAL_DEPENDENCIES}")
    elif isinstance(mutable_deps, list) and mutable_deps:
        errors.append(f"{agent_id}:{ERROR_MUTABLE_GLOBAL_DEPENDENCIES}")
    elif not isinstance(mutable_deps, list) and mutable_deps:
        errors.append(f"{agent_id}:{ERROR_MUTABLE_GLOBAL_DEPENDENCIES}")

    scope = meta.get("dream_scope")
    if isinstance(scope, dict) and scope.get("enabled", False):
        allow = scope.get("allow", [])
        if isinstance(allow, str):
            allow = [allow]
        if not allow:
            errors.append(f"{agent_id}:{ERROR_DREAM_SCOPE_ALLOW}")

    return errors


def check_invariants(agents_root: Path) -> List[str]:
    errors: List[str] = []
    if not agents_root.exists():
        return errors

    lineage_roots: set[str] = set()
    boot_signatures: Dict[str, str] = {}
    for agent_dir in iter_agent_dirs(agents_root):
        meta = _load_json(agent_dir / "meta.json") or {}
        dna = _load_json(agent_dir / "dna.json") or {}
        lineage = dna.get("lineage")
        if isinstance(lineage, str):
            lineage_roots.add(lineage)
        lineage_parent = dna.get("lineage_parent")
        if isinstance(lineage_parent, str):
            lineage_roots.add(lineage_parent)
        boot_signature = meta.get("boot_signature")
        if isinstance(boot_signature, str):
            agent_id = resolve_agent_id(agent_dir, agents_root)
            boot_signatures[agent_id] = boot_signature

    for agent_dir in iter_agent_dirs(agents_root):
        errors.extend(_check_agent_invariants(agent_dir, agents_root, lineage_roots, boot_signatures))

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
