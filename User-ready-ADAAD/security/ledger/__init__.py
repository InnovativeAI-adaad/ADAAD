# SPDX-License-Identifier: Apache-2.0
"""
Ledger package for Cryovant lineage tracking.
"""

from pathlib import Path

LEDGER_ROOT = Path(__file__).resolve().parent
ELEMENT_ID = "Water"

__all__ = ["LEDGER_ROOT", "ELEMENT_ID"]
