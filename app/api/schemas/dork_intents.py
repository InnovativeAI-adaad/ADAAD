# SPDX-License-Identifier: Apache-2.0
"""Compatibility shim; import from adaad.api.schemas.dork_intents instead."""

from app._deprecated_shim import warn_legacy_module

warn_legacy_module("app.api.schemas.dork_intents", "adaad.api.schemas.dork_intents")

from adaad.api.schemas.dork_intents import *  # noqa: F401,F403
