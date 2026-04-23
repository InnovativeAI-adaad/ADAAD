# SPDX-License-Identifier: Apache-2.0
"""Compatibility shim; import from adaad.agents.test_subject.__init__ instead."""

from app._deprecated_shim import warn_legacy_module

warn_legacy_module("app.agents.test_subject", "adaad.agents.test_subject.__init__")

from adaad.agents.test_subject import *  # noqa: F401,F403
