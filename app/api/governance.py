# SPDX-License-Identifier: Apache-2.0
"""Compatibility shim; import from adaad.api.governance instead."""

from app._deprecated_shim import warn_legacy_module

warn_legacy_module("app.api.governance", "adaad.api.governance")

from adaad.api.governance import *  # noqa: F401,F403
