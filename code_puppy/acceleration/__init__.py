"""Unified acceleration bridge - Hybrid Zig/Rust approach.

Architecture:
- Rust (PyO3): puppy_core, turbo_parse (performance critical)
- Zig (cffi): turbo_ops (file I/O, less FFI sensitive)

This hybrid approach leverages:
- Rust's superior FFI performance via PyO3 for hot paths
- Zig's simpler build/cross-compilation for file operations
"""

from typing import Any

# Import Rust acceleration (primary)
from code_puppy._core_bridge import (
    RUST_AVAILABLE,
    is_rust_enabled,
    process_messages_batch,
    prune_and_filter,
    truncation_indices,
    split_for_summarization,
    serialize_session,
    deserialize_session,
    MessageBatchHandle,
)

# Import Zig acceleration for file ops
try:
    from code_puppy.zig_bridge import (
        ZIG_AVAILABLE,
        list_files as zig_list_files,
        grep as zig_grep,
    )
except ImportError:
    ZIG_AVAILABLE = False
    zig_list_files = None  # type: ignore[assignment]
    zig_grep = None  # type: ignore[assignment]


# Determine best backend for each operation
def get_backend_info() -> dict[str, str]:
    """Return which backend is used for each operation."""
    return {
        "puppy_core": "rust" if RUST_AVAILABLE else "python",
        "turbo_parse": "rust" if RUST_AVAILABLE else "python",
        "turbo_ops": "zig" if ZIG_AVAILABLE else "python",
    }


# File operations - prefer Zig
def list_files(directory: str = ".", recursive: bool = True) -> dict[str, Any]:
    """List files using Zig backend if available."""
    if ZIG_AVAILABLE and zig_list_files:
        return zig_list_files(directory, recursive)
    # Fallback to Python implementation
    return {"success": False, "error": "No acceleration available"}


def grep(pattern: str, directory: str = ".") -> dict[str, Any]:
    """Search files using Zig backend if available."""
    if ZIG_AVAILABLE and zig_grep:
        return zig_grep(pattern, directory)
    return {"success": False, "error": "No acceleration available"}


__all__ = [
    # Backend info
    "RUST_AVAILABLE",
    "ZIG_AVAILABLE",
    "get_backend_info",
    # Rust-backed (puppy_core)
    "process_messages_batch",
    "prune_and_filter",
    "truncation_indices",
    "split_for_summarization",
    "serialize_session",
    "deserialize_session",
    "MessageBatchHandle",
    # Zig-backed (turbo_ops)
    "list_files",
    "grep",
]
