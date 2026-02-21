# SPDX-License-Identifier: Apache-2.0
"""Canonical tool contract template for ADAAD tools."""

from __future__ import annotations

from typing import Any, Dict

TOOL_ID: str = "template.tool"
VERSION: str = "1.0.0"


def get_tool_manifest() -> Dict[str, Any]:
    return {
        "tool_id": TOOL_ID,
        "version": VERSION,
        "description": "Template tool module that satisfies the ADAAD tool contract.",
    }


def run_tool(params: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "ok": True,
        "tool_id": TOOL_ID,
        "echo": dict(params),
    }
