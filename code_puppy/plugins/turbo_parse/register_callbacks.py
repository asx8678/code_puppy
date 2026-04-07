"""Turbo Parse Plugin — Callback Registration.

Registers the turbo_parse parsing system with code_puppy's callback hooks:
- startup: Check turbo_parse Rust module availability and log status
- register_tools: Register the parse_code tool for code parsing operations

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
"""

import logging
import time
from typing import Any, Dict, List

from pydantic_ai import RunContext

from code_puppy.callbacks import register_callback
from code_puppy.plugins.turbo_parse import is_turbo_parse_available
from code_puppy.turbo_parse_bridge import (
    parse_source as _parse_source,
    extract_symbols as _extract_symbols,
    extract_syntax_diagnostics as _extract_diagnostics,
    is_language_supported,
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


# Register all callbacks
register_callback("startup", _on_startup)
register_callback("register_tools", _register_tools)

logger.debug("Turbo Parse plugin callbacks registered")
