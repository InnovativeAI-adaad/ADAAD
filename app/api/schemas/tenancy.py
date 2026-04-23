# SPDX-License-Identifier: Apache-2.0
"""Compatibility shim; import from adaad.api.schemas.tenancy instead."""

from app._deprecated_shim import warn_legacy_module

warn_legacy_module("app.api.schemas.tenancy", "adaad.api.schemas.tenancy")

from adaad.api.schemas.tenancy import *  # noqa: F401,F403
