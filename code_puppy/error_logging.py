"""Error logging utility for code_puppy.

Logs unexpected errors to XDG_STATE_HOME/code_puppy/logs/ for debugging purposes.
Per XDG spec, logs are "state data" (actions history), not configuration.
Because even good puppies make mistakes sometimes! 🐶
"""

import sys
import traceback
from datetime import datetime
from pathlib import Path

from code_puppy.config import STATE_DIR

# Logs directory within the state directory (per XDG spec, logs are state data)
LOGS_DIR = Path(STATE_DIR) / "logs"
ERROR_LOG_FILE = LOGS_DIR / "errors.log"
MAX_LOG_SIZE = 5 * 1024 * 1024  # 5MB


def _rotate_log_if_needed() -> None:
    """Rotate the error log file if it exceeds MAX_LOG_SIZE."""
    try:
        if (
            ERROR_LOG_FILE.exists()
            and ERROR_LOG_FILE.stat().st_size > MAX_LOG_SIZE
        ):
            rotated = ERROR_LOG_FILE.parent / (ERROR_LOG_FILE.name + ".1")
            ERROR_LOG_FILE.replace(rotated)
    except OSError:
        pass


def _ensure_logs_dir() -> None:
    """Create the logs directory if it doesn't exist (with 0700 perms per XDG spec)."""
    Path(LOGS_DIR).mkdir(parents=True, exist_ok=True, mode=0o700)


def log_error(
    error: Exception,
    context: str | None = None,
    include_traceback: bool = True) -> None:
    """Log an error to the error log file.

    Args:
        error: The exception to log
        context: Optional context string describing where the error occurred
        include_traceback: Whether to include the full traceback (default True)
    """
    try:
        _ensure_logs_dir()
        _rotate_log_if_needed()

        timestamp = datetime.now().isoformat()
        error_type = type(error).__name__
        error_msg = str(error)

        log_entry_parts = [
            f"\n{'=' * 80}",
            f"Timestamp: {timestamp}",
            f"Error Type: {error_type}",
            f"Error Message: {error_msg}",
        ]

        if context:
            log_entry_parts.append(f"Context: {context}")

        if include_traceback:
            tb = traceback.format_exception(type(error), error, error.__traceback__)
            log_entry_parts.append(f"Traceback:\n{''.join(tb)}")

        if hasattr(error, "args") and error.args:
            log_entry_parts.append(f"Args: {error.args}")

        log_entry_parts.append(f"{'=' * 80}\n")

        log_entry = "\n".join(log_entry_parts)

        with open(ERROR_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_entry)

    except Exception as _log_exc:
        # Last-resort: write to stderr so the failure isn't invisible.
        try:
            sys.stderr.write(
                f"[code_puppy] error_logging.log_error() failed: {_log_exc}\n"
            )
        except Exception:
            pass  # truly nothing we can do


def log_error_message(
    message: str,
    context: str | None = None) -> None:
    """Log a simple error message without an exception object.

    Args:
        message: The error message to log
        context: Optional context string describing where the error occurred
    """
    try:
        _ensure_logs_dir()
        _rotate_log_if_needed()

        timestamp = datetime.now().isoformat()

        log_entry_parts = [
            f"\n{'=' * 80}",
            f"Timestamp: {timestamp}",
            f"Message: {message}",
        ]

        if context:
            log_entry_parts.append(f"Context: {context}")

        log_entry_parts.append(f"{'=' * 80}\n")

        log_entry = "\n".join(log_entry_parts)

        with open(ERROR_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_entry)

    except Exception as _log_exc:
        # Last-resort: write to stderr so the failure isn't invisible.
        try:
            sys.stderr.write(
                f"[code_puppy] error_logging.log_error_message() failed: {_log_exc}\n"
            )
        except Exception:
            pass  # truly nothing we can do


def get_log_file_path() -> Path:
    """Return the path to the error log file."""
    return ERROR_LOG_FILE


def get_logs_dir() -> Path:
    """Return the path to the logs directory."""
    return LOGS_DIR
