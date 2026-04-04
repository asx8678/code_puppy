"""Disk usage checking and utilities for the clean command."""

from pathlib import Path

# Disk usage warning thresholds (bytes)
_WARNING_THRESHOLD_MB = 100 * 1024 * 1024  # 100 MB
_CRITICAL_THRESHOLD_MB = 500 * 1024 * 1024  # 500 MB


def _human_size(nbytes: int) -> str:
    """Format *nbytes* as a human-friendly string."""
    if nbytes < 1024:
        return f"{nbytes} B"
    for unit in ("KB", "MB", "GB"):
        nbytes /= 1024.0
        if nbytes < 1024.0 or unit == "GB":
            return f"{nbytes:.1f} {unit}"
    return f"{nbytes:.1f} GB"  # pragma: no cover


def _dir_stats(path: Path) -> tuple[int, int]:
    """Return ``(file_count, total_bytes)`` for a directory tree."""
    if not path.is_dir():
        return 0, 0
    count = 0
    total = 0
    try:
        for item in path.rglob("*"):
            if item.is_file():
                try:
                    total += item.stat().st_size
                    count += 1
                except OSError:
                    pass
    except OSError:
        pass
    return count, total


def _file_stats(path: Path) -> tuple[int, int]:
    """Return ``(1, size)`` if file exists, else ``(0, 0)``."""
    if not path.is_file():
        return 0, 0
    try:
        return 1, path.stat().st_size
    except OSError:
        return 0, 0


def _check_disk_usage(path: Path) -> tuple[int, str | None]:
    """Check disk usage for a path and return warning if thresholds exceeded.

    Args:
        path: The path to check (file or directory)

    Returns:
        Tuple of (bytes_used, warning_message_or_none).
        Warning is shown for > 100MB, critical warning for > 500MB.
    """
    if path.is_dir():
        count, total = _dir_stats(path)
    elif path.is_file():
        count, total = _file_stats(path)
    else:
        return 0, None

    if total == 0:
        return 0, None

    warning = None
    if total > _CRITICAL_THRESHOLD_MB:
        warning = f"🔴 CRITICAL: {_human_size(total)} - very large!"
    elif total > _WARNING_THRESHOLD_MB:
        warning = f"🟡 Warning: {_human_size(total)} - consider cleaning"

    return total, warning


def _get_last_modified(path: Path) -> str | None:
    """Get the last modified timestamp for a path as a human-readable string.

    Args:
        path: The path to check

    Returns:
        Human-readable timestamp string, or None if path doesn't exist
    """
    import time

    if not path.exists():
        return None

    try:
        mtime = path.stat().st_mtime
        # Format as relative time if within last 24 hours, else as date
        age_seconds = time.time() - mtime
        if age_seconds < 86400:  # 24 hours
            hours = int(age_seconds / 3600)
            if hours < 1:
                mins = int(age_seconds / 60)
                return f"{mins}m ago"
            return f"{hours}h ago"
        else:
            return time.strftime("%Y-%m-%d", time.localtime(mtime))
    except OSError:
        return None
