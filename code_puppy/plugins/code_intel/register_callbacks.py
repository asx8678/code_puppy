"""Code Intelligence Plugin — Callback Registration.

Registers Tree-sitter based code intelligence with code_puppy:
- register_tools: Add code_intel_symbols, code_intel_references, code_intel_definition
- startup: Initialize (lazy, no work done until tools called)
- shutdown: Clear in-memory graph

Supports: Python, JavaScript/TypeScript, Rust, Go
Features: Incremental parsing (file hash tracking), in-memory symbol graph, structured JSON output
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from code_puppy.callbacks import register_callback

logger = logging.getLogger(__name__)

# Global parser instance (initialized lazily)
_incremental_parser: Any = None
_parser_lock = None


async def _get_parser():
    """Get or create the incremental parser."""
    global _incremental_parser, _parser_lock

    if _parser_lock is None:
        import asyncio

        _parser_lock = asyncio.Lock()

    if _incremental_parser is None:
        async with _parser_lock:
            if _incremental_parser is None:
                from code_puppy.code_intel.parser import IncrementalParser

                _incremental_parser = IncrementalParser()
                logger.debug("Code intelligence parser initialized")

    return _incremental_parser


def _on_startup():
    """Initialize on startup - parser is lazily created on first use."""
    logger.debug("Code intelligence plugin ready (lazy initialization)")


async def _on_shutdown():
    """Clear parser on shutdown."""
    global _incremental_parser
    if _incremental_parser:
        _incremental_parser.clear()
        _incremental_parser = None
        logger.debug("Code intelligence parser shut down")


def _register_code_intel_tools():
    """Register code intelligence tools.

    Returns a list of tool definitions for the register_tools callback.
    """
    return [
        {"name": "code_intel_symbols", "register_func": _register_symbols_tool},
        {"name": "code_intel_references", "register_func": _register_references_tool},
        {"name": "code_intel_definition", "register_func": _register_definition_tool},
    ]


def _register_symbols_tool(agent):
    """Register the code_intel_symbols tool.

    Extracts and returns symbols from source files.
    """
    from pydantic_ai import RunContext

    @agent.tool
    async def code_intel_symbols(
        context: RunContext,
        file_path: str,
        force_refresh: bool = False,
    ) -> dict:
        """Extract code symbols (functions, classes, etc.) from a source file.

        Parses the file using Tree-sitter and returns structured symbol information
        including names, types, signatures, and locations. Uses incremental parsing
        to avoid reparsing unchanged files unless force_refresh is True.

        Supports: Python, JavaScript/TypeScript (.js, .ts, .jsx, .tsx), Rust, Go

        Args:
            file_path: Path to the source file to analyze.
            force_refresh: If True, reparse even if file hasn't changed (default False).

        Returns:
            Dict with symbol information:
            - symbols: List of symbol dicts with name, kind, signature, location, etc.
            - file_parsed: True if file was parsed (changed or force_refresh)
            - symbol_count: Number of symbols found
            - error: Error message if parsing failed
        """
        try:
            parser = await _get_parser()

            # Force refresh if requested
            if force_refresh:
                parser.remove_file(file_path)

            # Parse the file
            was_parsed = parser.parse_file(file_path)

            # Get symbols from graph
            graph = parser.graph
            symbols = graph.get_symbols_in_file(file_path)

            return {
                "symbols": [s.to_dict() for s in symbols],
                "file_parsed": was_parsed,
                "symbol_count": len(symbols),
                "error": None,
            }

        except Exception as e:
            logger.debug(f"code_intel_symbols error: {e}")
            return {
                "symbols": [],
                "file_parsed": False,
                "symbol_count": 0,
                "error": f"Symbol extraction failed: {str(e)}",
            }


def _register_references_tool(agent):
    """Register the code_intel_references tool.

    Finds references to a symbol (calls, imports, etc.).
    """
    from pydantic_ai import RunContext

    @agent.tool
    async def code_intel_references(
        context: RunContext,
        symbol_name: str,
        file_path: Optional[str] = None,
        max_results: int = 50,
    ) -> dict:
        """Find references to a symbol (who calls it, imports it, etc.).

        Searches the symbol graph for references pointing to the specified symbol.
        Returns information about where and how the symbol is referenced.

        Args:
            symbol_name: Name of the symbol to find references to.
            file_path: Optional file path to narrow search (parses file first if provided).
            max_results: Maximum number of references to return (default 50).

        Returns:
            Dict with reference information:
            - references: List of reference dicts with source, kind, location
            - reference_count: Total number of references found
            - symbol_found: True if the symbol exists in the graph
            - error: Error message if query failed
        """
        try:
            parser = await _get_parser()

            # Parse file if provided
            if file_path:
                parser.parse_file(file_path)

            # Get the symbol
            graph = parser.graph
            symbol = graph.get_symbol(symbol_name)

            # Find references
            references = graph.find_references_to(symbol_name)

            # Limit results
            limited_refs = references[:max_results]

            return {
                "references": [ref.to_dict() for ref in limited_refs],
                "reference_count": len(references),
                "symbol_found": symbol is not None,
                "symbol": symbol.to_dict() if symbol else None,
                "error": None,
            }

        except Exception as e:
            logger.debug(f"code_intel_references error: {e}")
            return {
                "references": [],
                "reference_count": 0,
                "symbol_found": False,
                "symbol": None,
                "error": f"Reference query failed: {str(e)}",
            }


def _register_definition_tool(agent):
    """Register the code_intel_definition tool.

    Finds the definition location of a symbol.
    """
    from pydantic_ai import RunContext

    @agent.tool
    async def code_intel_definition(
        context: RunContext,
        symbol_name: str,
        file_path: Optional[str] = None,
        search_all_files: bool = False,
    ) -> dict:
        """Find the definition location of a symbol.

        Searches for the symbol definition and returns its location and details.
        Can search within a specific file or across all parsed files.

        Args:
            symbol_name: Name of the symbol to find (supports partial matching).
            file_path: Optional file path to search in (parses file first if provided).
            search_all_files: If True, search across all previously parsed files.

        Returns:
            Dict with definition information:
            - definitions: List of matching symbol definitions
            - definition_count: Number of definitions found
            - searched_files: List of files that were searched
            - error: Error message if query failed
        """
        try:
            parser = await _get_parser()
            graph = parser.graph
            searched_files = []

            definitions = []

            if file_path:
                # Parse and search specific file
                parser.parse_file(file_path)
                searched_files.append(file_path)

                symbol = graph.get_symbol(symbol_name, file_path)
                if symbol:
                    definitions.append(symbol)

            elif search_all_files:
                # Search across all tracked files
                tracked_files = list(parser.change_tracker.get_tracked_files())

                for fp in tracked_files:
                    parser.parse_file(fp)
                    searched_files.append(fp)

                    symbol = graph.get_symbol(symbol_name, fp)
                    if symbol:
                        definitions.append(symbol)

                # Also do partial name search
                if not definitions:
                    all_symbols = graph.search_symbols(symbol_name)
                    definitions = all_symbols

            else:
                # Just check already parsed symbols
                symbol = graph.get_symbol(symbol_name)
                if symbol:
                    definitions.append(symbol)
                    searched_files.append(symbol.location.file_path)

            return {
                "definitions": [d.to_dict() for d in definitions],
                "definition_count": len(definitions),
                "searched_files": searched_files,
                "error": None,
            }

        except Exception as e:
            logger.debug(f"code_intel_definition error: {e}")
            return {
                "definitions": [],
                "definition_count": 0,
                "searched_files": [],
                "error": f"Definition query failed: {str(e)}",
            }


def _code_intel_command_help():
    """Provide help for code intelligence commands."""
    return []


def _handle_code_intel_command(command: str, name: str) -> Any:
    """Handle code intelligence slash commands (none currently)."""
    return None


def _load_code_intel_prompt() -> str:
    """Add guidance for code intelligence tool usage to system prompts."""
    return """

## 🔍 Code Intelligence Tools (Tree-sitter based)

The following tools provide static code analysis via Tree-sitter AST parsing:

- `code_intel_symbols(file_path, force_refresh=False)`: Extract symbols (functions, classes, imports) from a file
- `code_intel_references(symbol_name, file_path=None, max_results=50)`: Find who references a symbol
- `code_intel_definition(symbol_name, file_path=None, search_all_files=False)`: Find where a symbol is defined

Supported languages:
- Python (.py)
- JavaScript/TypeScript (.js, .ts, .jsx, .tsx)
- Rust (.rs)
- Go (.go)

Features:
- Incremental parsing: only changed files are reparsed
- In-memory symbol graph (rebuilt from source each session)
- Structured JSON output with locations, signatures, and relationships

Use these tools to understand code structure without needing LSP servers.
"""


# Register all callbacks
register_callback("startup", _on_startup)
register_callback("shutdown", _on_shutdown)
register_callback("register_tools", _register_code_intel_tools)
register_callback("custom_command_help", _code_intel_command_help)
register_callback("custom_command", _handle_code_intel_command)
register_callback("load_prompt", _load_code_intel_prompt)

logger.info("Code intelligence plugin callbacks registered")
