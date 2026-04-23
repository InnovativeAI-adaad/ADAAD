# SPDX-License-Identifier: Apache-2.0
"""Compatibility shim; import from adaad.api.schemas.governance instead."""

from app._deprecated_shim import warn_legacy_module

warn_legacy_module("app.api.schemas.governance", "adaad.api.schemas.governance")

from adaad.api.schemas.governance import *  # noqa: F401,F403
