# SPDX-License-Identifier: Apache-2.0

"""Smoke test to ensure server module imports in minimal environments."""

from __future__ import annotations

import importlib


def test_server_module_imports() -> None:
    module = importlib.import_module("server")
    assert hasattr(module, "app")
