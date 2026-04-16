"""Code Explorer Plugin — Callback Registration.

Registers code exploration tools that integrate turbo_parse symbols
with existing code exploration flows in code_puppy.

## Available Tools

### get_code_context
Get enhanced code context for a file including symbols and outline.

**Parameters:**
- `file_path` (string, required): Path to the file to analyze
- `include_content` (bool, optional): Whether to include file content (default: False)
- `with_symbols` (bool, optional): Whether to extract symbols (default: True)

**Returns:** Dict with file_path, language, outline, symbols, metadata

### explore_directory
Explore a directory and get code contexts for all supported files.

**Parameters:**
- `directory` (string, required): Path to the directory
- `pattern` (string, optional): File pattern to match (default: "*")
- `recursive` (bool, optional): Whether to search recursively (default: True)
- `max_files` (int, optional): Maximum files to process (default: 50)

**Returns:** List of code context dicts

### get_file_outline
Get hierarchical symbol outline for a file.

**Parameters:**
- `file_path` (string, required): Path to the file
- `max_depth` (int, optional): Maximum depth for nested symbols

**Returns:** Dict with hierarchical outline structure

## Integration

This plugin integrates with:
- `register_tools` hook: Registers exploration tools
- `custom_command` hook: Provides /explore slash command
- `pre_tool_call` hook: Optionally enhances read_file with symbols
"""

import logging
from typing import Any

from pydantic_ai import RunContext

from code_puppy.callbacks import register_callback
from code_puppy.code_context import (
    CodeExplorer,
    explore_directory as _explore_directory,
    format_outline,
    get_code_context as _get_code_context,
    get_file_outline as _get_file_outline,
)
from code_puppy.messaging import emit_info, emit_error

logger = logging.getLogger(__name__)


def _get_explorer() -> CodeExplorer:
    """Get the global CodeExplorer instance."""
    from code_puppy.code_context import get_explorer_instance

    return get_explorer_instance()


def _on_startup():
    """Initialize the code explorer plugin on startup."""
    logger.info("🔍 Code Explorer: Symbol-augmented code exploration ready")


# -----------------------------------------------------------------------------
# Tool Registration
# -----------------------------------------------------------------------------


def _register_get_code_context_tool(agent):
    """Register the get_code_context tool."""

    @agent.tool
    async def get_code_context(
        context: RunContext,
        file_path: str,
        include_content: bool = False,
        with_symbols: bool = True,
    ) -> dict[str, Any]:
        """Get enhanced code context for a file including symbols and outline.

        Use this tool when you need to:
        - Understand the structure of a code file
        - Get function/class definitions and their locations
        - Explore code with symbol-level information
        - Navigate large files efficiently

        This tool integrates turbo_parse to provide structural information
        about the code, including class hierarchies, function signatures,
        and import statements.

        Args:
            file_path: Path to the file to analyze
            include_content: Whether to include full file content (default: False)
            with_symbols: Whether to extract symbols (default: True)

        Returns:
            Dict with:
            - file_path: str - Absolute path to the file
            - language: str - Detected programming language
            - num_lines: int - Number of lines in the file
            - num_tokens: int - Estimated token count
            - outline: dict - Hierarchical symbol outline with classes, functions, etc.
            - symbols_available: bool - Whether symbol extraction succeeded
            - content: str | None - Full file content (if include_content=True)
        """
        try:
            code_context = _get_code_context(
                file_path, include_content=include_content, with_symbols=with_symbols
            )

            result: dict[str, Any] = {
                "file_path": code_context.file_path,
                "language": code_context.language,
                "num_lines": code_context.num_lines,
                "num_tokens": code_context.num_tokens,
                "symbols_available": code_context.is_parsed,
            }

            if code_context.outline:
                result["outline"] = code_context.outline.to_dict()

            if code_context.content:
                result["content"] = code_context.content

            if code_context.has_errors:
                result["error"] = code_context.error_message

            return result

        except Exception as e:
            logger.exception(f"get_code_context failed for {file_path}")
            return {
                "file_path": file_path,
                "error": f"Failed to get code context: {str(e)}",
                "symbols_available": False,
            }


def _register_explore_directory_tool(agent):
    """Register the explore_directory tool."""

    @agent.tool
    async def explore_directory(
        context: RunContext,
        directory: str,
        pattern: str = "*",
        recursive: bool = True,
        max_files: int = 50,
    ) -> dict[str, Any]:
        """Explore a directory and get code contexts for all supported files.

        Use this tool when you need to:
        - Survey a codebase structure
        - Find all classes and functions in a directory
        - Get an overview of multiple files
        - Batch analyze code files

        Only files with supported extensions (.py, .rs, .js, .ts, etc.)
        will be processed. Other files are silently skipped.

        Args:
            directory: Path to the directory to explore
            pattern: File pattern to match (default: "*" for all files)
            recursive: Whether to search recursively (default: True)
            max_files: Maximum number of files to process (default: 50)

        Returns:
            Dict with:
            - contexts: list - Code contexts for each file
            - total_files: int - Number of files processed
            - summary: dict - Summary with language counts, total symbols, etc.
        """
        try:
            contexts = _explore_directory(
                directory=directory,
                pattern=pattern,
                recursive=recursive,
                max_files=max_files,
            )

            context_dicts = []
            language_counts: dict[str, int] = {}
            total_symbols = 0

            for ctx in contexts:
                ctx_dict = {
                    "file_path": ctx.file_path,
                    "language": ctx.language,
                    "num_lines": ctx.num_lines,
                    "num_tokens": ctx.num_tokens,
                    "symbols_available": ctx.is_parsed,
                    "symbol_count": ctx.symbol_count,
                }

                if ctx.outline:
                    ctx_dict["outline"] = ctx.outline.to_dict()

                context_dicts.append(ctx_dict)

                # Count languages
                if ctx.language:
                    language_counts[ctx.language] = (
                        language_counts.get(ctx.language, 0) + 1
                    )

                total_symbols += ctx.symbol_count

            return {
                "contexts": context_dicts,
                "total_files": len(contexts),
                "summary": {
                    "language_counts": language_counts,
                    "total_symbols": total_symbols,
                    "directory": directory,
                },
            }

        except Exception as e:
            logger.exception(f"explore_directory failed for {directory}")
            return {
                "error": f"Failed to explore directory: {str(e)}",
                "contexts": [],
                "total_files": 0,
            }


def _register_get_file_outline_tool(agent):
    """Register the get_file_outline tool."""

    @agent.tool
    async def get_file_outline(
        context: RunContext,
        file_path: str,
        max_depth: int | None = None,
    ) -> dict[str, Any]:
        """Get hierarchical symbol outline for a file.

        Use this tool when you need to:
        - See the structure of a code file
        - Navigate class hierarchies
        - Find function/method locations
        - Understand code organization

        Args:
            file_path: Path to the file
            max_depth: Maximum depth for nested symbols (e.g., 2 for top-level only)

        Returns:
            Dict with:
            - outline: list - Hierarchical symbol structure
            - language: str - Programming language
            - success: bool - Whether extraction succeeded
            - formatted: str - Human-readable formatted outline
        """
        try:
            outline = _get_file_outline(file_path, max_depth=max_depth)

            return {
                "outline": outline.to_dict()["symbols"],
                "language": outline.language,
                "success": outline.success,
                "formatted": format_outline(outline, show_lines=True),
                "errors": outline.errors,
            }

        except Exception as e:
            logger.exception(f"get_file_outline failed for {file_path}")
            return {
                "outline": [],
                "language": "unknown",
                "success": False,
                "formatted": f"Error: {str(e)}",
                "errors": [str(e)],
            }


def _register_tools() -> list[dict[str, Any]]:
    """Register code explorer tools.

    Returns a list of tool definitions for the register_tools callback.
    """
    return [
        {
            "name": "get_code_context",
            "register_func": _register_get_code_context_tool,
        },
        {
            "name": "explore_directory",
            "register_func": _register_explore_directory_tool,
        },
        {
            "name": "get_file_outline",
            "register_func": _register_get_file_outline_tool,
        },
    ]


# -----------------------------------------------------------------------------
# Slash Command Implementation
# -----------------------------------------------------------------------------


def _explore_help() -> list[tuple[str, str]]:
    """Return help entries for the /explore command."""
    return [
        ("explore", "Symbol-augmented code exploration with turbo_parse"),
        ("explore file <path>", "Get code context for a single file"),
        ("explore dir <path>", "Explore a directory of code files"),
        ("explore outline <path>", "Show hierarchical outline of a file"),
        ("explore help", "Show detailed usage for the /explore command"),
    ]


def _format_file_context(context: dict[str, Any]) -> str:
    """Format a code context for display."""
    lines = [
        f"📄 {context.get('file_path', 'unknown')}",
        f"   Language: {context.get('language', 'unknown')}",
        f"   Lines: {context.get('num_lines', 0)}, "
        f"Tokens: {context.get('num_tokens', 0)}",
    ]

    if context.get("symbols_available"):
        outline = context.get("outline", {})
        symbols = outline.get("symbols", [])

        # Count by kind
        classes = [s for s in symbols if s.get("kind") in ("class", "struct")]
        functions = [s for s in symbols if s.get("kind") in ("function", "method")]
        imports = [s for s in symbols if s.get("kind") == "import"]

        lines.append(f"   Symbols: {len(symbols)} total")
        if classes:
            lines.append(f"      Classes: {len(classes)}")
        if functions:
            lines.append(f"      Functions: {len(functions)}")
        if imports:
            lines.append(f"      Imports: {len(imports)}")

        # Show top-level symbols
        if symbols:
            lines.append("   Outline:")
            for symbol in symbols[:10]:  # Show first 10
                kind_icon = {
                    "class": "🏛️",
                    "struct": "🏛️",
                    "function": "⚡",
                    "method": "🔹",
                    "import": "📦",
                }.get(symbol.get("kind"), "•")
                line_info = f" (L{symbol.get('start_line', 0)})"
                lines.append(f"      {kind_icon} {symbol.get('name')}{line_info}")

            if len(symbols) > 10:
                lines.append(f"      ... and {len(symbols) - 10} more")

    if context.get("error"):
        lines.append(f"   ⚠️ {context['error']}")

    return "\n".join(lines)


def _handle_explore_file(path_str: str) -> str:
    """Handle the /explore file <path> subcommand."""
    try:
        # Use the async version through the explorer
        context = _get_code_context(path_str, include_content=False)
        return _format_file_context(context.to_dict())
    except Exception as e:
        return f"❌ Error exploring file: {e}"


def _handle_explore_dir(path_str: str) -> str:
    """Handle the /explore dir <path> subcommand."""
    try:
        contexts = _explore_directory(path_str, max_files=20)

        if not contexts:
            return f"📁 No supported files found in {path_str}"

        lines = [
            f"📁 Directory: {path_str}",
            f"Found {len(contexts)} files with code context:\n",
        ]

        # Group by language
        by_language: dict[str, list[dict[str, Any]]] = {}
        for ctx in contexts:
            lang = ctx.language or "unknown"
            if lang not in by_language:
                by_language[lang] = []
            by_language[lang].append(ctx.to_dict())

        for lang, ctxs in sorted(by_language.items()):
            lines.append(f"\n🔸 {lang.upper()} ({len(ctxs)} files):")
            for ctx in ctxs:
                file_name = ctx.get("file_path", "unknown").split("/")[-1]
                sym_count = ctx.get("symbol_count", 0)
                lines.append(f"   • {file_name} ({sym_count} symbols)")

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Error exploring directory: {e}"


def _handle_explore_outline(path_str: str) -> str:
    """Handle the /explore outline <path> subcommand."""
    try:
        outline = _get_file_outline(path_str)
        return format_outline(outline, show_lines=True)
    except Exception as e:
        return f"❌ Error getting outline: {e}"


def _handle_explore_help() -> str:
    """Handle the /explore help subcommand."""
    return """📖 /explore Command Help
========================

Symbol-augmented code exploration with turbo_parse integration.

Usage:
  /explore file <path>     Get code context for a single file
  /explore dir <path>      Explore a directory of code files
  /explore outline <path>  Show hierarchical outline of a file
  /explore help            Show this help message

Supported Languages:
  • Python (.py)
  • Rust (.rs)
  • JavaScript (.js, .jsx)
  • TypeScript (.ts, .tsx)
  • Elixir (.ex, .exs, .heex)

Examples:
  /explore file ./src/main.py
  /explore dir ./lib
  /explore outline ./code_puppy/agents/base_agent.py
"""


def _handle_explore_command(command: str, name: str) -> bool | str | None:
    """Handle the /explore custom slash command."""
    if name != "explore":
        return None

    parts = command.split(maxsplit=2)
    subcommand = parts[1] if len(parts) > 1 else None

    if subcommand is None:
        emit_info(_handle_explore_help())
        return True

    subcommand = subcommand.lower()

    if subcommand == "file":
        if len(parts) < 3:
            emit_error("Usage: /explore file <path>")
            return True
        path = parts[2].strip()
        output = _handle_explore_file(path)
        emit_info(output)
        return True

    elif subcommand in ("dir", "directory"):
        if len(parts) < 3:
            emit_error("Usage: /explore dir <path>")
            return True
        path = parts[2].strip()
        output = _handle_explore_dir(path)
        emit_info(output)
        return True

    elif subcommand == "outline":
        if len(parts) < 3:
            emit_error("Usage: /explore outline <path>")
            return True
        path = parts[2].strip()
        output = _handle_explore_outline(path)
        emit_info(output)
        return True

    elif subcommand == "help":
        emit_info(_handle_explore_help())
        return True

    else:
        emit_error(f"Unknown subcommand: {subcommand}")
        emit_info("Run '/explore help' for available subcommands")
        return True


# -----------------------------------------------------------------------------
# Optional: Enhance read_file with symbols
# -----------------------------------------------------------------------------


def _on_pre_tool_call(
    tool_name: str,
    tool_args: dict,
    context: Any = None,
) -> Any:
    """Hook to optionally enhance read_file with symbol info.

    This hook checks if read_file is being called with a 'with_symbols'
    parameter and enhances the result if so.
    """
    if tool_name != "read_file":
        return None

    # Check if with_symbols is requested
    with_symbols = tool_args.get("with_symbols", False)
    if not with_symbols:
        return None

    # This would need to be implemented as a post-processing hook
    # For now, we just log that it was requested
    logger.debug(f"read_file with_symbols requested for {tool_args.get('file_path')}")
    return None


# -----------------------------------------------------------------------------
# Register all callbacks
# -----------------------------------------------------------------------------

register_callback("startup", _on_startup)
register_callback("register_tools", _register_tools)
register_callback("custom_command_help", _explore_help)
register_callback("custom_command", _handle_explore_command)

logger.debug("Code Explorer plugin callbacks registered")
