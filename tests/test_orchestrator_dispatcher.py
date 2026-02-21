from __future__ import annotations

import importlib
import time

from adaad.orchestrator import bootstrap as bootstrap_module
from adaad.orchestrator.bootstrap import bootstrap_tool_registry
from adaad.orchestrator.dispatcher import Dispatcher, dispatch
from adaad.orchestrator.registry import HandlerRegistry, clear_registry, register_tool


def teardown_function() -> None:
    clear_registry()
    bootstrap_module._BOOTSTRAPPED = False


def test_dispatch_meta_contains_monotonic_latency() -> None:
    register_tool("test.echo", lambda payload: payload)

    envelope = dispatch("test.echo", {"ok": True})

    assert envelope["result"] == {"ok": True}
    meta = envelope["_dispatch_meta"]
    assert meta["tool"] == "test.echo"
    assert isinstance(meta["started_mono_ns"], int)
    assert isinstance(meta["finished_mono_ns"], int)
    assert isinstance(meta["latency_ns"], int)
    assert meta["finished_mono_ns"] >= meta["started_mono_ns"]
    assert meta["latency_ns"] == meta["finished_mono_ns"] - meta["started_mono_ns"]


def test_dispatch_hot_path_avoids_imports_after_bootstrap(monkeypatch) -> None:
    bootstrap_module._BOOTSTRAPPED = False
    clear_registry()
    bootstrap_tool_registry(tool_specs=(("test.noop", "builtins:len"),))

    monkeypatch.setattr(importlib, "import_module", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("import called during dispatch")))

    envelope = dispatch("test.noop", [1, 2, 3])
    assert envelope["result"] == 3
    assert envelope["_dispatch_meta"]["latency_ns"] >= 0


def test_dispatch_structured_error_envelope_for_unknown_route() -> None:
    clear_registry()
    envelope = dispatch("missing.route", {})
    assert envelope["status"] == "error"
    assert envelope["error"]["code"] == "route_not_found"
    assert envelope["metadata"]["route"] == "missing.route"


def test_dispatcher_class_error_isolation_and_latency_watchdog() -> None:
    def slow_handler(_payload):
        time.sleep(0.055)
        return {"ok": True}

    dispatcher = Dispatcher(HandlerRegistry.preload({"slow": slow_handler}))
    response = dispatcher.dispatch("slow", None)

    assert response["ok"] is True
    assert response["metadata"]["route"] == "slow"
    assert response["metadata"]["within_target"] is False
    assert response["metadata"]["warning"] == "latency_budget_exceeded"
