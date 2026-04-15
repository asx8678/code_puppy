"""Unified acceleration bridge — delegates to NativeBackend.

bd-70: Simplified to route all queries through NativeBackend instead of
importing directly from _core_bridge and turbo_parse_bridge.
bd-99: Updated for Elixir-first architecture. File operations route through
Elixir control plane by default. turbo_ops references remain for backward
compatibility but operations are handled via Elixir FileOps.

Configuration:
    Use environment variables to override backends:
    - PUP_ACCEL_PUPPY_CORE=rust|python
    - PUP_ACCEL_TURBO_PARSE=rust|python
    - PUP_ACCEL_TURBO_OPS=elixir|rust|python  # Now routes via Elixir

    Or use the Python API:
    - NativeBackend.set_backend_preference("elixir_first")  # Default
    - NativeBackend.set_backend_preference("rust_first")
    - NativeBackend.set_backend_preference("python_only")
"""

from typing import Any

# Import core types and re-export message processing functions (bd-70)
from code_puppy._core_bridge import (
    MessageBatchHandle,
    create_message_batch,
    deserialize_session,
    process_messages_batch,
    prune_and_filter,
    serialize_session,
    split_for_summarization,
    truncation_indices,
)
from code_puppy.native_backend import NativeBackend

# bd-70: Derive availability flags from NativeBackend
# bd-99: Add ELIXIR_AVAILABLE for Elixir-first architecture
RUST_AVAILABLE = NativeBackend.is_active(NativeBackend.Capabilities.MESSAGE_CORE)
TURBO_PARSE_AVAILABLE = NativeBackend.is_active(NativeBackend.Capabilities.PARSE)
ELIXIR_AVAILABLE = NativeBackend.is_elixir_connected()


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
    """Return a simple backend summary for display.  # bd-99"""
    info = get_backend_info()
    summary = {
        name: f"{data['configured']} ({data['status']})" for name, data in info.items()
    }
    # bd-99: Add Elixir status to summary
    summary["elixir"] = "connected" if ELIXIR_AVAILABLE else "disconnected"
    return summary


def list_files(directory: str = ".", recursive: bool = True) -> dict[str, Any]:
    """List files using NativeBackend with fallback."""
    return NativeBackend.list_files(directory, recursive)


def grep(pattern: str, directory: str = ".") -> dict[str, Any]:
    """Search files using NativeBackend with fallback."""
    return NativeBackend.grep(pattern, directory)


__all__ = [
    # bd-99: Backend availability flags (Elixir-first architecture)
    "RUST_AVAILABLE",
    "TURBO_PARSE_AVAILABLE",
    "ELIXIR_AVAILABLE",
    # Backend introspection
    "get_backend_info",
    "get_backend_summary",
    "is_rust_enabled",
    "get_rust_status",
    "get_turbo_parse_status",
    # Message core operations (Rust-backed)
    "process_messages_batch",
    "prune_and_filter",
    "truncation_indices",
    "split_for_summarization",
    "serialize_session",
    "deserialize_session",
    "MessageBatchHandle",
    "create_message_batch",
    # File operations (Elixir-first, with fallbacks)
    "list_files",
    "grep",
]
