# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

from adaad.core.agent_contract import (
    discover_agent_modules,
    validate_agent_contracts,
    validate_agent_module,
    validate_legacy_agent_module,
)
from runtime.preflight import validate_agent_contract_preflight


def test_discovery_includes_agent_template() -> None:
    root = Path(__file__).resolve().parents[1]
    modules = discover_agent_modules(root)
    assert Path("adaad/agents/agent_template.py") in modules


def test_validator_reports_missing_symbols(tmp_path: Path) -> None:
    p = tmp_path / "bad_agent.py"
    p.write_text("def run_goal(goal) -> dict:\n    return {}\n", encoding="utf-8")
    result = validate_agent_module(Path("bad_agent.py"), tmp_path)
    assert result.ok is False
    msgs = [v.message for v in result.violations]
    assert "Missing AGENT_ID" in msgs
    assert "Missing info" in msgs


def test_template_contract_passes() -> None:
    root = Path(__file__).resolve().parents[1]
    result = validate_agent_contracts(root)
    assert result["ok"] is True
    assert result["checked_modules"] >= 1


def test_preflight_wrapper_matches_direct_with_legacy_bridge() -> None:
    root = Path(__file__).resolve().parents[1]
    direct = validate_agent_contracts(root, include_legacy_bridge=True)
    preflight = validate_agent_contract_preflight()
    assert direct["ok"] is True
    assert preflight["ok"] is True


def test_legacy_bridge_validates_sample_agent() -> None:
    root = Path(__file__).resolve().parents[1]
    result = validate_legacy_agent_module(Path("app/agents/sample_agent/__init__.py"), root)
    assert result.ok is True


def test_string_annotations_are_accepted(tmp_path: Path) -> None:
    module = tmp_path / "agent_with_string_ann.py"
    module.write_text(
        '''
AGENT_ID = "a"
VERSION = "1.0.0"
CAPABILITIES = []
GOAL_SCHEMA = {}
OUTPUT_SCHEMA = {}
SPAWN_POLICY = {}

def get_agent_manifest() -> "dict":
    return {}

def run_goal(goal) -> "dict":
    return {}

def info() -> "dict":
    return {}

def run(input=None) -> "dict":
    return {}

def mutate(src: "str") -> "str":
    return src

def score(output: "dict") -> "float":
    return 1.0
''',
        encoding="utf-8",
    )
    result = validate_agent_module(Path("agent_with_string_ann.py"), tmp_path)
    assert result.ok is True
