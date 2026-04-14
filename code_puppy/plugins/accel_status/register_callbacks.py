"""Acceleration status slash command - DEPRECATED.

DEPRECATED: Use /fast_puppy status instead.

This module is kept for backward compatibility and will be removed in a future release.
All acceleration status information is now available via /fast_puppy status.
"""

from code_puppy.callbacks import register_callback
from code_puppy.messaging import emit_info


def _custom_help() -> list[tuple[str, str]]:
    return [
        ("accel", "DEPRECATED: Use /fast_puppy status instead"),
    ]


def _handle_accel_command(command: str, name: str) -> bool | None:
    """Handle /accel commands - shows deprecation notice."""
    if not name:
        return None

    if name != "accel":
        return None

    # Show deprecation notice directing users to /fast_puppy status
    emit_info(
        "⚠️  /accel is deprecated. Use `/fast_puppy status` for acceleration info.\n"
        "   The /accel command will be removed in a future release."
    )
    return True


register_callback("custom_command_help", _custom_help)
register_callback("custom_command", _handle_accel_command)
