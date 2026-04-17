"""Fast Puppy Plugin — Native acceleration management.

bd-86: Native acceleration layer removed. This plugin now only reports
the status of native backends as unavailable.
"""

import logging

from code_puppy.callbacks import register_callback

logger = logging.getLogger(__name__)


def _on_startup():
    """Initialize Fast Puppy on startup.

    bd-86: Reports that native acceleration has been removed.
    """
    logger.info("🐍 Fast Puppy: Native acceleration layer removed (bd-86)")


def _handle_fast_puppy_command(args: list[str]) -> str:
    """Handle /fast_puppy command.

    bd-86: Returns message that acceleration layer has been removed.
    """
    if not args:
        return (
            "Fast Puppy Status:\n"
            "  Native acceleration layer removed (bd-86)\n"
            "  All operations use pure Python implementations\n"
            "  Elixir bridge: unavailable\n"
            "  Rust crates: unavailable\n"
            "\nCommands (now disabled):\n"
            "  /fast_puppy enable - DISABLED\n"
            "  /fast_puppy disable - DISABLED\n"
            "  /fast_puppy status - shows this message\n"
            "  /fast_puppy profile - DISABLED"
        )

    subcommand = args[0].lower()

    if subcommand == "status":
        return _handle_fast_puppy_command([])
    elif subcommand in ("enable", "disable", "profile"):
        return f"❌ '{subcommand}' command disabled - native acceleration layer removed (bd-86)"
    else:
        return f"Unknown command: {subcommand}. Use: status (other commands disabled)"


def _on_custom_command(command: str, name: str):
    """Handle /fast_puppy custom command."""
    if name != "fast_puppy":
        return None

    args = command.split()[1:] if len(command.split()) > 1 else []
    return _handle_fast_puppy_command(args)


def _on_custom_command_help():
    """Provide help for /fast_puppy command."""
    return [
        ("fast_puppy [status]", "Show status (native acceleration removed in bd-86)"),
    ]


# Register callbacks
register_callback("startup", _on_startup)
register_callback("custom_command", _on_custom_command)
register_callback("custom_command_help", _on_custom_command_help)
