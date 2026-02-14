from __future__ import annotations

import json
from pathlib import Path

from runtime import founders_law


def test_load_law_policy_honors_rule_severity(tmp_path: Path, monkeypatch) -> None:
    policy = {
        "rules": [
            {"rule_id": founders_law.RULE_KEY_ROTATION, "enabled": True, "severity": "warning"},
            {"rule_id": founders_law.RULE_LEDGER_INTEGRITY, "enabled": True, "severity": "blocking"},
        ]
    }
    path = tmp_path / "founders_law.json"
    path.write_text(json.dumps(policy), encoding="utf-8")
    monkeypatch.setattr(founders_law, "LAW_POLICY_PATH", path)
    founders_law.reload_founders_law(force=True)

    decision = founders_law.enforce_law(
        {
            "mutation_id": "m-1",
            "checks": [
                {"rule_id": founders_law.RULE_KEY_ROTATION, "ok": False, "reason": "stale"},
                {"rule_id": founders_law.RULE_LEDGER_INTEGRITY, "ok": True, "reason": "ok"},
            ],
        }
    )
    assert decision.passed is True
