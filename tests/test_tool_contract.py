# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

from adaad.core.tool_contract import discover_tool_modules, validate_tool_contracts, validate_tool_module
from runtime.preflight import validate_tool_contract_preflight


def test_discovery_includes_migrated_and_template_modules() -> None:
    root = Path(__file__).resolve().parents[1]

    modules = discover_tool_modules(root)

    assert Path("tools/asset_generator.py") in modules
    assert Path("adaad/tools/tool_template.py") in modules


def test_validator_reports_missing_required_symbols(tmp_path: Path) -> None:
    module = tmp_path / "bad_tool.py"
    module.write_text("def run_tool(params):\n    return {}\n", encoding="utf-8")

    result = validate_tool_module(module, root=tmp_path)

    assert result.ok is False
    messages = [item.message for item in result.violations]
    assert "Missing TOOL_ID" in messages
    assert "Missing VERSION" in messages
    assert "Missing get_tool_manifest" in messages


def test_validator_reports_semver_and_signature_mismatch(tmp_path: Path) -> None:
    module = tmp_path / "almost_tool.py"
    module.write_text(
        """
TOOL_ID = "almost"
VERSION = "1"

def get_tool_manifest(extra):
    return {}

def run_tool(a, b):
    return {}
""",
        encoding="utf-8",
    )

    result = validate_tool_module(module, root=tmp_path)

    assert result.ok is False
    assert any(item.message == "VERSION must be a valid semver string" for item in result.violations)
    assert any("get_tool_manifest must have signature" in item.message for item in result.violations)
    assert any("run_tool must have signature" in item.message for item in result.violations)


def test_repo_contracts_pass_and_preflight_wrapper_matches() -> None:
    root = Path(__file__).resolve().parents[1]

    direct = validate_tool_contracts(root)
    preflight = validate_tool_contract_preflight()

    assert direct["ok"] is True
    assert preflight["ok"] is True
    assert preflight["checked_modules"] >= 2
