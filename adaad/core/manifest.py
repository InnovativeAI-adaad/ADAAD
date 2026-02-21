# SPDX-License-Identifier: Apache-2.0
"""Canonical tool manifest builder."""

from __future__ import annotations


def build_manifest(identity: dict, description: str, params_schema: dict) -> dict:
    """Construct a standard ADAAD tool manifest envelope."""
    return {
        "identity": identity,
        "description": description,
        "params_schema": params_schema,
    }
