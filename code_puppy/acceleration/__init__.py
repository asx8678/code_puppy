"""Unified acceleration bridge - Hybrid Zig/Rust approach.

Architecture:
- Rust (PyO3): puppy_core, turbo_parse (performance critical)
- Zig (cffi): turbo_ops (file I/O, less FFI sensitive)

This hybrid approach leverages:
- Rust's superior FFI performance via PyO3 for hot paths
- Zig's simpler build/cross-compilation for file operations

Configuration:
    Use environment variables to override backends:
    - PUP_ACCEL_PUPPY_CORE=rust|zig|python
    - PUP_ACCEL_TURBO_PARSE=rust|zig|python
    - PUP_ACCEL_TURBO_OPS=rust|zig|python
"""

import os
from typing import Any

from code_puppy.config import get_acceleration_config

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

# Import Zig acceleration for turbo_ops
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


def get_backend_info() -> dict[str, Any]:
    """Return detailed backend information including config and runtime status.

    Returns:
        Dict with backend status for each module (puppy_core, turbo_parse, turbo_ops)
    """
    config = get_acceleration_config()

    # Determine effective backends based on availability + config
    rust_status = get_rust_status()
    turbo_parse_status = get_turbo_parse_status()

    return {
        "puppy_core": {
            "configured": config["puppy_core"],
            "available": RUST_AVAILABLE,
            "active": RUST_AVAILABLE and is_rust_enabled(),
            "status": "active" if (RUST_AVAILABLE and is_rust_enabled()) else "disabled",
        },
        "turbo_parse": {
            "configured": config["turbo_parse"],
            "available": TURBO_PARSE_AVAILABLE,
            "active": turbo_parse_status.get("active", False),
            "status": "active" if turbo_parse_status.get("active", False) else "disabled",
        },
        "turbo_ops": {
            "configured": config["turbo_ops"],
            "available": ZIG_AVAILABLE,
            "active": ZIG_AVAILABLE and config["turbo_ops"] == "zig",
            "status": "active" if ZIG_AVAILABLE else "disabled",
        },
    }


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


# File operations - use Zig if configured and available
def list_files(directory: str = ".", recursive: bool = True) -> dict[str, Any]:
    """List files using configured backend (Zig preferred, then Python)."""
    config = get_acceleration_config()

    # Check if turbo_ops should use Zig
    if config.get("turbo_ops") == "zig" and ZIG_AVAILABLE and zig_list_files:
        return zig_list_files(directory, recursive)

    # Fallback: use Python implementation
    from code_puppy.tools import list_files as python_list_files
    return python_list_files(directory, recursive)


def grep(pattern: str, directory: str = ".") -> dict[str, Any]:
    """Search files using configured backend (Zig preferred, then Python)."""
    config = get_acceleration_config()

    # Check if turbo_ops should use Zig
    if config.get("turbo_ops") == "zig" and ZIG_AVAILABLE and zig_grep:
        return zig_grep(pattern, directory)

    # Fallback: use Python implementation
    from code_puppy.tools import grep as python_grep
    return python_grep(pattern, directory)


__all__ = [
    # Backend info
    "RUST_AVAILABLE",
    "ZIG_AVAILABLE",
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
    # Zig-backed (turbo_ops)
    "list_files",
    "grep",
]
