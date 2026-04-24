"""Code skeleton generator — compressed structural view of source files.

Replaces function/method bodies with ``...`` to show only signatures,
class declarations, and top-level constants. Dramatically reduces token
usage when providing file context to LLMs.

Pure regex-based skeleton generator. Tree-sitter / symbol-aware skeletons
are available via the Elixir code_context.explore_file bridge (see
code_puppy/code_context/explorer.py) when the Elixir runtime is connected.

Removed dead tree-sitter branches (deleted).
"""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Regex skeleton (the only implementation)
# ---------------------------------------------------------------------------

# Patterns that start a block scope
_BLOCK_START = re.compile(
    r"^(\s*)(class |def |async def |function |export function "
    r"|pub fn |fn |impl |func |interface |struct |enum )",
    re.IGNORECASE,
)

# Patterns for top-level assignments/constants
_TOP_LEVEL_ASSIGN = re.compile(r"^([A-Z_][A-Z_0-9]*)\s*=")


def _skeleton_via_regex(content: str) -> str:
    """Generate skeleton using regex-based heuristic.

    Works for Python and similar indent-based languages.
    Replaces function bodies with ``...``, keeps signatures and constants.
    Handles nested blocks (classes with methods, etc).
    """
    lines = content.splitlines()
    output: list[str] = []

    def get_indent(line: str) -> int:
        return len(line) - len(line.lstrip())

    # Pass 1: Identify all block-start lines and their indents
    block_lines: list[tuple[int, str, str]] = [] # (indent, keyword, full_line)
    for line in lines:
        match = _BLOCK_START.match(line)
        if match:
            indent_str = match.group(1)
            keyword = match.group(2).strip()
            block_lines.append((len(indent_str), keyword, line.rstrip()))

    if not block_lines:
        # No blocks found - just keep imports and constants
        for line in lines:
            stripped = line.rstrip()
            if stripped.startswith(
                ("import ", "from ", "#!", "//!", "///", "package ", "use ", "require")
            ):
                output.append(stripped)
            elif _TOP_LEVEL_ASSIGN.match(stripped):
                output.append(stripped)
        return "\n".join(output)

    # Pass 2: Output skeleton with proper nesting
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.rstrip()

        if not stripped:
            i += 1
            continue

        # Check if this is a block-start line
        match = _BLOCK_START.match(line)
        if match:
            current_indent = get_indent(line)
            indent_str = match.group(1)

            # Add the signature
            output.append(stripped)

            # Look ahead to find children (blocks at deeper indent) or body end
            j = i + 1
            found_children = False
            while j < len(lines):
                next_line = lines[j]
                next_stripped = next_line.rstrip()
                if not next_stripped:
                    j += 1
                    continue

                next_indent = get_indent(next_line)

                # If we've dedented past the block's level, we're done
                if next_indent <= current_indent and not next_stripped.startswith("#"):
                    break

                # Check for nested block at deeper indent
                if next_indent > current_indent:
                    nested_match = _BLOCK_START.match(next_line)
                    if nested_match:
                        found_children = True
                        break # We'll handle this in the next iteration

                j += 1

            if found_children:
                # Will process children next, add blank line
                output.append("")
            else:
                # No children - add ... placeholder and skip body
                output.append(indent_str + " ...")
                output.append("")
                i = j - 1 # Skip to the dedent position (will be processed next iter)

            i += 1
            continue

        # Keep imports and constants
        if stripped.startswith(
            ("import ", "from ", "#!", "//!", "///", "package ", "use ", "require")
        ):
            output.append(stripped)
        elif _TOP_LEVEL_ASSIGN.match(stripped):
            output.append(stripped)

        i += 1

    return "\n".join(output)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_skeleton(
    content: str,
    *,
    path: str | None = None,
    language: str | None = None,
    max_lines: int | None = None,
) -> str:
    """Generate a compressed structural skeleton of source code.

    Shows function/method signatures, class declarations, and top-level
    constants with bodies replaced by ``...``. Reduces token usage by
    60-80% for typical source files.

    Args:
        content: Full source code content.
        path: File path (reserved for API compatibility; not used currently).
        language: Explicit language name (reserved for API compatibility;
            not used currently).
        max_lines: Optional cap on output lines. Truncates with ``...`` marker.

    Returns:
        Skeleton source code with bodies replaced by ``...``.

    Examples:
        >>> code = '''
        ... class Calculator:
        ... def add(self, a, b):
        ... return a + b
        ... def multiply(self, a, b):
        ... result = a * b
        ... return result
        ... '''
        >>> skeleton = get_skeleton(code.strip(), path="calc.py")
        >>> "def add" in skeleton
        True
        >>> "return a + b" not in skeleton
        True
    """
    if not content.strip():
        return ""

    # Tree-sitter path removed; use regex directly.
    result = _skeleton_via_regex(content)

    # Apply max_lines cap
    if max_lines is not None and result:
        result_lines = result.splitlines()
        if len(result_lines) > max_lines:
            result = "\n".join(result_lines[:max_lines]) + "\n..."

    return result


def get_skeleton_for_file(
    file_path: str,
    *,
    max_lines: int | None = None,
    encoding: str = "utf-8",
) -> str:
    """Read a file and return its skeleton.

    Convenience wrapper around ``get_skeleton`` that handles file I/O.

    Args:
        file_path: Path to the source file.
        max_lines: Optional cap on output lines.
        encoding: File encoding (default: utf-8).

    Returns:
        Skeleton source code, or empty string if file can't be read.
    """
    try:
        content = Path(file_path).read_text(encoding=encoding, errors="replace")
    except (OSError, UnicodeDecodeError) as exc:
        logger.debug("code_skeleton: could not read %s: %s", file_path, exc)
        return ""

    return get_skeleton(content, path=file_path, max_lines=max_lines)
