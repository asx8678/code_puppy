"""History offload: append evicted messages to a timestamped log file.

When summarization compacts old messages, this helper preserves them by appending
to a per-session log file with section headers. Useful for debugging and audit.

Opt-in via config key `summarization_history_offload_enabled` (default: False).
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_offload_lock = threading.Lock()

DEFAULT_ARCHIVE_DIR = Path.home() / ".code_puppy" / "history"
DEFAULT_MAX_ARCHIVE_SIZE_MB = 100  # Default max archive size before rotation


def _sanitize_session_id(session_id: str | None) -> str:
    """Sanitize session ID for use as a filename.

    Replaces unsafe characters with underscores. Handles None safely
    by returning 'unknown'.

    Args:
        session_id: Session ID string, or None.

    Returns:
        Sanitized session ID safe for use as a filename.
    """
    # Handle None safely
    if session_id is None:
        return "unknown"

    # Characters that are safe in filenames (cross-platform)
    safe_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.")
    return "".join(c if c in safe_chars else "_" for c in session_id)


def _get_archive_size_mb(archive_path: Path) -> float:
    """Get the size of an archive file in megabytes.

    Args:
        archive_path: Path to the archive file.

    Returns:
        Size in megabytes, or 0.0 if file doesn't exist.
    """
    if not archive_path.exists():
        return 0.0
    return archive_path.stat().st_size / (1024 * 1024)


def _rotate_archive(archive_path: Path) -> None:
    """Rotate an archive file by renaming it with a timestamp suffix.

    The existing archive is renamed to {name}.{timestamp}.history.md,
    effectively starting a new archive file.

    Args:
        archive_path: Path to the archive file to rotate.
    """
    if not archive_path.exists():
        return

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    rotated_name = archive_path.stem.replace(".history", f"_{timestamp}.history") + archive_path.suffix
    rotated_path = archive_path.parent / rotated_name

    try:
        archive_path.rename(rotated_path)
        logger.debug("Rotated archive %s to %s", archive_path, rotated_path)
    except OSError as e:
        logger.warning("Failed to rotate archive %s: %s", archive_path, e)


def _enforce_archive_size_limit(
    archive_path: Path,
    max_size_mb: float,
) -> None:
    """Enforce archive size limit by rotating if necessary.

    If the archive exceeds the size limit, it is rotated to make room.

    Args:
        archive_path: Path to the archive file.
        max_size_mb: Maximum size in megabytes before rotation.
    """
    current_size = _get_archive_size_mb(archive_path)
    if current_size > max_size_mb:
        logger.debug(
            "Archive %s size (%.2f MB) exceeds limit (%.2f MB), rotating",
            archive_path,
            current_size,
            max_size_mb,
        )
        _rotate_archive(archive_path)


def _serialize_message(msg: Any) -> str:
    """Best-effort human-readable serialization of a single message."""
    try:
        # Try to extract role and content from common message types
        role = None
        content = None

        # pydantic-ai ModelRequest / ModelResponse
        if hasattr(msg, "kind"):
            role = msg.kind
        if hasattr(msg, "parts"):
            # Summarize parts - don't dump huge content
            parts = msg.parts
            if parts:
                part_summaries = []
                for p in parts:
                    if hasattr(p, "part_kind"):
                        pk = p.part_kind
                        if pk == "text":
                            txt = getattr(p, "content", "") or ""
                            part_summaries.append(f"[text: {len(txt)} chars]")
                        elif pk == "tool-call":
                            tn = getattr(p, "tool_name", "unknown")
                            part_summaries.append(f"[tool-call: {tn}]")
                        elif pk == "tool-return":
                            tn = getattr(p, "tool_name", "unknown")
                            part_summaries.append(f"[tool-return: {tn}]")
                        else:
                            part_summaries.append(f"[{pk}]")
                    else:
                        part_summaries.append(str(p)[:100])
                content = ", ".join(part_summaries)

        # Fallback: try common attributes
        if role is None:
            role = getattr(msg, "role", None)
        if content is None:
            content = getattr(msg, "content", None)

        # Final fallback
        if role is None:
            role = type(msg).__name__
        if content is None:
            # Truncate repr to avoid massive dumps
            r = repr(msg)
            content = r[:500] + "..." if len(r) > 500 else r

        return f"**{role}**: {content}"
    except Exception as e:
        return f"**unreadable**: {e}"


def offload_evicted_messages(
    messages: Sequence[Any],
    *,
    session_id: str,
    archive_dir: Path | None = None,
    compact_reason: str = "summarization",
    max_archive_size_mb: float = DEFAULT_MAX_ARCHIVE_SIZE_MB,
) -> Path | None:
    """Append evicted messages to the session's history archive.

    Args:
        messages: The messages being evicted (soon-to-be-replaced by a summary).
        session_id: Unique ID for this session (used as the filename stem).
        archive_dir: Directory for history archives. Defaults to ~/.code_puppy/history/
        compact_reason: Reason for this compaction (appears in the header).
        max_archive_size_mb: Maximum archive size in MB before rotation (default: 100).

    Returns:
        Path to the archive file that was appended to, or None on failure.
    """
    if not messages:
        return None

    archive_dir = archive_dir or DEFAULT_ARCHIVE_DIR

    try:
        safe_session_id = _sanitize_session_id(session_id)
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path = archive_dir / f"{safe_session_id}.history.md"

        timestamp = datetime.now(timezone.utc).isoformat()
        header = f"\n\n## Compacted at {timestamp} (reason: {compact_reason})\n\n"

        # Serialize messages
        body_lines = []
        for msg in messages:
            body_lines.append(_serialize_message(msg))
            body_lines.append("")
        body = "\n".join(body_lines)

        with _offload_lock:
            # Enforce size limit before writing (rotate if necessary)
            _enforce_archive_size_limit(archive_path, max_archive_size_mb)

            with archive_path.open("a", encoding="utf-8") as f:
                f.write(header)
                f.write(body)

        logger.debug("Offloaded %d messages to %s", len(messages), archive_path)
        return archive_path
    except OSError as e:
        # Don't crash summarization because of a filesystem issue
        logger.warning("Failed to offload history to %s: %s", archive_dir, e)
        return None
    except Exception as e:
        logger.warning("Unexpected error during history offload: %s", e)
        return None
