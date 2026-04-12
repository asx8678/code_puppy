"""Code Context Package — Symbol-augmented code exploration.

This package provides comprehensive code exploration capabilities:
- SymbolInfo, FileOutline, CodeContext: Data models
- CodeExplorer: File and directory exploration with caching
- get_code_context, get_file_outline, explore_directory: Convenience functions

## Quick Start

```python
from code_puppy.code_context import get_code_context, format_outline

# Get context for a file
context = get_code_context("src/main.py", include_content=False)
print(context.get_summary())

# Get file outline
outline = get_file_outline("src/main.py")
print(format_outline(outline))
```
"""

import threading

from code_puppy.code_context.models import CodeContext, FileOutline, SymbolInfo
from code_puppy.code_context.explorer import CodeExplorer

# Global explorer instance for module-level functions (lazy-init singleton)
_global_explorer: CodeExplorer | None = None
_explorer_lock = threading.Lock()


def get_code_context(
    file_path: str,
    include_content: bool = True,
    with_symbols: bool = True,
) -> CodeContext:
    """Get code context for a file.

    This is the main entry point for accessing code context information.
    It wraps the turbo_parse results and provides a convenient interface
    for code exploration.

    Args:
        file_path: Path to the file to analyze
        include_content: Whether to include file content in the result
        with_symbols: Whether to extract symbols (requires turbo_parse)

    Returns:
        CodeContext object with file information and symbols

    Example:
        >>> context = get_code_context("src/main.py")
        >>> print(context.get_summary())
        >>> for symbol in context.outline.functions:
        ...     print(f"Function: {symbol.name} at line {symbol.start_line}")
    """
    if not with_symbols:
        # Return context without symbol extraction
        from code_puppy.tools.file_operations import _read_file_sync

        content, num_tokens, error = _read_file_sync(file_path)
        return CodeContext(
            file_path=file_path,
            content=content if include_content else None,
            num_tokens=num_tokens,
            num_lines=content.count("\n") + 1 if content else 0,
            has_errors=error is not None,
            error_message=error,
        )

    return get_explorer_instance().explore_file(file_path, include_content=include_content)


def get_file_outline(file_path: str, max_depth: int | None = None) -> FileOutline:
    """Get the hierarchical outline of a file.

    Args:
        file_path: Path to the file
        max_depth: Maximum depth for nested symbols (None for unlimited)

    Returns:
        FileOutline with hierarchical symbol structure
    """
    return get_explorer_instance().get_outline(file_path, max_depth)


def explore_directory(
    directory: str,
    pattern: str = "*",
    recursive: bool = True,
    max_files: int = 50,
) -> list[CodeContext]:
    """Explore a directory and return code contexts for supported files.

    Args:
        directory: Path to the directory
        pattern: File pattern to match
        recursive: Whether to search recursively
        max_files: Maximum number of files to process

    Returns:
        List of CodeContext objects
    """
    return get_explorer_instance().explore_directory(directory, pattern, recursive, max_files)


def format_outline(outline: FileOutline, show_lines: bool = True) -> str:
    """Format a file outline as a human-readable string.

    Args:
        outline: The outline to format
        show_lines: Whether to show line numbers

    Returns:
        Formatted outline string
    """
    lines = [f"📋 Outline ({outline.language}):"]

    def format_symbol(symbol: SymbolInfo, indent: int = 0) -> str:
        prefix = "  " * indent
        kind_icon = {
            "class": "🏛️",
            "struct": "🏛️",
            "interface": "🔷",
            "trait": "🔷",
            "function": "⚡",
            "method": "🔹",
            "import": "📦",
            "variable": "📌",
            "enum": "🔢",
            "module": "📂",
        }.get(symbol.kind, "•")

        line_info = f" (L{symbol.start_line})" if show_lines else ""
        result = f"{prefix}{kind_icon} {symbol.name}{line_info}"

        for child in symbol.children:
            result += "\n" + format_symbol(child, indent + 1)

        return result

    for symbol in outline.symbols:
        lines.append(format_symbol(symbol))

    return "\n".join(lines)


def enhance_read_file_result(
    file_path: str,
    content: str,
    num_tokens: int,
    with_symbols: bool = False,
) -> dict[str, any]:
    """Enhance a file read result with symbol information.

    This helper function can be used to add symbol information to
    existing file reading tools.

    Args:
        file_path: Path to the file that was read
        content: File content
        num_tokens: Token count
        with_symbols: Whether to include symbols

    Returns:
        Enhanced result dictionary with optional symbol info
    """
    import logging

    logger = logging.getLogger(__name__)

    result: dict[str, any] = {
        "content": content,
        "num_tokens": num_tokens,
        "file_path": file_path,
    }

    if with_symbols:
        try:
            outline = get_file_outline(file_path)
            result["outline"] = outline.to_dict()
            result["symbols_available"] = outline.success
        except Exception as e:
            logger.warning(f"Failed to enhance read_file with symbols: {e}")
            result["symbols_available"] = False
            result["symbols_error"] = str(e)

    return result


def get_explorer_instance() -> CodeExplorer:
    """Get the global CodeExplorer singleton (double-checked locking)."""
    global _global_explorer
    if _global_explorer is None:
        with _explorer_lock:
            if _global_explorer is None:
                _global_explorer = CodeExplorer(enable_cache=True)
    return _global_explorer


__all__ = [
    "CodeContext",
    "CodeExplorer",
    "FileOutline",
    "SymbolInfo",
    "enhance_read_file_result",
    "explore_directory",
    "format_outline",
    "get_code_context",
    "get_explorer_instance",
    "get_file_outline",
]
