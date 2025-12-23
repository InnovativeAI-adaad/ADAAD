"""
Security package for Cryovant controls.
"""

from pathlib import Path

SECURITY_ROOT = Path(__file__).resolve().parent

__all__ = ["SECURITY_ROOT"]
