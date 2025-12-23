"""
Monotonic capability registry.
"""

"""
Legacy compatibility wrapper for the capability graph registry.
"""

from runtime.capability_graph import get_capabilities, register_capability

# The public API is preserved for backward compatibility. New code should import
# runtime.capability_graph instead of this module.
