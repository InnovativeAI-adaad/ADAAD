# SPDX-License-Identifier: Apache-2.0
"""Shared logging configuration for ADAAD modules."""

from __future__ import annotations

import logging


def configure_logging(level: int = logging.INFO) -> None:
    """Configure deterministic logging format once per process."""
    root = logging.getLogger()
    if root.handlers:
        return
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
