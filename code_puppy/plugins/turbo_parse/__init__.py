"""Turbo Parse Plugin — High-performance parsing via Rust module.

Provides fast code parsing capabilities using the turbo_parse Rust module.
Falls back to pure Python implementations when Rust module is unavailable.
"""

__version__ = "0.1.0"

# Plugin exports (for future expansion)
__all__ = [
    "__version__",
    "is_turbo_parse_available",
]


def is_turbo_parse_available() -> bool:
    """Check if the turbo_parse Rust module is available.
    
    Returns:
        True if the Rust module is installed and functional, False otherwise.
    """
    try:
        import turbo_parse
        return True
    except ImportError:
        return False
