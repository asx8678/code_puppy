"""Age filtering utilities for the clean command plugin.

Provides duration parsing and age-based file filtering.
"""

import re
import time
from pathlib import Path


def _parse_duration(s: str) -> int:
    """Parse a duration string into seconds.

    Supports formats like:
        - 7d, 30d (days)
        - 24h (hours)
        - 1w (weeks = 7 days)
        - 12m (minutes)
        - 30s (seconds)

    Args:
        s: Duration string with number + unit suffix.

    Returns:
        Number of seconds as an integer.

    Raises:
        ValueError: If the format is invalid or unit is not recognized.
    """
    s = s.strip().lower()
    match = re.match(r"^(\d+)\s*([dhwms])$", s)
    if not match:
        raise ValueError(
            f"Invalid duration format: '{s}'. Use formats like: 7d, 24h, 1w, 12m, 30s"
        )
    num, unit = match.groups()
    value = int(num)
    multipliers = {
        "s": 1,
        "m": 60,
        "h": 3600,
        "d": 86400,
        "w": 604800,  # 7 days
    }
    return value * multipliers[unit]


def _human_age(seconds: int) -> str:
    """Format *seconds* as a human-friendly age string."""
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    if seconds < 604800:
        return f"{seconds // 86400}d"
    return f"{seconds // 604800}w"


def _is_older_than(path: Path, max_age_seconds: int) -> bool:
    """Check if a file is older than the given age threshold.

    Args:
        path: Path to the file to check.
        max_age_seconds: Maximum age in seconds. Files older than this
            (based on mtime) will return True.

    Returns:
        True if the file exists and is older than max_age_seconds.
    """
    try:
        mtime = path.stat().st_mtime
        return (time.time() - mtime) > max_age_seconds
    except OSError:
        return False


def _parse_args(parts: list[str]) -> tuple[list[str], bool, int | None]:
    """Parse command arguments.

    Args:
        parts: List of argument strings (after the command name).

    Returns:
        Tuple of (remaining_args, dry_run, max_age_seconds).

    Raises:
        ValueError: If --older-than is missing its duration argument
        or the duration is invalid.
    """
    dry_run = False
    max_age_seconds: int | None = None
    args: list[str] = []

    i = 0
    while i < len(parts):
        arg = parts[i]
        if arg == "--dry-run":
            dry_run = True
        elif arg == "--older-than":
            if i + 1 >= len(parts):
                raise ValueError(
                    "--older-than requires a duration argument (e.g., 7d, 24h)"
                )
            max_age_seconds = _parse_duration(parts[i + 1])
            i += 1
        else:
            args.append(arg)
        i += 1

    return args, dry_run, max_age_seconds
