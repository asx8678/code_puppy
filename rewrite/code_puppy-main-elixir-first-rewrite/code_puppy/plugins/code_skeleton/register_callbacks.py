"""Code Skeleton plugin — structural compression for token-budget optimization.

Registers:
- ``/skeleton <path>`` command to display file skeletons
- ``skeleton`` tool for agents to request compressed file views

Inspired by Agentless ``compress_file.py``. Uses tree-sitter (multi-language)
with regex fallback.
"""

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


def _handle_context_command(command: str, name: str) -> str | None:
    """Handle /context <path> <start_line> <end_line> command.

    Shows a file fragment with enclosing scope context headers,
    like VS Code's sticky scroll.
    """
    if name != "context":
        return None

    parts = command.strip().split()
    if len(parts) < 4:
        return "Usage: /context <file_path> <start_line> <end_line>"

    file_path = parts[1]
    try:
        start_line = int(parts[2])
        end_line = int(parts[3])
    except ValueError:
        return "Error: start_line and end_line must be integers"

    if start_line < 1 or end_line < start_line:
        return "Error: start_line must be >= 1 and end_line >= start_line"

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.read().splitlines()
    except OSError as exc:
        return f"Error reading file: {exc}"

    if start_line > len(all_lines):
        return f"Error: file has only {len(all_lines)} lines"

    from code_puppy.utils.file_display import inject_scope_context

    result = inject_scope_context(
        all_lines, start_line, min(end_line, len(all_lines))
    )

    if not result:
        return "No content to display"

    # Format with line numbers for context lines, then fragment lines
    output_lines = []
    fragment_start = 0
    for i, line in enumerate(result):
        if line.startswith("// "):
            output_lines.append(f"  {line}")
            fragment_start = i + 1
        else:
            actual_line_num = start_line + (i - fragment_start)
            output_lines.append(f"{actual_line_num:6d}\t{line}")

    return "```\n" + "\n".join(output_lines) + "\n```"


def _skeleton_help() -> list[tuple[str, str]]:
    """Provide help entries for skeleton and context commands."""
    return [
        ("/skeleton <path>", "Show compressed structural skeleton of a source file"),
        ("/context <path> <start> <end>", "Show file fragment with enclosing scope context"),
    ]


def _register_skeleton_tool() -> list[dict]:
    """Register the skeleton tool for agent use."""

    def _register_get_file_skeleton(agent):
        """Register get_file_skeleton with the agent."""

        @agent.tool
        async def get_file_skeleton(
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
            "register_func": _register_get_file_skeleton,
        }
    ]


# Register callbacks at module scope
register_callback("custom_command", _handle_skeleton_command)
register_callback("custom_command", _handle_context_command)
register_callback("custom_command_help", _skeleton_help)
register_callback("register_tools", _register_skeleton_tool)
