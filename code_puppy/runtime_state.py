"""Runtime state management for Code Puppy.

This module is a thin Python wrapper that routes all runtime state operations
to the Elixir RuntimeState GenServer. State is stored exclusively in Elixir
with no Python-side caching.

## State Managed

- **Autosave session ID**: Runtime-only session identifier (per-process)
- **Session model name**: Session-local model name cached after first read from config
- **Session start time**: When the current session began

## Migration Note

This module has been migrated from a dual-path implementation (Elixir-first
with Python fallback) to a pure thin wrapper that routes exclusively to
Elixir. The public API remains unchanged for backward compatibility.
"""

import os
import threading
from typing import Any

from code_puppy.elixir_transport import ElixirTransportError

# opt-in degraded mode lock for thread-safe degraded-mode state access
_DEGRADED_STATE_LOCK = threading.Lock()


def _degraded() -> bool:
    # Check env var directly instead of using a cached constant
    return os.environ.get("PUP_ALLOW_ELIXIR_DEGRADED") == "1"

# =============================================================================
# Backward Compatibility Stubs
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
    try:
        transport = _get_transport()
        result = transport._send_request("runtime_get_autosave_id", {})
        return result["autosave_id"]
    except (ElixirTransportError, OSError, BrokenPipeError, ConnectionError, TimeoutError):
        if _degraded():
            with _DEGRADED_STATE_LOCK:
                global _CURRENT_AUTOSAVE_ID
                if _CURRENT_AUTOSAVE_ID is None:
                    from datetime import datetime

                    _CURRENT_AUTOSAVE_ID = datetime.now().strftime("%Y%m%d_%H%M%S")
                return _CURRENT_AUTOSAVE_ID
        raise


def rotate_autosave_id() -> str:
    """Force a new autosave session ID and return it."""
    try:
        transport = _get_transport()
        result = transport._send_request("runtime_rotate_autosave_id", {})
        return result["autosave_id"]
    except (ElixirTransportError, OSError, BrokenPipeError, ConnectionError, TimeoutError) as exc:
        if _degraded():
            import logging
            logging.getLogger(__name__).warning(
                "Elixir transport unavailable during rotate_autosave_id; "
                "using degraded Python-local ID (PUP_ALLOW_ELIXIR_DEGRADED=1): %s",
                exc,
            )
            with _DEGRADED_STATE_LOCK:
                global _CURRENT_AUTOSAVE_ID
                from datetime import datetime
                _CURRENT_AUTOSAVE_ID = datetime.now().strftime("%Y%m%d_%H%M%S")
                return _CURRENT_AUTOSAVE_ID
        raise


def get_current_autosave_session_name() -> str:
    """Return the full session name used for autosaves (no file extension)."""
    try:
        transport = _get_transport()
        result = transport._send_request("runtime_get_autosave_session_name", {})
        return result["session_name"]
    except (ElixirTransportError, OSError, BrokenPipeError, ConnectionError, TimeoutError) as exc:
        if _degraded():
            import logging
            from datetime import datetime
            logging.getLogger(__name__).warning(
                "Elixir transport unavailable during get_autosave_session_name; "
                "using degraded Python-local session name: %s",
                exc,
            )
            with _DEGRADED_STATE_LOCK:
                return "auto_session_%s" % (
                    _CURRENT_AUTOSAVE_ID or datetime.now().strftime("%Y%m%d_%H%M%S")
                )
        raise


def set_current_autosave_from_session_name(session_name: str) -> str:
    """Set the current autosave ID based on a full session name.

    Accepts names like 'auto_session_YYYYMMDD_HHMMSS' and extracts the ID part.
    Returns the ID that was set.
    """
    try:
        transport = _get_transport()
        result = transport._send_request(
            "runtime_set_autosave_from_session", {"session_name": session_name}
        )
        return result["autosave_id"]
    except (ElixirTransportError, OSError, BrokenPipeError, ConnectionError, TimeoutError) as exc:
        if _degraded():
            import logging
            logging.getLogger(__name__).warning(
                "Elixir transport unavailable during set_autosave_from_session; "
                "using degraded Python-local storage: %s",
                exc,
            )
            with _DEGRADED_STATE_LOCK:
                global _CURRENT_AUTOSAVE_ID
                if session_name.startswith("auto_session_"):
                    _CURRENT_AUTOSAVE_ID = session_name[len("auto_session_"):]
                else:
                    _CURRENT_AUTOSAVE_ID = session_name
                return _CURRENT_AUTOSAVE_ID
        raise


def reset_autosave_id() -> None:
    """Reset the autosave ID to None (primarily for testing)."""
    try:
        transport = _get_transport()
        transport._send_request("runtime_reset_autosave_id", {})
    except (ElixirTransportError, OSError, BrokenPipeError, ConnectionError, TimeoutError) as exc:
        if _degraded():
            import logging
            logging.getLogger(__name__).warning(
                "Elixir transport unavailable during reset_autosave_id; "
                "resetting Python-local ID: %s",
                exc,
            )
            with _DEGRADED_STATE_LOCK:
                global _CURRENT_AUTOSAVE_ID
                _CURRENT_AUTOSAVE_ID = None
            return
        raise


# =============================================================================
# Session Model State
# =============================================================================


def get_session_model() -> str | None:
    """Get the cached session model name, or None if not yet initialized."""
    try:
        transport = _get_transport()
        result = transport._send_request("runtime_get_session_model", {})
        return result["session_model"]
    except (ElixirTransportError, OSError, BrokenPipeError, ConnectionError, TimeoutError):
        if _degraded():
            import logging

            logging.getLogger(__name__).warning(
                "Elixir transport unavailable; using degraded Python-local "
                "session_model (PUP_ALLOW_ELIXIR_DEGRADED=1)"
            )
            with _DEGRADED_STATE_LOCK:
                return _SESSION_MODEL
        raise


def set_session_model(model: str | None) -> None:
    """Set the session-local model name."""
    try:
        transport = _get_transport()
        transport._send_request("runtime_set_session_model", {"model": model})
    except (ElixirTransportError, OSError, BrokenPipeError, ConnectionError, TimeoutError):
        if _degraded():
            with _DEGRADED_STATE_LOCK:
                global _SESSION_MODEL
                _SESSION_MODEL = model
            return
        raise


def reset_session_model() -> None:
    """Reset the session-local model cache (primarily for testing)."""
    try:
        transport = _get_transport()
        transport._send_request("runtime_reset_session_model", {})
    except (ElixirTransportError, OSError, BrokenPipeError, ConnectionError, TimeoutError) as exc:
        if _degraded():
            import logging
            logging.getLogger(__name__).warning(
                "Elixir transport unavailable during reset_session_model; "
                "resetting Python-local session model: %s",
                exc,
            )
            with _DEGRADED_STATE_LOCK:
                global _SESSION_MODEL
                _SESSION_MODEL = None
            return
        raise


# =============================================================================
# Utility Functions
# =============================================================================


def finalize_autosave_session() -> str:
    """Persist the current autosave snapshot and rotate to a fresh session.

    This function is best-effort and never raises: autosave rotation is not
    a critical-path operation, so any failure (transport dead, disk full,
    etc.) falls back to a timestamp-based ID so the caller can keep running.
    """
    from code_puppy.config import auto_save_session_if_enabled

    try:
        auto_save_session_if_enabled()
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "auto_save_session_if_enabled failed during finalize: %s", exc
        )

    try:
        return rotate_autosave_id()
    except Exception as exc:
        import logging
        from datetime import datetime
        logging.getLogger(__name__).warning(
            "rotate_autosave_id failed during finalize; using timestamp fallback: %s", exc
        )
        return datetime.now().strftime("%Y%m%d_%H%M%S_fallback")


def get_state() -> dict[str, Any]:
    """Get full runtime state for introspection.

    Returns a dictionary containing:
    - autosave_id: The current autosave session ID
    - session_model: The cached session model name
    - session_start_time: ISO8601 timestamp of when the state was queried
    """
    try:
        transport = _get_transport()
        result = transport._send_request("runtime_get_state", {})
        return {
            "autosave_id": result["autosave_id"],
            "session_model": result["session_model"],
            "session_start_time": result["session_start_time"],
        }
    except (ElixirTransportError, OSError, BrokenPipeError, ConnectionError, TimeoutError) as exc:
        if _degraded():
            import logging
            from datetime import datetime
            logging.getLogger(__name__).warning(
                "Elixir transport unavailable during get_state; "
                "returning degraded Python-local state: %s",
                exc,
            )
            with _DEGRADED_STATE_LOCK:
                return {
                    "autosave_id": _CURRENT_AUTOSAVE_ID or datetime.now().strftime("%Y%m%d_%H%M%S"),
                    "session_model": _SESSION_MODEL,
                    "session_start_time": datetime.now().isoformat() + "Z",
                }
        raise


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
