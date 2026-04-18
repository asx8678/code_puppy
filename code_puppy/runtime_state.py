"""Runtime state management for Code Puppy.

This module contains mutable runtime state that changes during execution.
It is separate from the immutable configuration (code_puppy.config) which
is loaded from persistent storage at startup and should not be mutated at runtime.

Runtime State vs Config:
- Runtime state: In-memory only, changes during execution, per-process/session
- Config: Loaded from puppy.cfg, persistent across sessions, immutable at runtime

## Elixir Routing (bd-117)

This module supports optional Elixir-first routing for all public functions.
When the Elixir transport is available, calls are routed to the Elixir
RuntimeState handlers; otherwise, the pure-Python fallback is used.

Routing priority: Elixir → Python

The following Elixir RPC methods are used:
- ``runtime_get_autosave_id`` - Get current autosave ID
- ``runtime_get_autosave_session_name`` - Get full session name
- ``runtime_rotate_autosave_id`` - Force new autosave ID
- ``runtime_set_autosave_from_session`` - Set ID from session name
- ``runtime_reset_autosave_id`` - Reset autosave ID to None
- ``runtime_get_session_model`` - Get cached session model
- ``runtime_set_session_model`` - Set session model
- ``runtime_reset_session_model`` - Reset session model cache
- ``runtime_get_state`` - Get full runtime state for introspection
"""

import datetime
from typing import Any

# =============================================================================
# Runtime-Only State Variables
# =============================================================================

#: Runtime-only autosave session ID (per-process). Changes when session rotates.
_CURRENT_AUTOSAVE_ID: str | None = None

#: Session-local model name (initialized from file on first access, then cached).
# This prevents model changes in other terminals from affecting this running instance.
_SESSION_MODEL: str | None = None


_ElixirTransportFailure = object()

# =============================================================================
# Elixir Routing Helpers (bd-117)
# =============================================================================


def _get_transport() -> "ElixirTransport":  # type: ignore # noqa: F821
    """Get the shared transport singleton from elixir_transport_helpers."""
    from code_puppy.elixir_transport_helpers import get_transport

    return get_transport()


def _try_elixir_get_autosave_id() -> tuple[bool, str | None]:
    """Try to get autosave ID from Elixir.

    Returns:
        (True, autosave_id) on success, (False, None) on transport failure.
    """
    try:
        transport = _get_transport()
        result = transport._send_request("runtime_get_autosave_id", {})
        return True, result.get("autosave_id")
    except Exception:
        return False, None  # Fall back to Python


def _try_elixir_get_autosave_session_name() -> tuple[bool, str | None]:
    """Try to get autosave session name from Elixir.

    Returns:
        (True, session_name) on success, (False, None) on transport failure.
    """
    try:
        transport = _get_transport()
        result = transport._send_request("runtime_get_autosave_session_name", {})
        return True, result.get("session_name")
    except Exception:
        return False, None  # Fall back to Python


def _try_elixir_rotate_autosave_id() -> str | None:
    """Try to rotate autosave ID via Elixir, return None on failure."""
    try:
        transport = _get_transport()
        result = transport._send_request("runtime_rotate_autosave_id", {})
        autosave_id = result.get("autosave_id")
        # Update Python cache to stay in sync
        global _CURRENT_AUTOSAVE_ID
        _CURRENT_AUTOSAVE_ID = autosave_id
        return autosave_id
    except Exception:
        return None  # Fall back to Python


def _try_elixir_set_autosave_from_session(session_name: str) -> str | None:
    """Try to set autosave ID from session name via Elixir, return None on failure."""
    try:
        transport = _get_transport()
        result = transport._send_request(
            "runtime_set_autosave_from_session", {"session_name": session_name}
        )
        autosave_id = result.get("autosave_id")
        # Update Python cache to stay in sync
        global _CURRENT_AUTOSAVE_ID
        _CURRENT_AUTOSAVE_ID = autosave_id
        return autosave_id
    except Exception:
        return None  # Fall back to Python


def _try_elixir_reset_autosave_id() -> bool | None:
    """Try to reset autosave ID via Elixir, return None on failure."""
    try:
        transport = _get_transport()
        transport._send_request("runtime_reset_autosave_id", {})
        # Update Python cache to stay in sync
        global _CURRENT_AUTOSAVE_ID
        _CURRENT_AUTOSAVE_ID = None
        return True
    except Exception:
        return None  # Fall back to Python


def _try_elixir_get_session_model() -> tuple[bool, str | None]:
    """Try to get session model from Elixir.

    Returns:
        (True, model) on success (including model=None), (False, None) on transport failure.
    """
    try:
        transport = _get_transport()
        result = transport._send_request("runtime_get_session_model", {})
        return True, result.get("session_model")
    except Exception:
        return False, None  # Fall back to Python


def _try_elixir_set_session_model(model: str | None) -> bool | None:
    """Try to set session model via Elixir, return None on failure."""
    try:
        transport = _get_transport()
        transport._send_request("runtime_set_session_model", {"model": model})
        # Update Python cache to stay in sync
        global _SESSION_MODEL
        _SESSION_MODEL = model
        return True
    except Exception:
        return None  # Fall back to Python


def _try_elixir_reset_session_model() -> bool | None:
    """Try to reset session model via Elixir, return None on failure."""
    try:
        transport = _get_transport()
        transport._send_request("runtime_reset_session_model", {})
        # Update Python cache to stay in sync
        global _SESSION_MODEL
        _SESSION_MODEL = None
        return True
    except Exception:
        return None  # Fall back to Python


def _try_elixir_get_state() -> tuple[bool, dict[str, Any] | None]:
    """Try to get full runtime state from Elixir.

    Returns:
        (True, state_dict) on success, (False, None) on transport failure.
    """
    try:
        transport = _get_transport()
        result = transport._send_request("runtime_get_state", {})
        return True, {
            "autosave_id": result.get("autosave_id"),
            "session_model": result.get("session_model"),
            "session_start_time": result.get("session_start_time"),
        }
    except Exception:
        return False, None  # Fall back to Python


# =============================================================================
# Autosave Session State
# =============================================================================


def get_current_autosave_id() -> str:
    """Get or create the current autosave session ID for this process.

    This is runtime-only state - it is not persisted to config and is
    unique to each process/session.

    Routing priority (bd-117): Elixir → Python
    """
    global _CURRENT_AUTOSAVE_ID
    # Try Elixir first
    elixir_success, elixir_value = _try_elixir_get_autosave_id()
    if elixir_success:
        # Sync Python cache so fallback uses last known good state
        _CURRENT_AUTOSAVE_ID = elixir_value
        return elixir_value

    # Fall back to Python
    if not _CURRENT_AUTOSAVE_ID:
        # Use a full timestamp so tests and UX can predict the name if needed
        _CURRENT_AUTOSAVE_ID = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return _CURRENT_AUTOSAVE_ID


def rotate_autosave_id() -> str:
    """Force a new autosave session ID and return it.

    This creates a fresh session ID, effectively starting a new session
    while keeping the same process running.

    Routing priority (bd-117): Elixir → Python
    """
    # Try Elixir first
    elixir_result = _try_elixir_rotate_autosave_id()
    if elixir_result is not None:
        return elixir_result

    # Fall back to Python
    global _CURRENT_AUTOSAVE_ID
    _CURRENT_AUTOSAVE_ID = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return _CURRENT_AUTOSAVE_ID


def get_current_autosave_session_name() -> str:
    """Return the full session name used for autosaves (no file extension).

    Routing priority (bd-117): Elixir → Python
    """
    # Try Elixir first
    elixir_success, elixir_value = _try_elixir_get_autosave_session_name()
    if elixir_success:
        return elixir_value

    # Fall back to Python
    return f"auto_session_{get_current_autosave_id()}"


def set_current_autosave_from_session_name(session_name: str) -> str:
    """Set the current autosave ID based on a full session name.

    Accepts names like 'auto_session_YYYYMMDD_HHMMSS' and extracts the ID part.
    Returns the ID that was set.

    Routing priority (bd-117): Elixir → Python
    """
    # Try Elixir first
    elixir_result = _try_elixir_set_autosave_from_session(session_name)
    if elixir_result is not None:
        return elixir_result

    # Fall back to Python
    global _CURRENT_AUTOSAVE_ID
    prefix = "auto_session_"
    if session_name.startswith(prefix):
        _CURRENT_AUTOSAVE_ID = session_name[len(prefix) :]
    else:
        _CURRENT_AUTOSAVE_ID = session_name
    return _CURRENT_AUTOSAVE_ID


def reset_autosave_id() -> None:
    """Reset the autosave ID to None.

    This is primarily for testing purposes. In normal operation, the autosave
    ID is set once and only changes via rotate_autosave_id().

    Routing priority (bd-117): Elixir → Python
    """
    # Try Elixir first
    elixir_result = _try_elixir_reset_autosave_id()
    if elixir_result is not None:
        return

    # Fall back to Python
    global _CURRENT_AUTOSAVE_ID
    _CURRENT_AUTOSAVE_ID = None


# =============================================================================
# Session Model State
# =============================================================================


def get_session_model() -> str | None:
    """Get the cached session model name.

    Returns:
        The cached model name, or None if not yet initialized.

    Routing priority (bd-117): Elixir → Python
    """
    global _SESSION_MODEL
    # Try Elixir first
    elixir_success, elixir_value = _try_elixir_get_session_model()
    if elixir_success:
        # Sync Python cache so fallback uses last known good state
        _SESSION_MODEL = elixir_value
        return elixir_value

    # Fall back to Python
    return _SESSION_MODEL


def set_session_model(model: str | None) -> None:
    """Set the session-local model name.

    This updates only the runtime cache. To persist the model to config,
    use the model setter in code_puppy.config which calls this internally
    after writing to the config file.

    Args:
        model: The model name to cache, or None to clear the cache.

    Routing priority (bd-117): Elixir → Python
    """
    # Try Elixir first
    elixir_result = _try_elixir_set_session_model(model)
    if elixir_result is not None:
        return

    # Fall back to Python
    global _SESSION_MODEL
    _SESSION_MODEL = model


def reset_session_model() -> None:
    """Reset the session-local model cache.

    This is primarily for testing purposes. In normal operation, the session
    model is set once at startup and only changes via set_session_model().

    Routing priority (bd-117): Elixir → Python
    """
    # Try Elixir first
    elixir_result = _try_elixir_reset_session_model()
    if elixir_result is not None:
        return

    # Fall back to Python
    global _SESSION_MODEL
    _SESSION_MODEL = None


# =============================================================================
# Utility Functions
# =============================================================================


def finalize_autosave_session() -> str:
    """Persist the current autosave snapshot and rotate to a fresh session.

    This is a convenience function that combines auto-saving with session rotation.

    Note: This function imports from config internally to avoid circular dependencies.
    If you need to customize the save behavior, use rotate_autosave_id() directly
    and handle persistence separately.
    """
    # Import here to avoid circular import at module level
    from code_puppy.config import auto_save_session_if_enabled

    auto_save_session_if_enabled()
    return rotate_autosave_id()


def get_state() -> dict[str, Any]:
    """Get full runtime state for introspection.

    Returns a dictionary containing:
    - autosave_id: The current autosave session ID
    - session_model: The cached session model name
    - session_start_time: ISO8601 timestamp of when the state was queried

    Routing priority (bd-117): Elixir → Python

    Returns:
        Dict with runtime state information
    """
    # Try Elixir first
    elixir_success, elixir_value = _try_elixir_get_state()
    if elixir_success and elixir_value is not None:
        # Sync Python cache so fallback uses last known good state
        global _CURRENT_AUTOSAVE_ID, _SESSION_MODEL
        _CURRENT_AUTOSAVE_ID = elixir_value.get("autosave_id")
        _SESSION_MODEL = elixir_value.get("session_model")
        return elixir_value

    # Fall back to Python
    return {
        "autosave_id": get_current_autosave_id(),
        "session_model": get_session_model(),
        "session_start_time": datetime.datetime.now().isoformat(),
    }


# =============================================================================
# Diagnostics
# =============================================================================


def is_using_elixir() -> bool:
    """Check if the Elixir backend is currently connected.

    Returns:
        True if Elixir transport is available, False otherwise.
    """
    try:
        transport = _get_transport()
        # A simple ping will tell us if the transport is working
        transport._send_request("ping", {})
        return True
    except Exception:
        return False
