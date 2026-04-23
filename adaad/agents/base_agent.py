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
Base agent definition and validation utilities.
"""

from abc import ABC, abstractmethod
import ast
import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple

from adaad.agents.discovery import iter_agent_dirs, resolve_agent_id, resolve_agent_module_entrypoint
from runtime.api.app_layer import metrics

REQUIRED_FILES = ("meta.json", "dna.json", "certificate.json")
ROLE_PRESETS: Dict[str, Dict[str, float]] = {
    "builder": {"build": 1.0, "optimize": 0.45, "test": 0.55, "market": 0.15},
    "optimizer": {"build": 0.45, "optimize": 1.0, "test": 0.4, "market": 0.2},
    "tester": {"build": 0.4, "optimize": 0.35, "test": 1.0, "market": 0.25},
    "marketer": {"build": 0.25, "optimize": 0.25, "test": 0.3, "market": 1.0},
}
_FUNCTION_SIGNATURES = {
    "info": {"params": [], "return": "dict"},
    "run": {"params": ["input"], "defaults": {"input": None}, "return": "dict"},
    "mutate": {"params": ["src"], "annotations": {"src": "str"}, "return": "str"},
    "score": {"params": ["output"], "annotations": {"output": "dict"}, "return": "float"},
}


class BaseAgent(ABC):
    """
    Minimal interface for agents participating in mutation cycles.
    """

    def __init__(
        self,
        *,
        role: str = "builder",
        skill_vector: Optional[Mapping[str, float]] = None,
        score_history: Optional[List[float]] = None,
        lineage_id: Optional[str] = None,
        survival_rank: float = 0.0,
        memory_ref: Optional[str] = None,
    ) -> None:
        self.role = role if role in ROLE_PRESETS else "builder"
        self.skill_vector = dict(skill_vector or ROLE_PRESETS[self.role])
        self.score_history = [float(score) for score in (score_history or [])]
        self.lineage_id = lineage_id or self.__class__.__name__.lower()
        self.survival_rank = float(survival_rank)
        self.memory_ref = memory_ref

    @abstractmethod
    def info(self) -> Dict:
        """Return descriptive metadata for the agent instance."""

    @abstractmethod
    def run(self, input=None) -> Dict:
        """Execute the agent against the provided input payload."""

    @abstractmethod
    def mutate(self, src: str) -> str:
        """Produce a deterministic mutation of source content."""

    @abstractmethod
    def score(self, output: Dict) -> float:
        """Score an output payload for downstream selection logic."""

    def compatibility_score(self, task_profile: Mapping[str, float]) -> float:
        score = 0.0
        for key, weight in task_profile.items():
            score += float(self.skill_vector.get(key, 0.0)) * float(weight)
        return round(score, 6)

    def update_score_history(self, value: float, window: int = 50) -> None:
        self.score_history.append(float(value))
        if window > 0 and len(self.score_history) > window:
            self.score_history = self.score_history[-window:]

    def score_trend(self, window: int = 5) -> float:
        if len(self.score_history) < 2:
            return 0.0
        history = self.score_history[-max(2, window) :]
        return (history[-1] - history[0]) / max(1, len(history) - 1)


def assign_task_by_role(
    agents: List[BaseAgent],
    task_profile: Mapping[str, float],
) -> Optional[BaseAgent]:
    """Return the agent with the strongest role-compatibility score."""
    if not agents:
        return None
    return max(agents, key=lambda agent: (agent.compatibility_score(task_profile), agent.score_trend(), agent.role))


def validate_agent_home(agent_path: Path) -> Tuple[bool, List[str]]:
    """
    Validate that a single agent directory contains the required files.
    """
    missing: List[str] = []
    for required in REQUIRED_FILES:
        if not (agent_path / required).exists():
            missing.append(required)
    if missing:
        metrics.log(
            event_type="agent_missing_metadata",
            payload={"agent": agent_path.name, "missing": missing},
            level="ERROR",
        )
        return False, missing
    return True, []


def _annotation_name(node: Optional[ast.AST]) -> Optional[str]:
    if node is None:
        return None
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ast.unparse(node)


def _extract_module_functions(module_tree: ast.Module) -> Dict[str, ast.FunctionDef]:
    functions: Dict[str, ast.FunctionDef] = {}
    for node in module_tree.body:
        if isinstance(node, ast.FunctionDef):
            functions[node.name] = node
        if isinstance(node, ast.ClassDef):
            for class_node in node.body:
                if isinstance(class_node, ast.FunctionDef) and class_node.name not in functions:
                    functions[class_node.name] = class_node
    return functions


def _validate_function_signature(func: ast.FunctionDef, name: str) -> List[str]:
    errors: List[str] = []
    expected = _FUNCTION_SIGNATURES[name]
    positional_args = [arg.arg for arg in func.args.posonlyargs + func.args.args]
    normalized_args = positional_args[:]
    if normalized_args and normalized_args[0] in {"self", "cls"}:
        normalized_args = normalized_args[1:]
    if normalized_args != expected["params"]:
        errors.append(
            f"AGENT_CONTRACT_SIGNATURE_MISMATCH:{name}: expected params {expected['params']}, got {normalized_args}"
        )
    if func.args.vararg or func.args.kwarg or func.args.kwonlyargs:
        errors.append(
            f"AGENT_CONTRACT_SIGNATURE_MISMATCH:{name}: variadic and keyword-only parameters are not allowed"
        )

    expected_defaults = expected.get("defaults", {})
    defaults_by_param = {}
    if func.args.defaults:
        defaults_by_param = {
            param: default for param, default in zip(positional_args[-len(func.args.defaults) :], func.args.defaults)
        }
    for param, default_value in expected_defaults.items():
        if param not in defaults_by_param:
            errors.append(f"AGENT_CONTRACT_SIGNATURE_MISMATCH:{name}: missing default for parameter '{param}'")
            continue
        default_node = defaults_by_param[param]
        if not (isinstance(default_node, ast.Constant) and default_node.value is default_value):
            errors.append(
                f"AGENT_CONTRACT_SIGNATURE_MISMATCH:{name}: default for '{param}' must be {default_value!r}"
            )

    for param, annotation in expected.get("annotations", {}).items():
        arg_node = next((arg for arg in func.args.posonlyargs + func.args.args if arg.arg == param), None)
        actual_annotation = _annotation_name(arg_node.annotation if arg_node else None)
        if actual_annotation != annotation:
            errors.append(
                f"AGENT_CONTRACT_SIGNATURE_MISMATCH:{name}: annotation for '{param}' must be {annotation}, got {actual_annotation or 'None'}"
            )

    actual_return = _annotation_name(func.returns)
    if actual_return != expected["return"]:
        errors.append(
            f"AGENT_CONTRACT_SIGNATURE_MISMATCH:{name}: return annotation must be {expected['return']}, got {actual_return or 'None'}"
        )
    return errors


def validate_agent_entrypoint(agent_path: Path) -> Tuple[bool, List[str]]:
    entrypoint = resolve_agent_module_entrypoint(agent_path)
    if entrypoint is None:
        return False, ["AGENT_MODULE_ENTRYPOINT_MISSING: unable to resolve agent python module entrypoint"]

    try:
        source = entrypoint.read_text(encoding="utf-8")
    except OSError as exc:
        return False, [f"AGENT_MODULE_READ_ERROR: failed to read {entrypoint}: {exc}"]

    try:
        module_tree = ast.parse(source, filename=str(entrypoint))
    except SyntaxError as exc:
        return False, [f"AGENT_MODULE_PARSE_ERROR: {entrypoint}:{exc.lineno}:{exc.offset}: {exc.msg}"]

    functions = _extract_module_functions(module_tree)
    errors: List[str] = []
    for required_name in _FUNCTION_SIGNATURES:
        if required_name not in functions:
            errors.append(f"AGENT_CONTRACT_MISSING_FUNCTION:{required_name}: required function is not defined")
            continue
        errors.extend(_validate_function_signature(functions[required_name], required_name))

    return (len(errors) == 0), errors



def _extract_error_code(error: str) -> str:
    segments = [segment.strip() for segment in error.split(":") if segment.strip()]
    for segment in segments:
        if segment.startswith("AGENT_"):
            return segment
    return "UNKNOWN"

def validate_agents(agents_root: Path) -> Tuple[bool, List[str]]:
    """
    Validate all agent directories and fail fast on missing metadata.
    """
    errors: List[str] = []
    if not agents_root.exists():
        return False, [f"{agents_root} does not exist"]

    for agent_dir in iter_agent_dirs(agents_root):
        if agent_dir.name == "agent_template":
            continue
        if agent_dir.name.startswith(("__", ".")):
            continue
        valid, missing = validate_agent_home(agent_dir)
        if not valid:
            errors.append(f"{resolve_agent_id(agent_dir, agents_root)}: {','.join(missing)}")
            continue
        entry_valid, entry_errors = validate_agent_entrypoint(agent_dir)
        if not entry_valid:
            agent_id = resolve_agent_id(agent_dir, agents_root)
            for entry_error in entry_errors:
                errors.append(f"{agent_id}: {entry_error}")
    if errors:
        metrics.log(
            event_type="agent_validation_failed",
            payload={"errors": errors, "error_count": len(errors), "error_codes": sorted({_extract_error_code(e) for e in errors})},
            level="ERROR",
        )
        return False, errors
    metrics.log(event_type="agent_validation_passed", payload={"agents": agents_root.name}, level="INFO")
    return True, []


def stage_offspring(
    parent_id: str,
    content: str,
    lineage_dir: Path,
    *,
    dream_mode: bool = False,
    handoff_contract: Optional[Dict[str, object]] = None,
    sandboxed: Optional[bool] = None,
    mutation_intent: Optional[str] = None,
    schema_version: str = "1.0",
) -> Path:
    """
    Stage a mutated offspring into the _staging area with metadata and hash.
    """
    staging_root = lineage_dir / "_staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d%H%M%S", time.gmtime())
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:8]
    intent_label = (mutation_intent or "unknown").strip().replace(" ", "_")
    parent_label = parent_id.replace(":", "_").replace("/", "_")
    flag_label = "dream" if dream_mode else "standard"
    staged_dir = staging_root / f"{timestamp}_{parent_label}_{intent_label}_{flag_label}_{content_hash}"
    staged_dir.mkdir(parents=True, exist_ok=True)
    sandboxed_flag = sandboxed if sandboxed is not None else bool(dream_mode)
    payload = {
        "schema_version": schema_version,
        "parent": parent_id,
        "content": content,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "content_hash": content_hash,
        "dream_mode": dream_mode,
        "sandboxed": sandboxed_flag,
        "mutation_intent": mutation_intent,
    }
    if handoff_contract is not None:
        payload["handoff_contract"] = handoff_contract
    with (staged_dir / "mutation.json").open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    metrics.log(event_type="offspring_staged", payload={"path": str(staged_dir)}, level="INFO")
    return staged_dir


def promote_offspring(staged_dir: Path, lineage_dir: Path) -> Path:
    """
    Promote a staged offspring into the main lineage directory.
    """
    if not staged_dir.exists():
        raise FileNotFoundError(f"staged_dir missing: {staged_dir}")
    lineage_dir.mkdir(parents=True, exist_ok=True)
    target_dir = lineage_dir / staged_dir.name
    shutil.move(str(staged_dir), target_dir)
    metrics.log(event_type="offspring_promoted", payload={"from": str(staged_dir), "to": str(target_dir)}, level="INFO")
    return target_dir
