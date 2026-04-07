"""Code Context Module — Symbol-augmented code exploration.

Provides CodeContext struct that wraps turbo_parse results and integrates
with existing code exploration flows. Offers symbol extraction, caching,
and hierarchical outline generation for enhanced code understanding.

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

## CodeExplorer Class

The CodeExplorer class provides comprehensive file and directory exploration:

```python
from code_puppy.code_context import CodeExplorer

explorer = CodeExplorer(enable_cache=True)

# Explore single file
context = explorer.explore_file("src/main.py")

# Explore directory
contexts = explorer.explore_directory("src/", pattern="*.py")

# Find symbol definitions
results = explorer.find_symbol_definitions("src/", "MyClass")
```

## Features

- Symbol extraction from Python, Rust, JavaScript, TypeScript, and Elixir
- Hierarchical outline with parent-child relationships
- Result caching for repeated access
- Optional content inclusion for memory efficiency
- Integration with existing file operations

## Architecture

- `CodeContext`: Complete context for a code file
- `FileOutline`: Hierarchical outline with symbols
- `SymbolInfo`: Individual symbol with metadata
- `CodeExplorer`: Main exploration interface with caching
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Union

from code_puppy.turbo_parse_bridge import (
    TURBO_PARSE_AVAILABLE,
    extract_symbols_from_file,
    get_folds_from_file,
    get_highlights_from_file,
    is_language_supported,
    parse_file,
)
from code_puppy.tools.file_operations import _read_file_sync

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Types and Protocols
# -----------------------------------------------------------------------------


class SymbolDict(Protocol):
    """Protocol for symbol dictionary structure."""

    name: str
    kind: str
    start_line: int
    end_line: int
    start_col: int
    end_col: int
    parent: Optional[str]
    docstring: Optional[str]


# -----------------------------------------------------------------------------
# Data Classes
# -----------------------------------------------------------------------------


@dataclass
class SymbolInfo:
    """Information about a code symbol (function, class, method, etc.)."""

    name: str
    kind: str
    start_line: int
    end_line: int
    start_col: int = 0
    end_col: int = 0
    parent: Optional[str] = None
    docstring: Optional[str] = None
    children: List[SymbolInfo] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SymbolInfo:
        """Create SymbolInfo from a dictionary."""
        return cls(
            name=data.get("name", ""),
            kind=data.get("kind", "unknown"),
            start_line=data.get("start_line", 0),
            end_line=data.get("end_line", 0),
            start_col=data.get("start_col", 0),
            end_col=data.get("end_col", 0),
            parent=data.get("parent"),
            docstring=data.get("docstring"),
            children=[],
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert SymbolInfo to a dictionary."""
        return {
            "name": self.name,
            "kind": self.kind,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "start_col": self.start_col,
            "end_col": self.end_col,
            "parent": self.parent,
            "docstring": self.docstring,
            "children": [c.to_dict() for c in self.children],
        }

    @property
    def line_range(self) -> tuple[int, int]:
        """Get the line range as a tuple."""
        return (self.start_line, self.end_line)

    @property
    def is_top_level(self) -> bool:
        """Check if this is a top-level symbol (no parent)."""
        return self.parent is None

    @property
    def size_lines(self) -> int:
        """Get the size of the symbol in lines."""
        return self.end_line - self.start_line + 1


@dataclass
class FileOutline:
    """Hierarchical outline of a source file."""

    language: str
    symbols: List[SymbolInfo]
    extraction_time_ms: float = 0.0
    success: bool = True
    errors: List[str] = field(default_factory=list)

    @property
    def top_level_symbols(self) -> List[SymbolInfo]:
        """Get only top-level symbols."""
        return [s for s in self.symbols if s.is_top_level]

    @property
    def classes(self) -> List[SymbolInfo]:
        """Get all class-like symbols."""
        return [
            s
            for s in self.symbols
            if s.kind in ("class", "struct", "interface", "trait", "enum")
        ]

    @property
    def functions(self) -> List[SymbolInfo]:
        """Get all function-like symbols."""
        return [s for s in self.symbols if s.kind in ("function", "method")]

    @property
    def imports(self) -> List[SymbolInfo]:
        """Get all import symbols."""
        return [s for s in self.symbols if s.kind == "import"]

    def get_symbol_by_name(self, name: str) -> Optional[SymbolInfo]:
        """Find a symbol by its name."""
        for symbol in self.symbols:
            if symbol.name == name:
                return symbol
        return None

    def get_symbols_in_range(self, start_line: int, end_line: int) -> List[SymbolInfo]:
        """Get all symbols within a line range."""
        return [
            s
            for s in self.symbols
            if s.start_line >= start_line and s.end_line <= end_line
        ]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "language": self.language,
            "symbols": [s.to_dict() for s in self.symbols],
            "extraction_time_ms": self.extraction_time_ms,
            "success": self.success,
            "errors": self.errors,
        }


@dataclass
class CodeContext:
    """Complete context for a code file including symbols, content, and metadata."""

    file_path: str
    content: Optional[str] = None
    language: Optional[str] = None
    outline: Optional[FileOutline] = None
    file_size: int = 0
    num_lines: int = 0
    num_tokens: int = 0
    parse_time_ms: float = 0.0
    has_errors: bool = False
    error_message: Optional[str] = None
    @property
    def is_parsed(self) -> bool:
        """Check if the file was successfully parsed."""
        return self.outline is not None and self.outline.success

    @property
    def symbol_count(self) -> int:
        """Get the total number of symbols."""
        return len(self.outline.symbols) if self.outline else 0

    def get_summary(self) -> str:
        """Get a human-readable summary of the code context."""
        lines = [
            f"📄 {self.file_path}",
            f"   Language: {self.language or 'unknown'}",
            f"   Lines: {self.num_lines}, Tokens: {self.num_tokens}",
        ]

        if self.outline:
            lines.append(f"   Symbols: {len(self.outline.symbols)}")
            if self.outline.classes:
                lines.append(f"   Classes: {len(self.outline.classes)}")
            if self.outline.functions:
                lines.append(f"   Functions: {len(self.outline.functions)}")

        if self.has_errors and self.error_message:
            lines.append(f"   ⚠️ Error: {self.error_message}")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "file_path": self.file_path,
            "content": self.content,
            "language": self.language,
            "outline": self.outline.to_dict() if self.outline else None,
            "file_size": self.file_size,
            "num_lines": self.num_lines,
            "num_tokens": self.num_tokens,
            "parse_time_ms": self.parse_time_ms,
            "has_errors": self.has_errors,
            "error_message": self.error_message,
        }


# -----------------------------------------------------------------------------
# Code Explorer Class
# -----------------------------------------------------------------------------


class CodeExplorer:
    """Enhanced code exploration with symbol extraction and caching.

    This class provides methods to explore files and directories with
    symbol-level understanding, integrating turbo_parse capabilities
    into the code exploration flow.
    """

    def __init__(self, enable_cache: bool = True):
        """Initialize the CodeExplorer.

        Args:
            enable_cache: Whether to enable result caching (default: True)
        """
        self.enable_cache = enable_cache
        self._cache: Dict[str, CodeContext] = {}
        self._parse_count = 0
        self._cache_hits = 0

    def _detect_language(self, file_path: str) -> Optional[str]:
        """Detect programming language from file extension."""
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

    def _is_supported_file(self, file_path: str) -> bool:
        """Check if a file has a supported extension.

        A file is considered supported if its extension maps to a language
        we can detect, regardless of whether turbo_parse is available.
        This allows exploration to work even without the Rust module.
        """
        return self._detect_language(file_path) is not None

    def _build_symbol_hierarchy(
        self, flat_symbols: List[SymbolInfo]
    ) -> List[SymbolInfo]:
        """Build parent-child hierarchy from flat symbol list."""
        if not flat_symbols:
            return []

        # Sort by position, longer ranges first for proper nesting
        sorted_symbols = sorted(
            flat_symbols,
            key=lambda s: (s.start_line, s.start_col, -s.size_lines),
        )

        root_items: List[SymbolInfo] = []
        stack: List[SymbolInfo] = []

        for symbol in sorted_symbols:
            # Find parent by checking containment
            while stack:
                parent = stack[-1]
                if self._is_symbol_contained(symbol, parent):
                    symbol.parent = parent.name
                    parent.children.append(symbol)
                    break
                else:
                    stack.pop()
            else:
                # No parent found, add to root
                root_items.append(symbol)

            # Push this symbol to stack
            stack.append(symbol)

        return root_items

    def _is_symbol_contained(self, child: SymbolInfo, parent: SymbolInfo) -> bool:
        """Check if child symbol is contained within parent symbol."""
        # Strict containment: child starts after parent starts and ends before parent ends
        if child.start_line > parent.start_line and child.end_line <= parent.end_line:
            return True
        # Same start but child ends before parent
        if child.start_line == parent.start_line and child.end_line < parent.end_line:
            return True
        return False

    def explore_file(
        self,
        file_path: str,
        include_content: bool = True,
        force_refresh: bool = False,
    ) -> CodeContext:
        """Explore a single file and return its code context.

        Args:
            file_path: Path to the file to explore
            include_content: Whether to include file content in result
            force_refresh: Whether to bypass cache and re-parse

        Returns:
            CodeContext with symbols, outline, and metadata
        """
        abs_path = str(Path(file_path).resolve())

        # Check cache first
        if self.enable_cache and not force_refresh and abs_path in self._cache:
            cached = self._cache[abs_path]
            # Update cache hit if content not needed
            if not include_content or cached.content is not None:
                self._cache_hits += 1
                logger.debug(f"Cache hit for {abs_path}")
                return cached

        start_time = time.time()
        self._parse_count += 1

        # Initialize context
        context = CodeContext(file_path=abs_path)

        # Detect language
        language = self._detect_language(abs_path)
        context.language = language

        # Read file content
        content, num_tokens, error = _read_file_sync(abs_path)
        if error:
            context.has_errors = True
            context.error_message = error
            return context

        context.content = content if include_content else None
        context.num_tokens = num_tokens
        context.num_lines = content.count("\n") + 1 if content else 0

        # Get file size
        try:
            context.file_size = Path(abs_path).stat().st_size
        except OSError:
            pass

        # Extract symbols if language is supported
        if language and TURBO_PARSE_AVAILABLE and is_language_supported(language):
            try:
                symbol_result = extract_symbols_from_file(abs_path, language)

                if symbol_result.get("success"):
                    raw_symbols = symbol_result.get("symbols", [])
                    symbol_infos = [SymbolInfo.from_dict(s) for s in raw_symbols]

                    # Build hierarchy
                    hierarchical = self._build_symbol_hierarchy(symbol_infos)

                    context.outline = FileOutline(
                        language=language,
                        symbols=hierarchical,
                        extraction_time_ms=symbol_result.get("extraction_time_ms", 0.0),
                        success=True,
                    )
                else:
                    errors = symbol_result.get("errors", [])
                    context.has_errors = True
                    context.error_message = "; ".join(str(e) for e in errors)
                    context.outline = FileOutline(
                        language=language,
                        symbols=[],
                        success=False,
                        errors=[str(e) for e in errors],
                    )
            except Exception as e:
                logger.warning(f"Symbol extraction failed for {abs_path}: {e}")
                context.has_errors = True
                context.error_message = f"Symbol extraction failed: {e}"
        else:
            # Language not supported or turbo_parse not available
            context.outline = FileOutline(
                language=language or "unknown",
                symbols=[],
                success=False,
                errors=["Symbol extraction not available for this language"],
            )

        # Cache the result
        if self.enable_cache:
            self._cache[abs_path] = context

        return context

    def explore_directory(
        self,
        directory: str,
        pattern: str = "*",
        recursive: bool = True,
        max_files: int = 50,
    ) -> List[CodeContext]:
        """Explore a directory and return code contexts for all supported files.

        Args:
            directory: Path to the directory to explore
            pattern: File pattern to match (e.g., "*.py")
            recursive: Whether to search recursively
            max_files: Maximum number of files to process

        Returns:
            List of CodeContext objects
        """
        dir_path = Path(directory).resolve()
        contexts: List[CodeContext] = []

        if not dir_path.exists():
            logger.error(f"Directory not found: {directory}")
            return contexts

        if not dir_path.is_dir():
            logger.error(f"Not a directory: {directory}")
            return contexts

        # Find all matching files
        if recursive:
            files = list(dir_path.rglob(pattern))
        else:
            files = list(dir_path.glob(pattern))

        # Filter to supported files and limit count
        supported_files = [f for f in files if f.is_file() and self._is_supported_file(str(f))]
        files_to_process = supported_files[:max_files]

        logger.info(
            f"Exploring {len(files_to_process)} files in {directory} "
            f"({len(supported_files)} total supported files found)"
        )

        for file_path in files_to_process:
            try:
                context = self.explore_file(str(file_path), include_content=False)
                contexts.append(context)
            except Exception as e:
                logger.warning(f"Failed to explore {file_path}: {e}")

        return contexts

    def get_outline(self, file_path: str, max_depth: Optional[int] = None) -> FileOutline:
        """Get the hierarchical outline of a file.

        Args:
            file_path: Path to the file
            max_depth: Maximum depth for nested symbols (None for unlimited)

        Returns:
            FileOutline with hierarchical symbol structure
        """
        context = self.explore_file(file_path, include_content=False)

        if not context.outline:
            return FileOutline(
                language="unknown",
                symbols=[],
                success=False,
                errors=["Failed to extract outline"],
            )

        # Apply depth limit if specified
        if max_depth is not None and context.outline.symbols:
            context.outline.symbols = self._limit_depth(
                context.outline.symbols, max_depth
            )

        return context.outline

    def _limit_depth(
        self, symbols: List[SymbolInfo], max_depth: int, current_depth: int = 1
    ) -> List[SymbolInfo]:
        """Limit the depth of symbol hierarchy."""
        if current_depth >= max_depth:
            # Remove all children at this depth
            for symbol in symbols:
                symbol.children = []
            return symbols

        # Recursively limit children
        for symbol in symbols:
            if symbol.children:
                symbol.children = self._limit_depth(
                    symbol.children, max_depth, current_depth + 1
                )

        return symbols

    def invalidate_cache(self, file_path: Optional[str] = None) -> None:
        """Invalidate the cache for a specific file or all files.

        Args:
            file_path: Specific file to invalidate, or None to clear all
        """
        if file_path:
            abs_path = str(Path(file_path).resolve())
            if abs_path in self._cache:
                del self._cache[abs_path]
                logger.debug(f"Cache invalidated for {abs_path}")
        else:
            self._cache.clear()
            logger.debug("Cache cleared for all files")

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        return {
            "cache_size": len(self._cache),
            "parse_count": self._parse_count,
            "cache_hits": self._cache_hits,
            "hit_ratio": self._cache_hits / max(1, self._cache_hits + len(self._cache)),
        }

    def find_symbol_definitions(
        self, directory: str, symbol_name: str
    ) -> List[tuple[str, SymbolInfo]]:
        """Find all definitions of a symbol name across a directory.

        Args:
            directory: Directory to search
            symbol_name: Name of the symbol to find

        Returns:
            List of (file_path, symbol_info) tuples
        """
        results: List[tuple[str, SymbolInfo]] = []

        contexts = self.explore_directory(
            directory, pattern="*", recursive=True, max_files=100
        )

        for context in contexts:
            if context.outline:
                for symbol in context.outline.symbols:
                    if symbol.name == symbol_name:
                        results.append((context.file_path, symbol))

        return results


# -----------------------------------------------------------------------------
# Module-Level Functions
# -----------------------------------------------------------------------------

# Global explorer instance for module-level functions
_global_explorer = CodeExplorer(enable_cache=True)


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
        content, num_tokens, error = _read_file_sync(file_path)
        return CodeContext(
            file_path=file_path,
            content=content if include_content else None,
            num_tokens=num_tokens,
            num_lines=content.count("\n") + 1 if content else 0,
            has_errors=error is not None,
            error_message=error,
        )

    return _global_explorer.explore_file(file_path, include_content=include_content)


def get_file_outline(file_path: str, max_depth: Optional[int] = None) -> FileOutline:
    """Get the hierarchical outline of a file.

    Args:
        file_path: Path to the file
        max_depth: Maximum depth for nested symbols (None for unlimited)

    Returns:
        FileOutline with hierarchical symbol structure
    """
    return _global_explorer.get_outline(file_path, max_depth)


def explore_directory(
    directory: str,
    pattern: str = "*",
    recursive: bool = True,
    max_files: int = 50,
) -> List[CodeContext]:
    """Explore a directory and return code contexts for supported files.

    Args:
        directory: Path to the directory
        pattern: File pattern to match
        recursive: Whether to search recursively
        max_files: Maximum number of files to process

    Returns:
        List of CodeContext objects
    """
    return _global_explorer.explore_directory(
        directory, pattern, recursive, max_files
    )


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


# -----------------------------------------------------------------------------
# Integration Helpers
# -----------------------------------------------------------------------------


def enhance_read_file_result(
    file_path: str,
    content: str,
    num_tokens: int,
    with_symbols: bool = False,
) -> dict[str, Any]:
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
    result: dict[str, Any] = {
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
    """Get the global CodeExplorer instance."""
    return _global_explorer
