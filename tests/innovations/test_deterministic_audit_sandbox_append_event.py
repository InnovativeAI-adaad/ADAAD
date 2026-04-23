# SPDX-License-Identifier: Apache-2.0
import json

from runtime.innovations30.deterministic_audit_sandbox import DeterministicAuditSandbox


def test_append_event_writes_to_sandbox_ledger_path(tmp_path):
    ledger_path = tmp_path / "sandbox" / "das.jsonl"
    sandbox = DeterministicAuditSandbox(ledger_path=ledger_path)

    sandbox._append_event({"z": 2, "a": 1})

    assert ledger_path.exists()
    raw = ledger_path.read_text(encoding="utf-8")
    assert raw.endswith("\n")
    assert raw == '{"a": 1, "z": 2}\n'
    assert json.loads(raw.strip()) == {"a": 1, "z": 2}
