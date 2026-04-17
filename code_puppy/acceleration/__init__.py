"""Unified acceleration bridge — delegates to NativeBackend.

bd-70: Simplified to route all queries through NativeBackend instead of
importing directly from _core_bridge and turbo_parse_bridge.
bd-94: Removed turbo_ops - file operations route through Elixir control plane.
bd-13: Removed turbo_parse_bridge dependency; NativeBackend is single routing boundary.
bd-31: Removed turbo_parse_bridge, content_prep_bridge, path_classify_bridge modules.

Configuration:
    Use environment variables to override backends:
    - PUP_ACCEL_PUPPY_CORE=rust|python
    - PUP_ACCEL_TURBO_PARSE=rust|python

    Or use the Python API:
    - NativeBackend.set_backend_preference("elixir_first")  # Default
    - NativeBackend.set_backend_preference("rust_first")
    - NativeBackend.set_backend_preference("python_only")

Backend Routing (bd-13):
    - get_turbo_parse_status() now derives from NativeBackend, not turbo_parse_bridge
    - NativeBackend provides explicit capability routing via get_capability_routing()
"""

import logging
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
from code_puppy.native_backend import BackendPreference, NativeBackend

logger = logging.getLogger(__name__)

# bd-70: Derive availability flags from NativeBackend
# bd-94: Add ELIXIR_AVAILABLE for Elixir-first architecture (turbo_ops removed)
RUST_AVAILABLE = NativeBackend.is_active(NativeBackend.Capabilities.MESSAGE_CORE)
# bd-13-fix-semantics: TURBO_PARSE_AVAILABLE is turbo_parse-specific (Rust backend availability).
# bd-13-partial-fix: Now uses NativeBackend._get_turbo_parse() for turbo_parse-specific check.
# NOTE: This checks if the turbo_parse Rust backend is available, NOT if any parse backend is active.
# Use NativeBackend.is_active(NativeBackend.Capabilities.PARSE) to check if ANY parse backend is active.
TURBO_PARSE_AVAILABLE = NativeBackend._get_turbo_parse().get("available", False)
ELIXIR_AVAILABLE = NativeBackend.is_elixir_connected()


def is_rust_enabled() -> bool:
    """Check if Rust acceleration is active."""
    return NativeBackend.is_message_core_active()


def get_rust_status() -> dict:
    """Return diagnostic info for Rust status."""
    from code_puppy._core_bridge import get_rust_status as _get_rust_status

    return _get_rust_status()


def get_turbo_parse_status() -> dict:
    """Return diagnostic info for turbo_parse.

    bd-13: Uses NativeBackend instead of direct turbo_parse_bridge import.
    bd-13-fix-semantics: Turbo_parse-specific and routing-aware status:
        - installed = turbo_parse Rust backend available (any entrypoint)
        - enabled = turbo_parse is allowed as a candidate (parse enabled, not PYTHON_ONLY)
        - active = actual selected parse backend IS turbo_parse (not just available)
        - will_use = "turbo_parse" only if turbo_parse IS selected, otherwise "disabled"
        - parse_backend = the generic selected parse backend (elixir|turbo_parse|python_fallback)
    bd-13-partial-fix: Uses entrypoint-aware routing (parse_file) for conservative status.
        In partial builds (e.g., parse_source exists but parse_file missing), this ensures
        active=False and will_use="disabled" since the primary parse entrypoint is missing.
    """
    try:
        # bd-13-fix-semantics: Check actual turbo_parse availability (any entrypoint)
        turbo = NativeBackend._get_turbo_parse()
        turbo_available = turbo.get("available", False)

        # bd-13-partial-fix: Use entrypoint-aware routing for conservative status
        # "parse_file" is the primary entrypoint - if it's missing, turbo is not usable
        routing = NativeBackend.get_capability_routing(
            NativeBackend.Capabilities.PARSE, entrypoint="parse_file"
        )
        selected_backend = routing.get(
            "will_use"
        )  # Could be "elixir", "turbo_parse", "python_fallback", or "disabled"

        # Get health and stats only if turbo_parse is relevant
        health = (
            NativeBackend.parse_health_check() if turbo_available else {}
        )
        stats = (
            NativeBackend.parse_stats()
            if turbo_available
            else {"total_parses": 0, "backend": "none"}
        )

        # Determine enabled/active status for turbo_parse specifically
        parse_enabled = NativeBackend.is_enabled(NativeBackend.Capabilities.PARSE)
        is_python_only = (
            NativeBackend.get_backend_preference() == BackendPreference.PYTHON_ONLY
        )

        # bd-13-fix-semantics:
        # - installed: turbo_parse Rust backend is available
        # - enabled: parse capability enabled AND not PYTHON_ONLY (turbo_parse is a candidate)
        # - active: turbo_parse IS the selected backend (not just available)
        turbo_is_enabled = parse_enabled and not is_python_only
        turbo_is_active = turbo_available and selected_backend == "turbo_parse"

        # will_use is turbo_parse-specific: only report "turbo_parse" if it's selected
        # If turbo_parse is not the selected backend, report "disabled"
        will_use = "turbo_parse" if turbo_is_active else "disabled"

        return {
            "installed": turbo_available,
            "enabled": turbo_is_enabled,
            "active": turbo_is_active,
            "will_use": will_use,
            "parse_backend": selected_backend,  # bd-13-fix-semantics: actual selected backend
            "preference": NativeBackend.get_backend_preference().value,
            "version": health.get("version") if turbo_available else None,
            "languages": health.get("languages", [])
            if turbo_available
            else [],
            "cache_available": health.get("cache_available", False)
            if turbo_available
            else False,
            "stats": stats if turbo_available else {"total_parses": 0, "backend": "none"},
            "backend_type": "turbo_parse",
        }
    except Exception as e:
        # bd-13-fix-semantics: Log the error instead of swallowing silently
        logger.debug(f"Error getting turbo_parse status: {e}")
        return {
            "installed": False,
            "enabled": False,
            "active": False,
            "will_use": "disabled",
            "parse_backend": None,
            "error": str(e),
            "backend_type": "turbo_parse",
        }


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
