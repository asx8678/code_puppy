"""Runtime state management for Code Puppy.

This module is a thin Python wrapper that routes all runtime state operations
to the Elixir RuntimeState GenServer. State is stored exclusively in Elixir
with no Python-side caching.

## State Managed

- **Autosave session ID**: Runtime-only session identifier (per-process)
- **Session model name**: Session-local model name cached after first read from config
- **Session start time**: When the current session began

## Migration Note (bd-133)

This module has been migrated from a dual-path implementation (Elixir-first
with Python fallback) to a pure thin wrapper that routes exclusively to
Elixir. The public API remains unchanged for backward compatibility.
"""

from typing import Any

# =============================================================================
# Backward Compatibility Stubs (bd-133)
# =============================================================================
# These module variables are retained for backward compatibility with tests
# that reference them. With pure Elixir routing, state is stored exclusively
# in the Elixir GenServer, not in these Python module-level variables.
# =============================================================================

#: DEPRECATED: Module-level variable retained for test compatibility.
# State is now stored exclusively in Elixir GenServer.
_CURRENT_AUTOSAVE_ID: str | None = None

#: DEPRECATED: Module-level variable retained for test compatibility.
# State is now stored exclusively in Elixir GenServer.
_SESSION_MODEL: str | None = None


def _get_transport():
    """Get the shared transport singleton from elixir_transport_helpers."""
    from code_puppy.elixir_transport_helpers import get_transport
    return get_transport()


# =============================================================================
# Autosave Session State
# =============================================================================


def get_current_autosave_id() -> str:
    """Get or create the current autosave session ID for this process."""
    transport = _get_transport()
    result = transport._send_request("runtime_get_autosave_id", {})
    return result["autosave_id"]


def rotate_autosave_id() -> str:
    """Force a new autosave session ID and return it."""
    transport = _get_transport()
    result = transport._send_request("runtime_rotate_autosave_id", {})
    return result["autosave_id"]


def get_current_autosave_session_name() -> str:
    """Return the full session name used for autosaves (no file extension)."""
    transport = _get_transport()
    result = transport._send_request("runtime_get_autosave_session_name", {})
    return result["session_name"]


def set_current_autosave_from_session_name(session_name: str) -> str:
    """Set the current autosave ID based on a full session name.

    Accepts names like 'auto_session_YYYYMMDD_HHMMSS' and extracts the ID part.
    Returns the ID that was set.
    """
    transport = _get_transport()
    result = transport._send_request(
        "runtime_set_autosave_from_session", {"session_name": session_name}
    )
    return result["autosave_id"]


def reset_autosave_id() -> None:
    """Reset the autosave ID to None (primarily for testing)."""
    transport = _get_transport()
    transport._send_request("runtime_reset_autosave_id", {})


# =============================================================================
# Session Model State
# =============================================================================


def get_session_model() -> str | None:
    """Get the cached session model name, or None if not yet initialized."""
    transport = _get_transport()
    result = transport._send_request("runtime_get_session_model", {})
    return result["session_model"]


def set_session_model(model: str | None) -> None:
    """Set the session-local model name."""
    transport = _get_transport()
    transport._send_request("runtime_set_session_model", {"model": model})


def reset_session_model() -> None:
    """Reset the session-local model cache (primarily for testing)."""
    transport = _get_transport()
    transport._send_request("runtime_reset_session_model", {})


# =============================================================================
# Utility Functions
# =============================================================================


def finalize_autosave_session() -> str:
    """Persist the current autosave snapshot and rotate to a fresh session."""
    from code_puppy.config import auto_save_session_if_enabled

    auto_save_session_if_enabled()
    return rotate_autosave_id()


def get_state() -> dict[str, Any]:
    """Get full runtime state for introspection.

    Returns a dictionary containing:
    - autosave_id: The current autosave session ID
    - session_model: The cached session model name
    - session_start_time: ISO8601 timestamp of when the state was queried
    """
    transport = _get_transport()
    result = transport._send_request("runtime_get_state", {})
    return {
        "autosave_id": result["autosave_id"],
        "session_model": result["session_model"],
        "session_start_time": result["session_start_time"],
    }


# =============================================================================
# Diagnostics
# =============================================================================


def is_using_elixir() -> bool:
    """Check if the Elixir backend is currently connected."""
    try:
        transport = _get_transport()
        transport._send_request("ping", {})
        return True
    except Exception:
        return False
