"""Error logger plugin – hooks internal errors into the file-based error log.

Connects the callback system to ``code_puppy.error_logging`` so that every
internal error is persisted for later review.  Also exposes a ``/errors``
slash command to inspect, tail, or clear the log.
"""

import os

from code_puppy.callbacks import register_callback
from code_puppy.error_logging import get_log_file_path, log_error, log_error_message

# ---------------------------------------------------------------------------
# 1. agent_exception hook
# ---------------------------------------------------------------------------


def _on_agent_exception(exception, *args, **kwargs):
    """Persist any exception surfaced through the agent_exception callback."""
    context_parts = ["agent_exception callback"]
    if args:
        context_parts.append(f"args={args!r}")
    if kwargs:
        context_parts.append(f"kwargs={kwargs!r}")
    log_error(exception, context=" | ".join(context_parts))


register_callback("agent_exception", _on_agent_exception)

# ---------------------------------------------------------------------------
# 2. agent_run_end hook – log when a run finishes with an error
# ---------------------------------------------------------------------------


def _on_agent_run_end(
    agent_name,
    model_name,
    session_id=None,
    success=True,
    error=None,
    response_text=None,
    metadata=None,
):
    if success or error is None:
        return

    context = (
        f"agent_run_end: agent={agent_name}, model={model_name}, "
        f"session_id={session_id}"
    )
    if isinstance(error, Exception):
        log_error(error, context=context)
    else:
        log_error_message(str(error), context=context)


register_callback("agent_run_end", _on_agent_run_end)

# ---------------------------------------------------------------------------
# 3. /errors slash command
# ---------------------------------------------------------------------------

_SEPARATOR = "=" * 80


def _read_last_entries(n=5):
    """Return the last *n* error entries from the log file."""
    log_path = get_log_file_path()
    if not os.path.isfile(log_path):
        return []

    try:
        with open(log_path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return []

    # Entries are delimited by separator lines (===...===)
    raw_blocks = content.split(f"\n{_SEPARATOR}\n")
    # Each "entry" is the block that starts with a separator and ends with one.
    # After splitting, non-empty blocks are individual entries.
    entries = [b.strip() for b in raw_blocks if b.strip()]
    return entries[-n:]


def _handle_errors_command(command, name):
    """Handle the /errors family of commands."""
    if name != "errors":
        return None  # not ours

    from code_puppy.messaging import emit_info, emit_success, emit_warning

    parts = command.strip().split()
    # parts[0] is "/errors"
    sub = parts[1] if len(parts) > 1 else "path"

    # --- /errors  or  /errors path ---
    if sub == "path":
        log_path = get_log_file_path()
        emit_info(f"📄 Error log: {log_path}")
        if os.path.isfile(log_path):
            size = os.path.getsize(log_path)
            if size < 1024:
                human = f"{size} B"
            elif size < 1024 * 1024:
                human = f"{size / 1024:.1f} KB"
            else:
                human = f"{size / (1024 * 1024):.1f} MB"
            emit_info(f"   Size: {human}")
        else:
            emit_success("   ✨ No error log yet – clean slate!")
        return True

    # --- /errors tail [N] ---
    if sub == "tail":
        n = 5
        if len(parts) > 2:
            try:
                n = int(parts[2])
            except ValueError:
                pass
        entries = _read_last_entries(n)
        if not entries:
            emit_success("✨ No errors logged – good puppy!")
            return True
        emit_info(f"📋 Last {len(entries)} error(s):\n")
        for entry in entries:
            emit_warning(entry)
            emit_info("")  # blank line separator
        return True

    # --- /errors clear ---
    if sub == "clear":
        log_path = get_log_file_path()
        if os.path.isfile(log_path):
            try:
                with open(log_path, "w", encoding="utf-8") as f:
                    f.truncate(0)
                emit_success("🧹 Error log cleared!")
            except OSError as exc:
                from code_puppy.messaging import emit_error

                emit_error(f"Failed to clear log: {exc}")
        else:
            emit_success("✨ No error log to clear!")
        return True

    # Unknown sub-command – show help
    emit_info("Usage: /errors [path|tail [N]|clear]")
    return True


register_callback("custom_command", _handle_errors_command)

# ---------------------------------------------------------------------------
# 4. /help entry
# ---------------------------------------------------------------------------


def _errors_help():
    return [("errors", "View/manage error logs (path|tail|clear)")]


register_callback("custom_command_help", _errors_help)
