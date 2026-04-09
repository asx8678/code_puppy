"""Tool allowlist plugin for config-driven tool restriction.

This plugin provides allowlist/denylist functionality for tools via the
pre_tool_call hook. Configuration is read from puppy.cfg:

    [puppy]
    tool_allowlist = read_file,write_file,grep
    tool_denylist = agent_run_shell_command

Empty or missing config means no restrictions (disabled by default).
"""

from __future__ import annotations

import logging
from typing import Any

from code_puppy.callbacks import register_callback
from code_puppy.config import get_value

logger = logging.getLogger(__name__)


def _parse_tool_list(config_value: str | None) -> set[str]:
    """Parse a comma-separated list of tool names from config.

    Args:
        config_value: Raw config value, may be None or comma-separated string.

    Returns:
        Set of normalized (stripped, lowercase) tool names.
    """
    if not config_value:
        return set()

    tools = set()
    for item in config_value.split(","):
        tool_name = item.strip().lower()
        if tool_name:
            tools.add(tool_name)
    return tools


def _get_allowlist() -> set[str]:
    """Get the configured tool allowlist.

    Returns:
        Set of allowed tool names (empty if not configured).
    """
    raw = get_value("tool_allowlist")
    return _parse_tool_list(raw)


def _get_denylist() -> set[str]:
    """Get the configured tool denylist.

    Returns:
        Set of denied tool names (empty if not configured).
    """
    raw = get_value("tool_denylist")
    return _parse_tool_list(raw)


def _is_tool_allowed(tool_name: str, allowlist: set[str], denylist: set[str]) -> bool:
    """Check if a tool is allowed based on allowlist and denylist.

    Priority:
    1. If denylist contains the tool -> DENIED
    2. If allowlist is set and tool not in it -> DENIED
    3. Otherwise -> ALLOWED

    Args:
        tool_name: Name of the tool being called.
        allowlist: Set of allowed tool names (empty means no allowlist restriction).
        denylist: Set of denied tool names.

    Returns:
        True if tool is allowed, False otherwise.
    """
    normalized_name = tool_name.lower()

    # Check denylist first (highest priority)
    if normalized_name in denylist:
        return False

    # Check allowlist if it's configured
    if allowlist and normalized_name not in allowlist:
        return False

    return True


def _on_pre_tool_call(
    tool_name: str, tool_args: dict[str, Any], context: Any = None
) -> dict[str, Any] | None:
    """Pre-tool-call callback to enforce allowlist/denylist restrictions.

    Args:
        tool_name: Name of the tool being called.
        tool_args: Arguments being passed to the tool.
        context: Optional context data for the tool call.

    Returns:
        None if the tool is allowed to proceed.
        Dict with {"blocked": True, ...} if the tool should be denied.
    """
    allowlist = _get_allowlist()
    denylist = _get_denylist()

    # If no restrictions configured, allow everything (disabled by default)
    if not allowlist and not denylist:
        return None

    if _is_tool_allowed(tool_name, allowlist, denylist):
        return None

    # Tool is blocked - determine reason
    normalized_name = tool_name.lower()
    if normalized_name in denylist:
        reason = f"Tool '{tool_name}' is in the denylist"
    elif allowlist:
        reason = f"Tool '{tool_name}' is not in the allowlist"
    else:
        reason = f"Tool '{tool_name}' is blocked by policy"

    logger.warning(f"Tool blocked: {reason}")

    return {
        "blocked": True,
        "reason": reason,
        "error_message": f"🚫 Tool blocked: {reason}",
    }


def register():
    """Register the tool allowlist callback."""
    register_callback("pre_tool_call", _on_pre_tool_call)


# Auto-register on import
register()


__all__ = [
    "_parse_tool_list",
    "_get_allowlist",
    "_get_denylist",
    "_is_tool_allowed",
    "_on_pre_tool_call",
    "register",
]
