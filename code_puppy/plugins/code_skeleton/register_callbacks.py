"""Code Skeleton plugin — structural compression for token-budget optimization.

Registers:
- ``/skeleton <path>`` command to display file skeletons
- ``skeleton`` tool for agents to request compressed file views

Inspired by Agentless ``compress_file.py``. Uses tree-sitter (multi-language)
with regex fallback.
"""

from __future__ import annotations

import logging

from code_puppy.callbacks import register_callback

logger = logging.getLogger(__name__)


def _handle_skeleton_command(command: str, name: str) -> str | None:
    """Handle /skeleton <path> slash command."""
    if name != "skeleton":
        return None

    parts = command.strip().split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        return "Usage: /skeleton <file_path> [--max-lines N]"

    args = parts[1].strip().split()
    file_path = args[0]
    max_lines = None

    # Parse --max-lines flag
    for i, arg in enumerate(args[1:], 1):
        if arg == "--max-lines" and i + 1 < len(args):
            try:
                max_lines = int(args[i + 1])
            except ValueError:
                return f"Invalid --max-lines value: {args[i + 1]}"

    from .skeleton import get_skeleton_for_file

    result = get_skeleton_for_file(file_path, max_lines=max_lines)
    if not result:
        return f"Could not generate skeleton for: {file_path}"

    return f"```\n{result}\n```"


def _skeleton_help() -> list[tuple[str, str]]:
    """Provide help entry for /skeleton command."""
    return [
        ("/skeleton <path>", "Show compressed structural skeleton of a source file"),
    ]


def _register_skeleton_tool() -> list[dict]:
    """Register the skeleton tool for agent use."""

    def skeleton_tool_handler(
        context,
        file_path: str,
        max_lines: int | None = None,
    ) -> str:
        """Generate a compressed skeleton of a source file.

        Shows only function signatures, class declarations, and constants.
        Bodies are replaced with ``...``. Reduces tokens by 60-80%.

        Args:
            context: Tool context (provided by framework).
            file_path: Path to the source file to compress.
            max_lines: Optional maximum output lines.

        Returns:
            Compressed skeleton view of the file.
        """
        from .skeleton import get_skeleton_for_file

        result = get_skeleton_for_file(file_path, max_lines=max_lines)
        if not result:
            return f"Could not generate skeleton for: {file_path}"
        return result

    return [
        {
            "name": "get_file_skeleton",
            "register_func": skeleton_tool_handler,
        }
    ]


# Register callbacks at module scope
register_callback("custom_command", _handle_skeleton_command)
register_callback("custom_command_help", _skeleton_help)
register_callback("register_tools", _register_skeleton_tool)
