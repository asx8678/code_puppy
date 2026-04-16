"""Code Explorer — File and directory exploration with symbol extraction and caching."""

import logging
from pathlib import Path
from typing import Any

from code_puppy.code_context.models import CodeContext, FileOutline, SymbolInfo
from code_puppy.tools.file_operations import _read_file_sync
# bd-68: Route parse operations through NativeBackend (single native boundary)
from code_puppy.native_backend import NativeBackend

# Derive availability from NativeBackend capability check
TURBO_PARSE_AVAILABLE = NativeBackend.is_active(NativeBackend.Capabilities.PARSE)
from code_puppy.utils.symbol_hierarchy import build_symbol_hierarchy

logger = logging.getLogger(__name__)


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
        self._cache: dict[str, CodeContext] = {}
        self._parse_count = 0
        self._cache_hits = 0
        self._cache_misses = 0

    def _detect_language(self, file_path: str) -> str | None:
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

        self._parse_count += 1
        self._cache_misses += 1

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
        if language and TURBO_PARSE_AVAILABLE and NativeBackend.is_language_supported(language):
            try:
                # bd-68: Use NativeBackend.extract_symbols with already-loaded content
                raw_symbols = NativeBackend.extract_symbols(content, language)
                symbol_result = {
                    "success": bool(raw_symbols),
                    "symbols": raw_symbols if isinstance(raw_symbols, list) else [],
                    "extraction_time_ms": 0.0,
                }

                if symbol_result.get("success"):
                    raw_symbols = symbol_result.get("symbols", [])
                    symbol_infos = [SymbolInfo.from_dict(s) for s in raw_symbols]

                    # Build hierarchy using shared utility
                    hierarchical = build_symbol_hierarchy(symbol_infos)

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
    ) -> list[CodeContext]:
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
        contexts: list[CodeContext] = []

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
        supported_files = [
            f for f in files if f.is_file() and self._is_supported_file(str(f))
        ]
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

    def get_outline(
        self, file_path: str, max_depth: int | None = None
    ) -> FileOutline:
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
        self, symbols: list[SymbolInfo], max_depth: int, current_depth: int = 1
    ) -> list[SymbolInfo]:
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

    def invalidate_cache(self, file_path: str | None = None) -> None:
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
        total_requests = self._cache_hits + self._cache_misses
        return {
            "cache_size": len(self._cache),
            "parse_count": self._parse_count,
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "hit_ratio": self._cache_hits / max(1, total_requests),
        }

    def find_symbol_definitions(
        self, directory: str, symbol_name: str
    ) -> list[tuple[str, SymbolInfo]]:
        """Find all definitions of a symbol name across a directory.

        Args:
            directory: Directory to search
            symbol_name: Name of the symbol to find

        Returns:
            List of (file_path, symbol_info) tuples
        """
        results: list[tuple[str, SymbolInfo]] = []

        contexts = self.explore_directory(
            directory, pattern="*", recursive=True, max_files=100
        )

        for context in contexts:
            if context.outline:
                for symbol in context.outline.symbols:
                    if symbol.name == symbol_name:
                        results.append((context.file_path, symbol))

        return results
