# SPDX-License-Identifier: Apache-2.0
"""Compatibility shim; import from adaad.api.schemas instead."""

from app._deprecated_shim import warn_legacy_module

warn_legacy_module("app.api.schemas", "adaad.api.schemas")

from adaad.api.schemas import *  # noqa: F401,F403
