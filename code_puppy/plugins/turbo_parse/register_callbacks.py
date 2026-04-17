"""Turbo Parse Plugin — Callback Registration.

bd-86: Native acceleration layer removed. This plugin is now disabled.
Parsing functionality has been moved to pure Python implementations.
"""

import logging

from code_puppy.callbacks import register_callback

logger = logging.getLogger(__name__)


def _on_startup():
    """Initialize the turbo_parse plugin on startup.

    bd-86: Native acceleration layer removed. Plugin is disabled.
    """
    logger.info("🐍 Turbo Parse: Native acceleration removed, plugin disabled")


def _on_register_tools():
    """Register turbo_parse tools (now disabled).

    bd-86: Returns empty list as native parsing is unavailable.
    """
    return []


def _on_custom_command(command: str, name: str):
    """Handle /parse commands.

    bd-86: All parse commands now return disabled message.
    """
    if name != "parse":
        return None

    return "Turbo Parse is disabled. Native acceleration layer removed (bd-86)."


def _on_custom_command_help():
    """Provide help for /parse command.

    bd-86: Returns disabled message.
    """
    return [
        ("parse", "DISABLED - Native acceleration layer removed (bd-86)"),
    ]


# Register callbacks
register_callback("startup", _on_startup)
register_callback("register_tools", _on_register_tools)
register_callback("custom_command", _on_custom_command)
register_callback("custom_command_help", _on_custom_command_help)
