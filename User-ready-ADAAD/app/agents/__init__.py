# SPDX-License-Identifier: Apache-2.0
"""
Agent registry and helpers.
"""

from pathlib import Path

AGENTS_ROOT = Path(__file__).resolve().parent

__all__ = ["AGENTS_ROOT"]
