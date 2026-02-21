# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import types
from pathlib import Path

from adaad.core.cryovant_identity import build_identity
from adaad.core.health import health_report
from adaad.core.manifest import build_manifest
from adaad.core.root import get_root_dir
from adaad.orchestrator.dispatcher import dispatch
from adaad.orchestrator.registry import clear_registry, register_tool


def test_root_dir_uses_env_override(monkeypatch) -> None:
    target = Path("/tmp/adaad-root-test")
    monkeypatch.setenv("ADAAD_ROOT", str(target))
    assert get_root_dir() == target.resolve()


def test_health_and_manifest_helpers() -> None:
    payload = health_report(extra={"a": 1})
    assert '"status": "ok"' in payload
    manifest = build_manifest({"tool_id": "x"}, "desc", {"k": "v"})
    assert manifest["description"] == "desc"


def test_identity_builder() -> None:
    module = types.ModuleType("sample_mod")
    identity = build_identity(module, "tool.sample", "1.2.3")
    assert identity["tool_id"] == "tool.sample"
    assert identity["version"] == "1.2.3"
    assert len(identity["hash"]) == 64


def test_registry_and_dispatch_flow() -> None:
    clear_registry()
    register_tool("test.echo", lambda params: {"status": "success", "echo": params.get("message", "")})

    envelope = dispatch("test.echo", {"message": "hi"})
    assert envelope["result"]["status"] == "success"
    assert envelope["result"]["echo"] == "hi"
    assert "_dispatch_meta" in envelope
    assert envelope["_dispatch_meta"]["latency_ns"] >= 0

    clear_registry()
