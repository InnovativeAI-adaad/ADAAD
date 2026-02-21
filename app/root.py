# SPDX-License-Identifier: Apache-2.0
"""Compatibility shim for application root helpers during rollout."""

from adaad.core.root import ROOT_DIR, get_root_dir

__all__ = ["ROOT_DIR", "get_root_dir"]
