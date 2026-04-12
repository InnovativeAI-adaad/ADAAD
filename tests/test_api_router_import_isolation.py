from __future__ import annotations

import builtins
import importlib
import sys
import types

import pytest


ROUTER_MODULES = [
    "app.api.compliance",
    "app.api.audit_exports",
    "app.api.mutation_control",
    "app.api.streams",
]


@pytest.mark.parametrize("module_name", ROUTER_MODULES)
def test_router_module_imports_without_server_bootstrap(module_name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        if name == "server" or name.startswith("server."):
            raise AssertionError(f"router import attempted forbidden server bootstrap: {name}")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    sse_module = types.ModuleType("sse_starlette.sse")
    sse_module.EventSourceResponse = object
    monkeypatch.setitem(sys.modules, "sse_starlette", types.ModuleType("sse_starlette"))
    monkeypatch.setitem(sys.modules, "sse_starlette.sse", sse_module)
    sys.modules.pop(module_name, None)

    imported = importlib.import_module(module_name)

    assert imported is not None
