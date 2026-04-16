"""Turbo Parse Plugin — High-performance parsing via Rust module.

Provides fast code parsing capabilities using the turbo_parse Rust module.
Falls back to pure Python implementations when Rust module is unavailable.

bd-93: Phase 4 - Now routes through NativeBackend for unified Elixir-first routing.
"""

__version__ = "0.1.0"

# Plugin exports (for future expansion)
__all__ = [
    "__version__",
    "is_turbo_parse_available",
]


def is_turbo_parse_available() -> bool:
    """Check if parsing capability is available through NativeBackend.

    bd-93: Phase 4 - Now delegates to NativeBackend for unified capability checking.

    Returns:
        True if parse capability is available (via Rust, Elixir, or Python).
    """
    from code_puppy.native_backend import NativeBackend

    return NativeBackend.is_available(NativeBackend.Capabilities.PARSE)
