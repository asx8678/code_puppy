"""Runtime state management for Code Puppy.

This module contains mutable runtime state that changes during execution.
It is separate from the immutable configuration (code_puppy.config) which
is loaded from persistent storage at startup and should not be mutated at runtime.

Runtime State vs Config:
- Runtime state: In-memory only, changes during execution, per-process/session
- Config: Loaded from puppy.cfg, persistent across sessions, immutable at runtime
"""

import datetime
from typing import Optional

# =============================================================================
# Runtime-Only State Variables
# =============================================================================

#: Runtime-only autosave session ID (per-process). Changes when session rotates.
_CURRENT_AUTOSAVE_ID: Optional[str] = None

#: Session-local model name (initialized from file on first access, then cached).
# This prevents model changes in other terminals from affecting this running instance.
_SESSION_MODEL: Optional[str] = None


# =============================================================================
# Autosave Session State
# =============================================================================

def get_current_autosave_id() -> str:
    """Get or create the current autosave session ID for this process.

    This is runtime-only state - it is not persisted to config and is
    unique to each process/session.
    """
    global _CURRENT_AUTOSAVE_ID
    if not _CURRENT_AUTOSAVE_ID:
        # Use a full timestamp so tests and UX can predict the name if needed
        _CURRENT_AUTOSAVE_ID = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return _CURRENT_AUTOSAVE_ID


def rotate_autosave_id() -> str:
    """Force a new autosave session ID and return it.

    This creates a fresh session ID, effectively starting a new session
    while keeping the same process running.
    """
    global _CURRENT_AUTOSAVE_ID
    _CURRENT_AUTOSAVE_ID = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return _CURRENT_AUTOSAVE_ID


def get_current_autosave_session_name() -> str:
    """Return the full session name used for autosaves (no file extension)."""
    return f"auto_session_{get_current_autosave_id()}"


def set_current_autosave_from_session_name(session_name: str) -> str:
    """Set the current autosave ID based on a full session name.

    Accepts names like 'auto_session_YYYYMMDD_HHMMSS' and extracts the ID part.
    Returns the ID that was set.
    """
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
    """
    global _CURRENT_AUTOSAVE_ID
    _CURRENT_AUTOSAVE_ID = None


# =============================================================================
# Session Model State
# =============================================================================

def get_session_model() -> Optional[str]:
    """Get the cached session model name.

    Returns:
        The cached model name, or None if not yet initialized.
    """
    global _SESSION_MODEL
    return _SESSION_MODEL


def set_session_model(model: Optional[str]) -> None:
    """Set the session-local model name.

    This updates only the runtime cache. To persist the model to config,
    use the model setter in code_puppy.config which calls this internally
    after writing to the config file.

    Args:
        model: The model name to cache, or None to clear the cache.
    """
    global _SESSION_MODEL
    _SESSION_MODEL = model


def reset_session_model() -> None:
    """Reset the session-local model cache.

    This is primarily for testing purposes. In normal operation, the session
    model is set once at startup and only changes via set_session_model().
    """
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
