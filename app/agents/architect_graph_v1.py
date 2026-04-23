# SPDX-License-Identifier: Apache-2.0
"""Compatibility shim; import from adaad.agents.architect_graph_v1 instead."""

from app._deprecated_shim import warn_legacy_module

warn_legacy_module("app.agents.architect_graph_v1", "adaad.agents.architect_graph_v1")

from adaad.agents.architect_graph_v1 import *  # noqa: F401,F403
