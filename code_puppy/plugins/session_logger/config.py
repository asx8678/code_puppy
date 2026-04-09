"""Plugin-level config helpers for session_logger."""

import logging
from pathlib import Path

from code_puppy.config import get_value, DATA_DIR

logger = logging.getLogger(__name__)


def get_session_logger_enabled() -> bool:
    """Check if session logging is enabled.

    Returns:
        True if session_logger_enabled is set to true/yes/1/on, False otherwise.
        Default: False (opt-in for privacy).
    """
    cfg_val = get_value("session_logger_enabled")
    if cfg_val is None:
        return False  # Default OFF - opt-in for privacy
    return str(cfg_val).strip().lower() in {"1", "true", "yes", "on"}


def get_session_logger_dir() -> Path:
    """Get the session log directory.

    Returns:
        Path to write session directories. Uses session_logger_dir config
        if set, otherwise defaults to DATA_DIR / "sessions".
    """
    cfg_val = get_value("session_logger_dir")
    if cfg_val:
        # Expand ~ and environment variables
        expanded = Path(cfg_val).expanduser()
        try:
            # Resolve to absolute, but don't require path to exist
            return (
                expanded.expanduser().resolve()
                if expanded.is_absolute()
                else expanded.expanduser()
            )
        except (OSError, ValueError) as e:
            logger.warning(f"Invalid session_logger_dir '{cfg_val}': {e}")
    # Default to DATA_DIR / "sessions"
    return Path(DATA_DIR) / "sessions"
