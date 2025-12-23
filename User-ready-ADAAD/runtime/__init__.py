"""
Runtime package providing core utilities for the ADAAD orchestrator.
"""

from pathlib import Path

ELEMENT_ID = "Earth"

ROOT_DIR = Path(__file__).resolve().parent.parent

__all__ = ["ROOT_DIR", "ELEMENT_ID"]
