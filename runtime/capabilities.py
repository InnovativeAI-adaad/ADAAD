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
Legacy compatibility wrapper for the capability graph registry.

New code should import runtime.capability_graph.
"""

from runtime import capability_graph

get_capabilities = capability_graph.get_capabilities
register_capability = capability_graph.register_capability
dispatch_capability = capability_graph.dispatch_capability
list_capabilities = capability_graph.list_capabilities

__all__ = ["dispatch_capability", "get_capabilities", "list_capabilities", "register_capability"]
