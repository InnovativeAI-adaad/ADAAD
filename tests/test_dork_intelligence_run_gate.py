# SPDX-License-Identifier: Apache-2.0
import json
import subprocess
import sys
import types


def _load_intelligence_module():
    sys.modules.setdefault("dorkllm.retriever", types.ModuleType("dorkllm.retriever"))
    import dorkllm.intelligence as intelligence  # local import for test isolation
    return intelligence


class _FakeHTTPResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _mock_llm_response(monkeypatch, text: str) -> None:
    intelligence = _load_intelligence_module()
    payload = {"message": {"content": text}}
    monkeypatch.setattr(
        intelligence.urllib.request,
        "urlopen",
        lambda req, timeout=30: _FakeHTTPResponse(payload),
    )


def test_run_tag_blocked_by_default(monkeypatch):
    intelligence = _load_intelligence_module()
    monkeypatch.delenv("ADAAD_DORK_ALLOW_RUN_TAGS", raising=False)
    monkeypatch.delenv("ADAAD_DORK_RUN_ALLOWLIST", raising=False)
    monkeypatch.delenv("ADAAD_DORK_RUN_ALLOW_PREFIXES", raising=False)
    _mock_llm_response(monkeypatch, "<run>echo hi</run>")

    trace_calls = []
    monkeypatch.setattr(intelligence, "log_trace", lambda event, payload: trace_calls.append((event, payload)))

    run_calls = []
    monkeypatch.setattr(intelligence.subprocess, "run", lambda *args, **kwargs: run_calls.append((args, kwargs)))

    response, _ = intelligence.ask("test query")

    assert response.startswith("Policy blocked")
    assert run_calls == []
    assert any(event == "tool_invocation_blocked" for event, _ in trace_calls)


def test_run_tag_allowed_when_gate_enabled_and_command_allowlisted(monkeypatch):
    intelligence = _load_intelligence_module()
    monkeypatch.setenv("ADAAD_DORK_ALLOW_RUN_TAGS", "1")
    monkeypatch.setenv("ADAAD_DORK_RUN_ALLOWLIST", "echo")
    monkeypatch.delenv("ADAAD_DORK_RUN_ALLOW_PREFIXES", raising=False)

    _mock_llm_response(monkeypatch, "<run>echo hi</run>")

    trace_calls = []
    monkeypatch.setattr(intelligence, "log_trace", lambda event, payload: trace_calls.append((event, payload)))

    captured = {}

    def _fake_run(argv, shell, capture_output, text, timeout):
        captured["argv"] = argv
        captured["shell"] = shell
        captured["capture_output"] = capture_output
        captured["text"] = text
        captured["timeout"] = timeout
        return subprocess.CompletedProcess(argv, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(intelligence.subprocess, "run", _fake_run)

    response, messages = intelligence.ask("test query")

    assert response == "Error: Max turns reached without final response."
    assert captured["argv"] == ["echo", "hi"]
    assert captured["shell"] is False
    assert any(event == "tool_invocation_allowed" for event, _ in trace_calls)
    assert messages[-1]["content"].startswith("Command output:")


def test_trace_contains_blocked_and_allowed_flow_details(monkeypatch):
    intelligence = _load_intelligence_module()
    traces = []
    monkeypatch.setattr(intelligence, "log_trace", lambda event, payload: traces.append((event, payload)))

    monkeypatch.delenv("ADAAD_DORK_ALLOW_RUN_TAGS", raising=False)
    _mock_llm_response(monkeypatch, "<run>echo blocked</run>")
    intelligence.ask("blocked path")
    blocked_event, blocked_payload = next((t for t in traces if t[0] == "tool_invocation_blocked"), (None, None))
    assert blocked_event == "tool_invocation_blocked"
    assert blocked_payload["policy"] == "run_tags_disabled"

    traces.clear()
    monkeypatch.setenv("ADAAD_DORK_ALLOW_RUN_TAGS", "1")
    monkeypatch.setenv("ADAAD_DORK_RUN_ALLOWLIST", "echo")
    _mock_llm_response(monkeypatch, "<run>echo allowed</run>")
    monkeypatch.setattr(
        intelligence.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout="ok\n", stderr=""),
    )
    intelligence.ask("allowed path")
    allowed_event, allowed_payload = next((t for t in traces if t[0] == "tool_invocation_allowed"), (None, None))
    assert allowed_event == "tool_invocation_allowed"
    assert allowed_payload["tool"] == "run"
