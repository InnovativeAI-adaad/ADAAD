# SPDX-License-Identifier: Apache-2.0
"""Compatibility shim for root directory helpers.

TODO: remove after all imports migrate to ``adaad.core.root``.
"""

from adaad.core.root import ROOT_DIR, get_root_dir

__all__ = ["ROOT_DIR", "get_root_dir"]
