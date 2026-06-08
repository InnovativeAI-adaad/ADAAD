# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "scan_secrets.py"
_SPEC = importlib.util.spec_from_file_location("scan_secrets", SCRIPT_PATH)
assert _SPEC and _SPEC.loader
scan_secrets = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = scan_secrets
_SPEC.loader.exec_module(scan_secrets)


def test_scan_secrets_detects_high_risk_plaintext(tmp_path: Path) -> None:
    leak_file = tmp_path / "leak.txt"
    simulated_pat = "ghp_" + "123456789012345678901234567890123456"
    simulated_claude = "sk-ant-api03-tMsC4Rm" + "A" * 95
    leak_file.write_text(f"token = '{simulated_pat}'\nclaude={simulated_claude}\n", encoding="utf-8")

    findings = scan_secrets.scan_path(tmp_path)

    assert findings
    assert any(f.rule == "github_pat" for f in findings)
    assert any(f.rule == "anthropic_claude_key" for f in findings)


def test_scan_secrets_allows_template_files(tmp_path: Path) -> None:
    template = tmp_path / ".env.example"
    template.write_text("API_KEY=placeholder\n", encoding="utf-8")

    findings = scan_secrets.scan_path(tmp_path)

    assert findings == []
