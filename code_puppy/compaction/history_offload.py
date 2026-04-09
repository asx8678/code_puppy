"""History offload: append evicted messages to a timestamped log file.

When summarization compacts old messages, this helper preserves them by appending
to a per-session log file with section headers. Useful for debugging and audit.

Opt-in via config key `summarization_history_offload_enabled` (default: False).
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_offload_lock = threading.Lock()

DEFAULT_ARCHIVE_DIR = Path.home() / ".code_puppy" / "history"


def _sanitize_session_id(session_id: str) -> str:
    """Sanitize session ID for use as a filename.

    Replaces unsafe characters with underscores.
    """
    # Characters that are safe in filenames (cross-platform)
    safe_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.")
    return "".join(c if c in safe_chars else "_" for c in session_id)


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
) -> Path | None:
    """Append evicted messages to the session's history archive.

    Args:
        messages: The messages being evicted (soon-to-be-replaced by a summary).
        session_id: Unique ID for this session (used as the filename stem).
        archive_dir: Directory for history archives. Defaults to ~/.code_puppy/history/
        compact_reason: Reason for this compaction (appears in the header).

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
