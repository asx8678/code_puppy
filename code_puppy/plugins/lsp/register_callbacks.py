"""LSP Plugin — Callback Registration.

Registers headless LSP integration with code_puppy:
- register_tools: Add lsp_hover, lsp_diagnostics, lsp_symbols, lsp_validate tools
- startup: Initialize server manager with cleanup task
- shutdown: Gracefully close all LSP connections

Supports: pyright, typescript-language-server, rust-analyzer, gopls
Features: Lazy startup, connection pooling, auto-detection from file extensions
"""

import logging
from typing import Any

from pydantic_ai import RunContext

from code_puppy.callbacks import register_callback

logger = logging.getLogger(__name__)

# Global manager instance (initialized lazily)
_lsp_manager: Any = None
_manager_lock = None


async def _get_manager():
    """Get or create the LSP server manager."""
    global _lsp_manager, _manager_lock

    if _manager_lock is None:
        import asyncio
        _manager_lock = asyncio.Lock()

    if _lsp_manager is None:
        async with _manager_lock:
            if _lsp_manager is None:
                from code_puppy.lsp.manager import LspServerManager
                _lsp_manager = LspServerManager()
                _lsp_manager.start_cleanup_task()
                logger.debug("LSP server manager initialized")

    return _lsp_manager


def _on_startup():
    """Initialize on startup - manager is lazily created on first use."""
    logger.debug("LSP plugin ready (lazy initialization)")


async def _on_shutdown():
    """Close all LSP connections on shutdown."""
    global _lsp_manager
    if _lsp_manager:
        await _lsp_manager.close_all()
        _lsp_manager = None
        logger.debug("LSP server manager shut down")


def _register_lsp_tools():
    """Register LSP tools.

    Returns a list of tool definitions for the register_tools callback.
    """
    return [
        {"name": "lsp_hover", "register_func": _register_hover_tool},
        {"name": "lsp_diagnostics", "register_func": _register_diagnostics_tool},
        {"name": "lsp_symbols", "register_func": _register_symbols_tool},
        {"name": "lsp_validate", "register_func": _register_validate_tool},
    ]


def _register_hover_tool(agent):
    """Register the lsp_hover tool.

    Provides type information and documentation for symbols at a position.
    """

    @agent.tool
    async def lsp_hover(
        context: RunContext,
        file_path: str,
        line: int,
        character: int,
    ) -> dict:
        """Get type information and documentation for a symbol at a specific position.

        Uses the appropriate LSP server (pyright, typescript-language-server,
        rust-analyzer, gopls) based on the file type. Returns hover information
        including type signatures and documentation.

        Args:
            file_path: Path to the file to query.
            line: Zero-based line number (0-indexed).
            character: Zero-based character position (0-indexed).

        Returns:
            Dict with hover information:
            - content: The hover text (type info, docs)
            - kind: Format of content (plaintext, markdown)
            - range: Optional range dict with start/end positions
            - error: Error message if request failed
        """
        try:
            manager = await _get_manager()

            from code_puppy.lsp.queries import LspQueries
            queries = LspQueries(manager)

            result = await queries.hover(file_path, line, character)

            if result is None:
                return {
                    "content": "",
                    "kind": "plaintext",
                    "error": "No hover information available (LSP server not available or no symbol at position)",
                }

            return {
                "content": result.get("content", ""),
                "kind": result.get("kind", "plaintext"),
                "range": result.get("range"),
            }

        except Exception as e:
            logger.debug(f"lsp_hover error: {e}")
            return {
                "content": "",
                "kind": "plaintext",
                "error": f"Hover query failed: {str(e)}",
            }


def _register_diagnostics_tool(agent):
    """Register the lsp_diagnostics tool.

    Provides diagnostic information (errors, warnings) for a file.
    """

    @agent.tool
    async def lsp_diagnostics(
        context: RunContext,
        file_path: str,
        max_diagnostics: int = 50,
    ) -> dict:
        """Get diagnostic information (errors, warnings) for a file.

        Runs the file through the appropriate LSP server to collect
        diagnostics like type errors, linting warnings, and suggestions.

        Args:
            file_path: Path to the file to check.
            max_diagnostics: Maximum number of diagnostics to return (default 50).

        Returns:
            Dict with diagnostic information:
            - valid: True if no errors found
            - diagnostics: List of diagnostic items with message, severity, line, column
            - error_count: Number of errors
            - warning_count: Number of warnings
            - error: Error message if check failed
        """
        try:
            manager = await _get_manager()

            from code_puppy.lsp.validator import LspValidator
            validator = LspValidator(manager)

            result = await validator.validate_file(file_path, max_diagnostics)
            return result

        except Exception as e:
            logger.debug(f"lsp_diagnostics error: {e}")
            return {
                "valid": False,
                "error": f"Diagnostics failed: {str(e)}",
                "diagnostics": [],
                "error_count": 0,
                "warning_count": 0,
            }


def _register_symbols_tool(agent):
    """Register the lsp_symbols tool.

    Provides document symbols (outline/structure) for a file.
    """

    @agent.tool
    async def lsp_symbols(
        context: RunContext,
        file_path: str,
    ) -> dict:
        """Get document symbols (outline/structure) for a file.

        Returns a hierarchical structure of symbols including functions,
        classes, variables, and their locations. Useful for understanding
        code structure and finding specific definitions.

        Args:
            file_path: Path to the file to analyze.

        Returns:
            Dict with symbol information:
            - symbols: List of symbol dicts with name, kind, range, children
            - error: Error message if request failed
        """
        try:
            manager = await _get_manager()

            from code_puppy.lsp.queries import LspQueries
            queries = LspQueries(manager)

            symbols = await queries.document_symbols(file_path)

            return {
                "symbols": symbols,
                "count": len(symbols),
            }

        except Exception as e:
            logger.debug(f"lsp_symbols error: {e}")
            return {
                "symbols": [],
                "count": 0,
                "error": f"Symbols query failed: {str(e)}",
            }


def _register_validate_tool(agent):
    """Register the lsp_validate tool.

    Validates code (file or inline) and returns type errors.
    """

    @agent.tool
    async def lsp_validate(
        context: RunContext,
        file_path: str | None = None,
        code: str | None = None,
        language: str | None = None,
        max_diagnostics: int = 50,
    ) -> dict:
        """Validate code using LSP and return type errors and warnings.

        Can validate either:
        - An existing file (provide file_path)
        - Inline code (provide code and language)

        Args:
            file_path: Path to existing file to validate (optional).
            code: Code string to validate (optional, requires language).
            language: Language for inline code (python, typescript, rust, go).
            max_diagnostics: Maximum number of diagnostics to return (default 50).

        Returns:
            Dict with validation results:
            - valid: True if no errors found
            - diagnostics: List of issues with severity, message, location
            - error_count: Number of errors
            - warning_count: Number of warnings
            - error: Error message if validation failed
        """
        try:
            manager = await _get_manager()

            from code_puppy.lsp.validator import LspValidator
            validator = LspValidator(manager)

            if file_path:
                # Validate existing file
                result = await validator.validate_file(file_path, max_diagnostics)
                return result

            elif code and language:
                # Validate inline code
                result = await validator.validate_code(code, language, max_diagnostics)
                return result

            else:
                return {
                    "valid": False,
                    "error": "Provide either file_path or (code + language)",
                    "diagnostics": [],
                    "error_count": 0,
                    "warning_count": 0,
                }

        except Exception as e:
            logger.debug(f"lsp_validate error: {e}")
            return {
                "valid": False,
                "error": f"Validation failed: {str(e)}",
                "diagnostics": [],
                "error_count": 0,
                "warning_count": 0,
            }


def _lsp_command_help():
    """Provide help for LSP-related commands."""
    return []


def _handle_lsp_command(command: str, name: str) -> Any:
    """Handle LSP-related slash commands (none currently)."""
    return None


def _load_lsp_prompt() -> str:
    """Add guidance for LSP tool usage to system prompts.

    This is called via the 'load_prompt' callback.
    """
    return """

## 🔍 LSP Type-Aware Tools

The following tools provide type information and validation via Language Server Protocol:

- `lsp_hover(file_path, line, character)`: Get type and documentation at a position
- `lsp_diagnostics(file_path)`: Get errors and warnings for a file
- `lsp_symbols(file_path)`: Get code structure (functions, classes, etc.)
- `lsp_validate(file_path|code, language)`: Validate code for type errors

Supported languages (requires server installed):
- Python: pyright (pip install pyright)
- TypeScript/JavaScript: typescript-language-server (npm install -g typescript-language-server)
- Rust: rust-analyzer (usually included with Rust)
- Go: gopls (go install golang.org/x/tools/gopls@latest)

These tools are lazy - LSP servers only start when first queried.
"""


# Register all callbacks
register_callback("startup", _on_startup)
register_callback("shutdown", _on_shutdown)
register_callback("register_tools", _register_lsp_tools)
register_callback("custom_command_help", _lsp_command_help)
register_callback("custom_command", _handle_lsp_command)
register_callback("load_prompt", _load_lsp_prompt)

logger.info("LSP plugin callbacks registered")
