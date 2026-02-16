# SPDX-License-Identifier: Apache-2.0
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Runtime package providing core utilities for the ADAAD orchestrator.
"""

from pathlib import Path

from runtime.import_guard import install_runtime_import_guard

ELEMENT_ID = "Earth"

# Canonical repository root for governance tooling.
REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_DIR = REPO_ROOT

install_runtime_import_guard()

__all__ = ["ROOT_DIR", "REPO_ROOT", "ELEMENT_ID"]
