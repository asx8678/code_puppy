"""Unified acceleration bridge — delegates to NativeBackend.

bd-70: Simplified to route all queries through NativeBackend instead of
importing directly from _core_bridge and turbo_parse_bridge.

Configuration:
    Use environment variables to override backends:
    - PUP_ACCEL_PUPPY_CORE=rust|python
    - PUP_ACCEL_TURBO_PARSE=rust|python
    - PUP_ACCEL_TURBO_OPS=rust|python
"""

from typing import Any

from code_puppy.native_backend import (
    MessageBatchHandle,
    NativeBackend,
    create_message_batch,
)

# bd-70: Derive availability flags from NativeBackend
RUST_AVAILABLE = NativeBackend.is_active(NativeBackend.Capabilities.MESSAGE_CORE)
TURBO_PARSE_AVAILABLE = NativeBackend.is_active(NativeBackend.Capabilities.PARSE)


def is_rust_enabled() -> bool:
    """Check if Rust acceleration is active."""
    return NativeBackend.is_message_core_active()


def get_rust_status() -> dict:
    """Return diagnostic info for Rust status."""
    from code_puppy._core_bridge import get_rust_status as _get_rust_status
    return _get_rust_status()


def get_turbo_parse_status() -> dict:
    """Return diagnostic info for turbo_parse."""
    try:
        from code_puppy.turbo_parse_bridge import get_turbo_parse_status as _get_status
        return _get_status()
    except ImportError:
        return {"installed": False, "enabled": False, "active": False}


# Re-export Rust-backed functions that _core_bridge provides
# These are used by consumers who import from acceleration
from code_puppy._core_bridge import (
    process_messages_batch,
    prune_and_filter,
    truncation_indices,
    split_for_summarization,
    serialize_session,
    deserialize_session,
)


def get_backend_info() -> dict[str, Any]:
    """Return detailed backend information including config and runtime status."""
    native_status = NativeBackend.get_status()
    return {
        cap_name: {
            "configured": info.configured,
            "available": info.available,
            "active": info.active,
            "status": info.status,
        }
        for cap_name, info in native_status.items()
    }


def get_backend_summary() -> dict[str, str]:
    """Return a simple backend summary for display."""
    info = get_backend_info()
    return {
        name: f"{data['configured']} ({data['status']})"
        for name, data in info.items()
    }


def list_files(directory: str = ".", recursive: bool = True) -> dict[str, Any]:
    """List files using NativeBackend with fallback."""
    return NativeBackend.list_files(directory, recursive)


def grep(pattern: str, directory: str = ".") -> dict[str, Any]:
    """Search files using NativeBackend with fallback."""
    return NativeBackend.grep(pattern, directory)


__all__ = [
    "RUST_AVAILABLE",
    "TURBO_PARSE_AVAILABLE",
    "get_backend_info",
    "get_backend_summary",
    "is_rust_enabled",
    "get_rust_status",
    "get_turbo_parse_status",
    "process_messages_batch",
    "prune_and_filter",
    "truncation_indices",
    "split_for_summarization",
    "serialize_session",
    "deserialize_session",
    "MessageBatchHandle",
    "list_files",
    "grep",
]
