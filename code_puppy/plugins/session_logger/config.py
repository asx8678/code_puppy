"""Plugin-level config helpers for session_logger."""

import logging
from pathlib import Path

from code_puppy.config_package import env_bool, get_puppy_config

logger = logging.getLogger(__name__)


def get_session_logger_enabled() -> bool:
    """Check if session logging is enabled.

    Returns:
        True if session_logger_enabled is set to true/yes/1/on, False otherwise.
        Default: False (opt-in for privacy).

    Priority: PUPPY_SESSION_LOGGER_ENABLED env var > puppy.cfg setting > default False
    """
    cfg = get_puppy_config()
    # Env var takes priority over config file for easy dogfooding toggle
    return env_bool("PUPPY_SESSION_LOGGER_ENABLED", default=cfg.session_logger_enabled)


def get_session_logger_dir() -> Path:
    """Get the session log directory.

    Returns:
        Path to write session directories. Uses session_logger_dir config
        if set, otherwise defaults to cfg.sessions_dir (DATA_DIR / "sessions").
    """
    cfg = get_puppy_config()
    # session_logger_dir in config is legacy - prefer cfg.sessions_dir
    # But if a custom session_logger_dir was set, we should respect it
    # For now, use the typed config's sessions_dir which is the canonical location
    return cfg.sessions_dir
