"""Turbo Parse Plugin — Callback Registration.

Registers the turbo_parse parsing system with code_puppy's callback hooks:
- startup: Check turbo_parse Rust module availability and log status
- register_tools: Register the parse_code tool for code parsing operations
- custom_command: Register the /parse slash command with subcommands
- custom_command_help: Register help text for the /parse command

## parse_code Tool

The parse_code tool provides high-performance code parsing using the turbo_parse
Rust module with graceful fallback to stub implementations when unavailable.

### Tool Signature

**Name:** `parse_code`

**Parameters:**
- `source` (string, required): Source code to parse
- `language` (string, required): Programming language identifier
  (e.g., "python", "rust", "javascript", "typescript")
- `options` (dict, optional): Additional parsing options
  - `extract_symbols` (bool): Whether to extract symbol outline
  - `extract_diagnostics` (bool): Whether to extract syntax diagnostics
  - `include_tree` (bool): Whether to include full AST tree (default: True)

**Returns:**
```python
{
    "success": bool,              # Whether parsing succeeded
    "tree": dict | None,          # Serialized AST tree
    "symbols": list,            # List of extracted symbols
    "diagnostics": list,        # Syntax error/warning diagnostics
    "parse_time_ms": float,     # Time taken to parse in milliseconds
    "language": str,            # Normalized language identifier
    "errors": list,             # Error messages if any
}
```

### Usage Example

```python
result = await parse_code(
    source="def hello(): pass",
    language="python",
    options={"extract_symbols": True}
)
# result["success"] -> True
# result["symbols"] -> [{"name": "hello", "kind": "function", ...}]
```

## /parse Slash Command

The /parse command provides CLI access to the turbo_parse functionality:

### Subcommands

- `/parse status` - Show parser health, version, supported languages, and stats
- `/parse parse_path <path>` - Parse a file or directory at the given path
- `/parse help` - Show usage information

### Usage Examples

```
/parse status
/parse parse_path ./src/main.py
/parse parse_path ./src
/parse help
```
"""

import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic_ai import RunContext

from code_puppy.callbacks import register_callback
from code_puppy.messaging import emit_info, emit_success, emit_warning, emit_error
from code_puppy.plugins.turbo_parse import is_turbo_parse_available
from code_puppy.turbo_parse_bridge import (
    parse_source as _parse_source,
    parse_file as _parse_file,
    parse_files_batch as _parse_files_batch,
    extract_symbols as _extract_symbols,
    extract_symbols_from_file as _extract_symbols_from_file,
    extract_syntax_diagnostics as _extract_diagnostics,
    is_language_supported,
    supported_languages,
    health_check,
    stats,
    TURBO_PARSE_AVAILABLE,
)

logger = logging.getLogger(__name__)


def _on_startup():
    """Initialize the turbo_parse plugin on startup.
    
    Attempts to import the turbo_parse Rust module and logs availability status.
    Gracefully falls back to pure Python if the Rust module is not available.
    """
    if is_turbo_parse_available():
        try:
            import turbo_parse
            version = getattr(turbo_parse, "__version__", "unknown")
            
            # Try to call health_check if available
            try:
                health = turbo_parse.health_check()
                logger.info(
                    f"🚀 Turbo Parse: Rust module available (version: {health.get('version', 'unknown')})"
                )
            except AttributeError:
                logger.info(
                    f"🚀 Turbo Parse: Rust module available (version: {version})"
                )
            except Exception as e:
                logger.warning(
                    f"🚀 Turbo Parse: Rust module available but health check failed: {e}"
                )
        except Exception as e:
            logger.warning(
                f"⚠️ Turbo Parse: Unexpected error loading Rust module: {e}. "
                f"Using pure Python fallback."
            )
    else:
        logger.info(
            "🐍 Turbo Parse: Rust module not available, using pure Python fallback"
        )


def _normalize_language(language: str) -> str:
    """Normalize language identifier to canonical form.
    
    Args:
        language: Raw language identifier
        
    Returns:
        Normalized language name
    """
    lang_lower = language.lower().strip()
    aliases = {
        "py": "python",
        "js": "javascript",
        "ts": "typescript",
        "jsx": "javascript",
        "tsx": "typescript",
        "ex": "elixir",
        "exs": "elixir",
        "rs": "rust",
    }
    return aliases.get(lang_lower, lang_lower)


def _register_parse_code_tool(agent):
    """Register the parse_code tool with an agent.
    
    Tool JSON Schema:
    {
        "name": "parse_code",
        "description": "Parse source code and extract AST, symbols, and diagnostics...",
        "parameters": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Source code to parse"
                },
                "language": {
                    "type": "string",
                    "description": "Programming language identifier (e.g., 'python', 'rust', 'javascript')"
                },
                "options": {
                    "type": "object",
                    "description": "Optional parsing options",
                    "properties": {
                        "extract_symbols": {
                            "type": "boolean",
                            "description": "Whether to extract symbol outline"
                        },
                        "extract_diagnostics": {
                            "type": "boolean",
                            "description": "Whether to extract syntax diagnostics"
                        },
                        "include_tree": {
                            "type": "boolean",
                            "description": "Whether to include full AST tree (default: True)"
                        }
                    }
                }
            },
            "required": ["source", "language"]
        }
    }
    """
    
    @agent.tool
    async def parse_code(
        context: RunContext,
        source: str,
        language: str,
        options: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Parse source code and extract AST, symbols, and diagnostics.
        
        Use this tool when you need to:
        - Parse code to understand its structure
        - Extract function/class definitions and their locations
        - Identify syntax errors or warnings
        - Get an AST representation for analysis
        
        Supported languages: python, rust, javascript, typescript, tsx, elixir
        
        Args:
            source: The source code string to parse
            language: Programming language identifier (e.g., "python", "rust", "js")
            options: Optional dict with:
                - extract_symbols: bool - Extract symbol outline (default: False)
                - extract_diagnostics: bool - Extract syntax diagnostics (default: False)
                - include_tree: bool - Include full AST tree (default: True)
                
        Returns:
            Dict with:
            - success: bool - Whether parsing succeeded
            - tree: dict | None - Serialized AST tree (if include_tree=True)
            - symbols: list - Extracted symbols (if extract_symbols=True)
            - diagnostics: list - Syntax diagnostics (if extract_diagnostics=True)
            - parse_time_ms: float - Time taken to parse
            - language: str - Normalized language identifier
            - errors: list - Error messages if parsing failed
        """
        options = options or {}
        extract_symbols = options.get("extract_symbols", False)
        extract_diagnostics = options.get("extract_diagnostics", False)
        include_tree = options.get("include_tree", True)
        
        start_time = time.time()
        normalized_lang = _normalize_language(language)
        
        # Check if language is supported
        if TURBO_PARSE_AVAILABLE and not is_language_supported(normalized_lang):
            return {
                "success": False,
                "tree": None,
                "symbols": [],
                "diagnostics": [],
                "parse_time_ms": (time.time() - start_time) * 1000,
                "language": normalized_lang,
                "errors": [{
                    "message": f"Language '{language}' is not supported",
                    "severity": "error",
                }],
            }
        
        try:
            # Parse the source code
            parse_result = _parse_source(source, normalized_lang)
            
            # Build the response
            result = {
                "success": parse_result.get("success", False),
                "tree": parse_result.get("tree") if include_tree else None,
                "symbols": [],
                "diagnostics": [],
                "parse_time_ms": parse_result.get("parse_time_ms", (time.time() - start_time) * 1000),
                "language": parse_result.get("language", normalized_lang),
                "errors": parse_result.get("errors", []),
            }
            
            # Extract symbols if requested
            if extract_symbols and TURBO_PARSE_AVAILABLE:
                try:
                    symbols_result = _extract_symbols(source, normalized_lang)
                    result["symbols"] = symbols_result.get("symbols", [])
                except Exception as e:
                    logger.warning(f"Symbol extraction failed: {e}")
                    result["symbols"] = []
            
            # Extract diagnostics if requested
            if extract_diagnostics and TURBO_PARSE_AVAILABLE:
                try:
                    diag_result = _extract_diagnostics(source, normalized_lang)
                    result["diagnostics"] = diag_result.get("diagnostics", [])
                except Exception as e:
                    logger.warning(f"Diagnostic extraction failed: {e}")
                    result["diagnostics"] = []
            
            return result
            
        except Exception as e:
            logger.exception("Parse code tool failed")
            return {
                "success": False,
                "tree": None,
                "symbols": [],
                "diagnostics": [],
                "parse_time_ms": (time.time() - start_time) * 1000,
                "language": normalized_lang,
                "errors": [{
                    "message": f"Parsing failed: {str(e)}",
                    "severity": "error",
                }],
            }


def _register_tools() -> List[Dict[str, Any]]:
    """Register turbo_parse tools.
    
    Returns a list of tool definitions for the register_tools callback.
    Currently registers the parse_code tool for high-performance code parsing.
    
    Returns:
        List of tool definitions with name and register_func.
    """
    return [
        {
            "name": "parse_code",
            "register_func": _register_parse_code_tool,
        }
    ]


# ============================================================================
# /parse Slash Command Implementation
# ============================================================================

def _parse_help() -> List[tuple[str, str]]:
    """Return help entries for the /parse command.
    
    Returns:
        List of (command, description) tuples for the /help menu.
    """
    return [
        ("parse", "Parse code files and extract AST, symbols, and diagnostics"),
        ("parse status", "Show parser health, version, and statistics"),
        ("parse parse_path <path>", "Parse a file or directory at the given path"),
        ("parse help", "Show detailed usage for the /parse command"),
    ]


def _get_language_from_extension(file_path: str) -> Optional[str]:
    """Infer language from file extension.
    
    Args:
        file_path: Path to the file
        
    Returns:
        Language identifier or None if unknown
    """
    ext = Path(file_path).suffix.lower()
    mapping = {
        ".py": "python",
        ".rs": "rust",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".ex": "elixir",
        ".exs": "elixir",
        ".heex": "elixir",
    }
    return mapping.get(ext)


def _format_status_output() -> str:
    """Format the status output for the /parse status command.
    
    Returns:
        Formatted status string
    """
    lines = ["🔍 Turbo Parse Status", "=" * 40]
    
    # Health check
    try:
        health = health_check()
        lines.append(f"Available: {'✅ Yes' if health.get('available') else '❌ No'}")
        lines.append(f"Version: {health.get('version', 'N/A')}")
        lines.append(f"Cache Available: {'✅ Yes' if health.get('cache_available') else '❌ No'}")
        
        # Supported languages
        langs = health.get('languages', [])
        if langs:
            lines.append(f"\nSupported Languages ({len(langs)}):")
            for lang in langs:
                lines.append(f"  • {lang}")
        else:
            lines.append("\nSupported Languages: None (module unavailable)")
    except Exception as e:
        lines.append(f"Health Check Error: {e}")
    
    # Stats
    try:
        stats_data = stats()
        lines.append(f"\n📊 Statistics:")
        lines.append(f"  Total Parses: {stats_data.get('total_parses', 0)}")
        lines.append(f"  Avg Parse Time: {stats_data.get('average_parse_time_ms', 0.0):.2f}ms")
        lines.append(f"  Cache Hits: {stats_data.get('cache_hits', 0)}")
        lines.append(f"  Cache Misses: {stats_data.get('cache_misses', 0)}")
        hit_ratio = stats_data.get('cache_hit_ratio', 0.0)
        lines.append(f"  Cache Hit Ratio: {hit_ratio:.1%}")
    except Exception as e:
        lines.append(f"\nStats Error: {e}")
    
    return "\n".join(lines)


def _format_parse_result(result: dict, file_path: str) -> str:
    """Format a single parse result for display.
    
    Args:
        result: Parse result dictionary
        file_path: Path to the file that was parsed
        
    Returns:
        Formatted result string
    """
    success = result.get("success", False)
    language = result.get("language", "unknown")
    parse_time = result.get("parse_time_ms", 0.0)
    errors = result.get("errors", [])
    
    status = "✅" if success else "❌"
    lines = [f"{status} {file_path} ({language}) - {parse_time:.2f}ms"]
    
    if errors:
        for err in errors:
            lines.append(f"  ⚠️  {err.get('message', str(err))}")
    
    # Show symbol count if available
    symbols = result.get("symbols", [])
    if symbols:
        lines.append(f"  📋 {len(symbols)} symbols extracted")
    
    return "\n".join(lines)


def _handle_parse_path(path_str: str) -> str:
    """Handle the /parse parse_path <path> subcommand.
    
    Args:
        path_str: Path to the file or directory to parse
        
    Returns:
        Formatted output string
    """
    path = Path(path_str).expanduser().resolve()
    
    if not path.exists():
        return f"❌ Path not found: {path_str}"
    
    if path.is_file():
        # Single file
        language = _get_language_from_extension(str(path))
        if language and not is_language_supported(language):
            language = None  # Let parser auto-detect or use unknown
        
        try:
            result = _parse_file(str(path), language)
            return _format_parse_result(result, str(path))
        except Exception as e:
            return f"❌ Error parsing {path}: {e}"
    
    elif path.is_dir():
        # Directory - find supported files
        supported_exts = {".py", ".rs", ".js", ".jsx", ".ts", ".tsx", ".ex", ".exs", ".heex"}
        files_to_parse = []
        
        for ext in supported_exts:
            files_to_parse.extend(path.rglob(f"*{ext}"))
        
        # Limit to avoid overwhelming output
        max_files = 20
        files_to_parse = files_to_parse[:max_files]
        total_found = len(list(path.rglob("*")))
        
        if not files_to_parse:
            return f"📁 No supported files found in {path}\nSupported: .py, .rs, .js, .jsx, .ts, .tsx, .ex, .exs, .heex"
        
        lines = [f"📁 Parsing directory: {path}", f"Found {len(files_to_parse)} files (showing first {max_files}):", ""]
        
        # Parse files using batch
        try:
            file_paths = [str(f) for f in files_to_parse]
            batch_result = _parse_files_batch(file_paths)
            
            results = batch_result.get("results", [])
            success_count = batch_result.get("success_count", 0)
            error_count = batch_result.get("error_count", 0)
            total_time = batch_result.get("total_time_ms", 0.0)
            
            for result in results:
                file_path = result.get("file_path", "unknown")
                lines.append(_format_parse_result(result, file_path))
            
            lines.append("")
            lines.append(f"✅ {success_count} succeeded, ❌ {error_count} failed")
            lines.append(f"⏱️  Total time: {total_time:.2f}ms")
            
            if total_found > max_files:
                lines.append(f"\n... and {total_found - max_files} more files not shown")
        
        except Exception as e:
            return f"❌ Error parsing directory: {e}"
        
        return "\n".join(lines)
    
    else:
        return f"❌ Invalid path: {path_str}"


def _handle_parse_help() -> str:
    """Handle the /parse help subcommand.
    
    Returns:
        Formatted help string
    """
    lines = [
        "📖 /parse Command Help",
        "=" * 40,
        "",
        "Parse code files and extract AST, symbols, and diagnostics.",
        "",
        "Usage:",
        "  /parse status              Show parser health and statistics",
        "  /parse parse_path <path>   Parse a file or directory",
        "  /parse help                Show this help message",
        "",
        "Supported Languages:",
    ]
    
    try:
        langs_info = supported_languages()
        langs = langs_info.get("languages", [])
        if langs:
            for lang in langs:
                lines.append(f"  • {lang}")
        else:
            lines.append("  (None - turbo_parse module not available)")
    except Exception:
        lines.append("  (Error fetching supported languages)")
    
    lines.extend([
        "",
        "Examples:",
        "  /parse status",
        "  /parse parse_path ./src/main.py",
        "  /parse parse_path ./lib",
    ])
    
    return "\n".join(lines)


def _handle_parse_command(command: str, name: str) -> Optional[bool | str]:
    """Handle the /parse custom slash command.
    
    Args:
        command: The full command string (e.g., "/parse status")
        name: The primary command name (e.g., "parse")
        
    Returns:
        - True if handled (no further processing needed)
        - str to display to the user
        - None if not handled (pass to other handlers)
    """
    if name != "parse":
        return None
    
    # Parse subcommand
    parts = command.split(maxsplit=2)
    subcommand = parts[1] if len(parts) > 1 else None
    
    if subcommand is None:
        # No subcommand - show brief help
        emit_info(_handle_parse_help())
        return True
    
    subcommand = subcommand.lower()
    
    if subcommand == "status":
        output = _format_status_output()
        emit_info(output)
        return True
    
    elif subcommand == "parse_path":
        if len(parts) < 3:
            emit_error("Usage: /parse parse_path <path>")
            emit_info("Example: /parse parse_path ./src/main.py")
            return True
        
        path = parts[2].strip()
        output = _handle_parse_path(path)
        emit_info(output)
        return True
    
    elif subcommand == "help":
        output = _handle_parse_help()
        emit_info(output)
        return True
    
    else:
        emit_error(f"Unknown subcommand: {subcommand}")
        emit_info("Run '/parse help' for available subcommands")
        return True


# ============================================================================
# Register all callbacks
# ============================================================================

register_callback("startup", _on_startup)
register_callback("register_tools", _register_tools)
register_callback("custom_command_help", _parse_help)
register_callback("custom_command", _handle_parse_command)

logger.debug("Turbo Parse plugin callbacks registered")
