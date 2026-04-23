# SPDX-License-Identifier: Apache-2.0
"""Shared helper for app.* compatibility shims."""

from __future__ import annotations

import warnings


def warn_legacy_module(legacy_module: str, canonical_module: str) -> None:
    warnings.warn(
        (
            f"{legacy_module} is deprecated and will be removed after the shim sunset cycle; "
            f"import {canonical_module} instead."
        ),
        DeprecationWarning,
        stacklevel=2,
    )
