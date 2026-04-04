"""Tree-sitter AST parser for code intelligence.

Provides incremental parsing for Python, JavaScript/TypeScript, Rust, and Go.
Builds a symbol graph from AST nodes.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from tree_sitter import Language, Parser, Tree

if TYPE_CHECKING:
    from .symbol_graph import SymbolGraph

logger = logging.getLogger(__name__)

# Language module cache
_language_cache: dict[str, Language] = {}


def _get_language(language_name: str) -> Optional[Language]:
    """Get or load a tree-sitter language.

    Args:
        language_name: One of "python", "javascript", "typescript", "rust", "go".

    Returns:
        Language object or None if not available.
    """
    if language_name in _language_cache:
        return _language_cache[language_name]

    try:
        if language_name == "python":
            import tree_sitter_python
            lang = Language(tree_sitter_python.language())
        elif language_name == "javascript":
            import tree_sitter_javascript
            lang = Language(tree_sitter_javascript.language())
        elif language_name == "typescript":
            import tree_sitter_typescript
            lang = Language(tree_sitter_typescript.language_typescript())
        elif language_name == "rust":
            import tree_sitter_rust
            lang = Language(tree_sitter_rust.language())
        elif language_name == "go":
            import tree_sitter_go
            lang = Language(tree_sitter_go.language())
        else:
            logger.warning(f"Unsupported language: {language_name}")
            return None

        _language_cache[language_name] = lang
        return lang

    except ImportError as e:
        logger.debug(f"Language {language_name} not available: {e}")
        return None


# File extension to language mapping
_EXTENSION_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".rs": "rust",
    ".go": "go",
}


def get_language_for_file(file_path: str | Path) -> Optional[str]:
    """Determine language from file extension.

    Args:
        file_path: Path to the file.

    Returns:
        Language name or None if not supported.
    """
    ext = Path(file_path).suffix.lower()
    return _EXTENSION_MAP.get(ext)


def get_parser_for_file(file_path: str | Path) -> Optional[TreeSitterParser]:
    """Create a parser for a file based on its extension.

    Args:
        file_path: Path to the file.

    Returns:
        Configured TreeSitterParser or None if language not supported.
    """
    lang_name = get_language_for_file(file_path)
    if not lang_name:
        return None

    language = _get_language(lang_name)
    if not language:
        return None

    return TreeSitterParser(language, lang_name)


class TreeSitterParser:
    """Tree-sitter parser wrapper for extracting symbols.

    Parses source code and extracts symbols to populate a SymbolGraph.
    Language-specific extraction is delegated to language modules.
    """

    def __init__(self, language: Language, language_name: str):
        """Initialize parser with a language.

        Args:
            language: Tree-sitter Language object.
            language_name: Name of the language.
        """
        self.language = language
        self.language_name = language_name
        self._parser = Parser(language)

    def parse(self, source: str | bytes) -> Tree:
        """Parse source code into an AST.

        Args:
            source: Source code as string or bytes.

        Returns:
            Tree-sitter Tree object.
        """
        if isinstance(source, str):
            source = source.encode("utf-8")
        return self._parser.parse(source)

    def extract_symbols(
        self,
        source: str | bytes,
        file_path: str,
        graph: SymbolGraph,
    ) -> int:
        """Extract symbols from source and add to graph.

        Args:
            source: Source code.
            file_path: Path to the file (for location info).
            graph: SymbolGraph to populate.

        Returns:
            Number of symbols extracted.
        """
        tree = self.parse(source)

        # Delegate to language-specific extractor
        from . import languages

        extractor = languages.get_extractor(self.language_name)
        if not extractor:
            logger.warning(f"No extractor available for {self.language_name}")
            return 0

        count = extractor.extract(tree, source, file_path, graph)
        logger.debug(f"Extracted {count} symbols from {file_path}")
        return count

    def parse_file(
        self,
        file_path: str | Path,
        graph: SymbolGraph,
    ) -> int:
        """Parse a file and extract symbols.

        Args:
            file_path: Path to the file.
            graph: SymbolGraph to populate.

        Returns:
            Number of symbols extracted, or 0 if file cannot be read.
        """
        path = Path(file_path)
        if not path.exists():
            logger.warning(f"File not found: {file_path}")
            return 0

        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            logger.warning(f"Failed to read {file_path}: {e}")
            return 0

        return self.extract_symbols(source, str(path.resolve()), graph)


class IncrementalParser:
    """Incremental parser with change tracking.

    Maintains a symbol graph and only reparses files that have changed.
    """

    def __init__(self, graph: Optional[SymbolGraph] = None):
        """Initialize the incremental parser.

        Args:
            graph: Optional SymbolGraph to use (creates new one if None).
        """
        from .change_tracker import ChangeTracker
        from .symbol_graph import SymbolGraph

        self.graph = graph or SymbolGraph()
        self.change_tracker = ChangeTracker()

    def parse_file(self, file_path: str | Path) -> bool:
        """Parse a file if it has changed.

        Args:
            file_path: Path to the file.

        Returns:
            True if file was parsed (changed or new), False if unchanged.
        """
        path = Path(file_path)
        if not path.exists():
            return False

        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            logger.warning(f"Failed to read {file_path}: {e}")
            return False

        # Check if changed
        if not self.change_tracker.has_changed(file_path, source):
            return False

        # Get appropriate parser
        parser = get_parser_for_file(file_path)
        if not parser:
            logger.debug(f"No parser available for {file_path}")
            return False

        # Remove old symbols for this file
        self.graph.remove_file(file_path)

        # Parse and extract
        parser.extract_symbols(source, str(path.resolve()), self.graph)

        # Update hash
        self.change_tracker.update_hash(file_path, source)

        return True

    def remove_file(self, file_path: str | Path) -> None:
        """Remove a file from the graph and change tracker.

        Args:
            file_path: Path to the file.
        """
        self.graph.remove_file(file_path)
        self.change_tracker.remove_file(file_path)

    def get_stats(self) -> dict:
        """Get statistics about the parser state.

        Returns:
            Dict with graph stats and change tracker stats.
        """
        return {
            "graph": self.graph.get_stats(),
            "change_tracker": self.change_tracker.get_stats(),
        }

    def clear(self) -> None:
        """Clear the graph and change tracker."""
        self.graph.clear()
        self.change_tracker.clear()
