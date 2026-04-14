"""Unified acceleration bridge - Rust native approach.

Architecture:
- Rust (PyO3): puppy_core, turbo_parse, turbo_ops (all via Rust)

This approach leverages Rust's superior FFI performance via PyO3 for all
acceleration paths, with turbo_executor handling batch file operations.

Configuration:
    Use environment variables to override backends:
    - PUP_ACCEL_PUPPY_CORE=rust|python
    - PUP_ACCEL_TURBO_PARSE=rust|python
    - PUP_ACCEL_TURBO_OPS=rust|python

bd-61: Now delegates to NativeBackend for unified acceleration access.
"""

from typing import Any

from code_puppy.native_backend import NativeBackend

# Import Rust acceleration (primary for puppy_core, turbo_parse)
from code_puppy._core_bridge import (
    RUST_AVAILABLE,
    is_rust_enabled,
    get_rust_status,
    process_messages_batch,
    prune_and_filter,
    truncation_indices,
    split_for_summarization,
    serialize_session,
    deserialize_session,
    MessageBatchHandle,
)

# Import turbo_parse bridge
try:
    from code_puppy.turbo_parse_bridge import (
        TURBO_PARSE_AVAILABLE,
        get_turbo_parse_status,
    )
except ImportError:
    TURBO_PARSE_AVAILABLE = False
    get_turbo_parse_status = lambda: {"installed": False, "enabled": False, "active": False}  # type: ignore[assignment]


def get_backend_info() -> dict[str, Any]:
    """Return detailed backend information including config and runtime status.

    Returns:
        Dict with backend status for each module (puppy_core, turbo_parse, turbo_ops)
    """
    # Delegate to NativeBackend for unified status
    native_status = NativeBackend.get_status()

    # Maintain backward compatible output format
    result: dict[str, Any] = {}
    for cap_name, info in native_status.items():
        result[cap_name] = {
            "configured": info.configured,
            "available": info.available,
            "active": info.active,
            "status": info.status,
        }

    return result


def get_backend_summary() -> dict[str, str]:
    """Return a simple backend summary for display.

    Returns:
        Dict mapping backend names to simple status strings
    """
    info = get_backend_info()
    return {
        name: f"{data['configured']} ({data['status']})"
        for name, data in info.items()
    }


# File operations - delegated to NativeBackend for unified access
def list_files(directory: str = ".", recursive: bool = True) -> dict[str, Any]:
    """List files using NativeBackend with fallback.

    Note: For accelerated file operations, use the turbo_executor agent
    which handles batch operations via Rust.
    """
    return NativeBackend.list_files(directory, recursive)


def grep(pattern: str, directory: str = ".") -> dict[str, Any]:
    """Search files using NativeBackend with fallback.

    Note: For accelerated file operations, use the turbo_executor agent
    which handles batch operations via Rust.
    """
    return NativeBackend.grep(pattern, directory)


__all__ = [
    # Backend info
    "RUST_AVAILABLE",
    "TURBO_PARSE_AVAILABLE",
    "get_backend_info",
    "get_backend_summary",
    # Rust-backed (puppy_core)
    "process_messages_batch",
    "prune_and_filter",
    "truncation_indices",
    "split_for_summarization",
    "serialize_session",
    "deserialize_session",
    "MessageBatchHandle",
    # Python fallback (turbo_ops via turbo_executor)
    "list_files",
    "grep",
]
