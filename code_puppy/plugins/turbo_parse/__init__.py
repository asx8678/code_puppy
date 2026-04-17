"""Turbo Parse Plugin — High-performance parsing via native modules.

bd-86: Native acceleration layer removed. This plugin now always returns
False for availability checks, as the native backends have been removed.
"""

__version__ = "0.1.0"

# Plugin exports (for future expansion)
__all__ = [
    "__version__",
    "is_turbo_parse_available",
]


def is_turbo_parse_available() -> bool:
    """Check if parsing capability is available.

    bd-86: Native acceleration layer removed, always returns False.
    Parsing operations now use pure Python implementations.

    Returns:
        False - native parsing is not available.
    """
    return False
