# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

SKILLS = Path("ui/developer/ADAADdev/dork_skills.js")
RUNTIME = Path("ui/developer/ADAADdev/dork_runtime.js")
WHALEDIC = Path("ui/developer/ADAADdev/whaledic.html")


def _src() -> str:
    return SKILLS.read_text(encoding="utf-8")


def test_skill_registry_contains_expected_slash_commands() -> None:
    src = _src()
    for cmd in ["'/gate'", "'/replay'", "'/blockers'", "'/phase'", "'/evidence'", "'/health'"]:
        assert cmd in src


def test_intent_parser_supports_required_commands() -> None:
    src = _src()
    assert "match(/^\\/(gate|replay|blockers|phase|evidence|health)\\b/)" in src
    assert "function parseIntent(rawText)" in src


def test_low_confidence_fallback_contract_present() -> None:
    src = _src()
    assert "LOW_CONFIDENCE_THRESHOLD" in src
    assert "failure_reason: 'low_confidence'" in src
    assert "needs_clarification: true" in src
    assert "clarifying_question" in src


def test_router_output_schema_is_stable() -> None:
    src = _src()
    assert "const ROUTER_OUTPUT_KEYS = Object.freeze([" in src
    for key in [
        "'schema'",
        "'intent'",
        "'command'",
        "'confidence'",
        "'markdown'",
        "'needs_clarification'",
        "'clarifying_question'",
        "'failure_reason'",
    ]:
        assert key in src


def test_runtime_uses_skill_router_before_provider_call() -> None:
    src = RUNTIME.read_text(encoding="utf-8")
    assert "const skillApi = global.DORK_SKILLS;" in src
    assert "runtime.emitEvent(\"dork_skill_usage\"" in src
    assert "runtime.emitEvent(\"dork_skill_failure\"" in src
    assert "provider: \"dorkskill\"" in src


def test_runtime_instruments_state_bus_skill_telemetry() -> None:
    src = RUNTIME.read_text(encoding="utf-8")
    assert "dork_skill_last" in src
    assert 'source: "dork_skill_router"' in src
    assert "latency_ms" in src


def test_whaledic_loads_dork_skills_script() -> None:
    html = WHALEDIC.read_text(encoding="utf-8")
    assert 'script src="./dork_skills.js"' in html
