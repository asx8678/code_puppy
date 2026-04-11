"""Register callbacks for the Git Auto Commit (GAC) spike.

This module registers:
- `custom_command` handler for `/commit` slash command
- `custom_command_help` to add entry to `/help` menu

The `/commit` command proves that we can bridge sync callback execution
to async shell execution through the security boundary.
"""

from __future__ import annotations

import logging
from code_puppy.callbacks import register_callback
from code_puppy.messaging import emit_info

from .shell_bridge import execute_git_command_sync

logger = logging.getLogger(__name__)


def _commit_help() -> list[tuple[str, str]]:
    """Return help text for the /commit command.

    Returns:
        List of (command_name, description) tuples for the /help menu.
    """
    return [
        (
            "commit",
            "Git auto-commit (GAC spike) - Execute git status through security boundary",
        )
    ]


def _handle_commit_command(command: str, name: str) -> bool | str | None:
    """Handle the /commit slash command.

    This handler is invoked via the sync `custom_command` callback mechanism,
    but it bridges to async shell execution through the security boundary.

    The bridging works via `run_async_sync()` which executes the async
    `execute_git_command()` function in a background thread with its own
    event loop, avoiding deadlock issues when called from sync contexts.

    Args:
        command: The full command string (e.g., "/commit" or "/commit status")
        name: The command name (always "commit" for this handler)

    Returns:
        True if successful, or a descriptive error string if failed
    """
    if name != "commit":
        # Not our command - let other handlers try
        return None  # type: ignore[return-value]

    logger.info(f"GAC spike: Executing /{command}")
    emit_info("🐕 GAC spike: Bridging sync callback to async shell execution...")

    # Parse subcommand (default to "status" for this spike)
    parts = command.split()
    subcommand = parts[1] if len(parts) > 1 else "status"

    # Validate subcommand for security (whitelist approach)
    allowed_subcommands = {"status", "branch", "log", "diff", "show"}
    if subcommand not in allowed_subcommands:
        error_msg = f"❌ Unknown subcommand: {subcommand}. Allowed: {', '.join(sorted(allowed_subcommands))}"
        logger.warning(error_msg)
        return error_msg

    # Build the git command
    git_command = f"git {subcommand}"

    # Execute through the security boundary bridge
    # This is the key proof point: sync callback → async shell execution
    emit_info(f"🔒 Checking security boundary for: {git_command}")

    try:
        result = execute_git_command_sync(git_command)

        if result.get("blocked"):
            # Command was blocked by security
            reason = result.get("reason", "Unknown security reason")
            error_msg = f"🛑 Command blocked by security: {reason}"
            logger.warning(f"GAC spike: {error_msg}")
            emit_info(error_msg)
            return error_msg

        if not result.get("success"):
            # Command execution failed
            error = result.get("error", "Unknown error")
            error_msg = f"❌ Command failed: {error}"
            logger.error(f"GAC spike: {error_msg}")
            emit_info(error_msg)
            return error_msg

        # Success!
        output = result.get("output", "")
        logger.info(f"GAC spike: Successfully executed {git_command}")
        emit_info(f"✅ Successfully executed: {git_command}")

        # Show output preview (truncated for large outputs)
        if output:
            lines = output.strip().split("\n")
            preview_lines = lines[:20]  # Show first 20 lines
            preview = "\n".join(preview_lines)
            if len(lines) > 20:
                preview += f"\n... ({len(lines) - 20} more lines)"
            emit_info(f"Output:\n{preview}")

        return True

    except Exception as e:
        error_msg = f"💥 Bridge execution failed: {type(e).__name__}: {e}"
        logger.exception(f"GAC spike: {error_msg}")
        emit_info(error_msg)
        return error_msg


# =============================================================================
# Register callbacks
# =============================================================================

register_callback("custom_command_help", _commit_help)
register_callback("custom_command", _handle_commit_command)

logger.debug("Git Auto Commit (GAC) spike callbacks registered")


__all__ = [
    "_commit_help",
    "_handle_commit_command",
]
