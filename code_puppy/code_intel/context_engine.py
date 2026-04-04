"""Context engine for selective code context injection.

The ContextEngine orchestrates:
1. Symbol discovery (from conversation, file system)
2. Relevance scoring
3. Code neighborhood building
4. Prompt injection via load_prompt hook
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .relevance_scorer import RelevanceScore

logger = logging.getLogger(__name__)


@dataclass
class SymbolInfo:
    """Information about a code symbol."""

    name: str
    symbol_type: str  # function, class, method, variable, etc.
    file_path: Path
    line_number: int | None = None
    source_code: str | None = None
    calls: list[str] = field(default_factory=list)
    called_by: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    docstring: str | None = None


@dataclass
class ContextEngineConfig:
    """Configuration for the context engine."""

    enabled: bool = True
    max_symbols_per_prompt: int = 5
    max_chars_per_prompt: int = 6000
    min_relevance_score: float = 3.0
    include_source_code: bool = True
    include_related_symbols: bool = True
    scan_recent_files: bool = True
    recent_files_lookback: int = 10


class ContextEngine:
    """Main engine for building selective code context."""

    def __init__(self, config: ContextEngineConfig | None = None):
        self.config = config or ContextEngineConfig()
        self._symbol_cache: dict[str, SymbolInfo] = {}
        self._conversation_history: list[str] = []
        self._recent_files: list[str] = []
        self._initialized = False

    def initialize(self) -> bool:
        """Initialize the context engine.

        Returns:
            True if initialized successfully, False otherwise
        """
        if self._initialized:
            return True

        if not self.config.enabled:
            logger.debug("Context engine is disabled")
            return False

        self._initialized = True
        logger.debug("Context engine initialized")
        return True

    def add_conversation_turn(self, user_message: str, assistant_response: str | None = None) -> None:
        """Add a conversation turn for context analysis.

        Args:
            user_message: The user's message
            assistant_response: Optional assistant response
        """
        self._conversation_history.append(user_message)
        if assistant_response:
            self._conversation_history.append(assistant_response)

        # Keep only recent history
        max_history = 5
        if len(self._conversation_history) > max_history * 2:
            self._conversation_history = self._conversation_history[-(max_history * 2) :]

    def set_recent_files(self, file_paths: list[str]) -> None:
        """Set the list of recently modified files.

        Args:
            file_paths: List of file paths
        """
        self._recent_files = file_paths[: self.config.recent_files_lookback]

    def build_context(self, conversation_text: str | None = None) -> str | None:
        """Build code context for prompt injection.

        Analyzes conversation and recent files to find relevant code symbols,
        scores them by relevance, and formats the top matches.

        Args:
            conversation_text: Optional conversation text to analyze.
                If not provided, uses recent conversation history.

        Returns:
            Formatted context string for prompt injection, or None if no relevant context
        """
        if not self._initialized or not self.config.enabled:
            return None

        # Get text to analyze
        text = conversation_text or "\n".join(self._conversation_history[-3:])
        if not text or len(text) < 20:
            logger.debug("No conversation text to analyze")
            return None

        # Discover symbols mentioned in conversation
        symbols = self._discover_symbols(text)
        if not symbols:
            logger.debug("No symbols discovered in conversation")
            return None

        # Score symbols by relevance
        from .relevance_scorer import RelevanceScorer, ScoringFactors

        scorer = RelevanceScorer(ScoringFactors())
        scorer.set_conversation_context(text, self._recent_files)
        scored = scorer.score_symbols(symbols)

        # Filter by minimum relevance
        relevant = [s for s in scored if s.score >= self.config.min_relevance_score]
        if not relevant:
            logger.debug("No symbols above relevance threshold")
            return None

        # Limit to top N
        top_symbols = relevant[: self.config.max_symbols_per_prompt]

        # Get full symbol info for each
        symbol_info_list = [
            (self._symbol_cache.get(s.symbol_name) or self._fetch_symbol_info(s.symbol_name), s)
            for s in top_symbols
        ]
        # Filter out any None values from fetch failures
        symbol_info_list = [(info, score) for info, score in symbol_info_list if info is not None]

        if not symbol_info_list:
            return None

        # Format for prompt
        from .formatters import CodeFormatter

        formatter = CodeFormatter(
            max_chars_per_symbol=self.config.max_chars_per_prompt // self.config.max_symbols_per_prompt,
            max_total_chars=self.config.max_chars_per_prompt,
            include_related=self.config.include_related_symbols,
        )

        if self.config.include_source_code:
            result = formatter.format_symbols_for_prompt(symbol_info_list)
        else:
            result = formatter.format_simple_list(symbol_info_list)

        if result:
            logger.debug(
                f"Built context with {len(symbol_info_list)} symbols, "
                f"{len(result)} chars"
            )

        return result

    def _discover_symbols(self, text: str) -> list[SymbolInfo]:
        """Discover code symbols mentioned in text.

        This extracts potential symbol names from the conversation
        and attempts to locate them in the codebase.
        """
        symbols = []
        found_names = set()

        # Extract potential symbol names
        names = self._extract_symbol_names(text)

        for name in names:
            if name in found_names:
                continue
            found_names.add(name)

            # Try to find symbol in codebase
            symbol = self._find_symbol_in_codebase(name)
            if symbol:
                symbols.append(symbol)
                self._symbol_cache[name] = symbol

        return symbols

    def _extract_symbol_names(self, text: str) -> set[str]:
        """Extract potential symbol names from text.

        Looks for:
        - Function/method names (followed by parentheses)
        - Class names (CamelCase)
        - File names
        - Explicit mentions
        """
        names = set()
        text_lower = text.lower()

        # Function calls
        func_pattern = r'\b([a-z_][a-z0-9_]*)\s*\('
        for match in re.finditer(func_pattern, text_lower):
            names.add(match.group(1))

        # Class names (CamelCase)
        class_pattern = r'\b([A-Z][a-zA-Z0-9_]*[a-z][a-zA-Z0-9_]*)\b'
        for match in re.finditer(class_pattern, text):
            name = match.group(1)
            if name not in {"True", "False", "None", "Http", "Json", "Api", "Url", "Html", "Xml", "Csv"}:
                names.add(name)

        # Explicit mentions
        patterns = [
            r'the\s+([a-z_][a-z0-9_]*)\s+(?:function|method)',
            r'the\s+([A-Z][a-zA-Z0-9_]*)\s+class',
            r'(?:function|method|def)\s+([a-z_][a-z0-9_]*)',
            r'class\s+([A-Z][a-zA-Z0-9_]*)',
            r'call\s+([a-z_][a-z0-9_]*)',
            r'import\s+([a-z_][a-z0-9_.]*)',
            r'from\s+([a-z_][a-z0-9_.]*)',
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, text_lower):
                names.add(match.group(1).split(".")[-1])  # Get last part of import

        return names

    def _find_symbol_in_codebase(self, name: str) -> SymbolInfo | None:
        """Find a symbol in the codebase.

        Searches recent files first, then does a broader search if needed.
        """
        # Search in recent files first
        for file_path_str in self._recent_files:
            try:
                file_path = Path(file_path_str)
                if not file_path.exists():
                    continue

                symbol = self._search_file_for_symbol(file_path, name)
                if symbol:
                    return symbol
            except (OSError, ValueError):
                continue

        # Search in current working directory (limited scope)
        try:
            cwd = Path.cwd()
            for pattern in ["*.py", "*.js", "*.ts", "*.java", "*.go", "*.rs"]:
                for file_path in cwd.rglob(pattern):
                    # Limit search depth
                    try:
                        rel_path = file_path.relative_to(cwd)
                        if len(rel_path.parts) > 3:  # Skip deep nesting
                            continue
                    except ValueError:
                        continue

                    symbol = self._search_file_for_symbol(file_path, name)
                    if symbol:
                        return symbol

                    # Limit total files searched
                    if len(self._symbol_cache) > 100:
                        break
                if len(self._symbol_cache) > 100:
                    break
        except (OSError, PermissionError) as e:
            logger.debug(f"Error searching codebase: {e}")

        return None

    def _search_file_for_symbol(self, file_path: Path, name: str) -> SymbolInfo | None:
        """Search a specific file for a symbol definition.

        Simple regex-based search for common patterns.
        """
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                lines = content.split("\n")
        except (OSError, UnicodeDecodeError):
            return None

        name_lower = name.lower()
        name_escaped = re.escape(name)

        # Define patterns for different symbol types
        patterns = [
            ("function", rf'^(?:def|function)\s+{name_escaped}\s*[\(:\(]'),
            ("class", rf'^class\s+{name_escaped}\b'),
            ("method", rf'^\s+(?:def|async\s+def)\s+{name_escaped}\s*\('),
            ("variable", rf'^{name_escaped}\s*='),
        ]

        for symbol_type, pattern in patterns:
            for i, line in enumerate(lines, 1):
                if re.search(pattern, line, re.IGNORECASE):
                    # Extract source (definition + following lines for context)
                    source_lines = self._extract_source_context(lines, i - 1, symbol_type)
                    source = "\n".join(source_lines)

                    # Extract imports and calls
                    imports = self._extract_imports(content)
                    calls = self._extract_calls(source)

                    return SymbolInfo(
                        name=name,
                        symbol_type=symbol_type,
                        file_path=file_path,
                        line_number=i,
                        source_code=source,
                        calls=calls,
                        imports=imports,
                    )

        return None

    def _extract_source_context(
        self, lines: list[str], start_idx: int, symbol_type: str
    ) -> list[str]:
        """Extract source code with context around the definition.

        For functions/classes, include the full definition.
        """
        if not lines or start_idx >= len(lines):
            return []

        # Start with the definition line
        result = [lines[start_idx]]

        # For Python-style indented blocks, include indented lines
        if symbol_type in {"function", "class", "method"}:
            base_indent = len(lines[start_idx]) - len(lines[start_idx].lstrip())
            for i in range(start_idx + 1, min(start_idx + 50, len(lines))):
                line = lines[i]
                if not line.strip():
                    result.append(line)
                    continue

                indent = len(line) - len(line.lstrip())
                # Stop at next definition at same or lower indentation
                if (
                    indent <= base_indent
                    and line.strip()
                    and not line.strip().startswith("#")
                    and not line.strip().startswith("@")
                ):
                    break

                result.append(line)

                # Limit total lines
                if len(result) > 30:
                    result.append("    ...")
                    break

        return result

    def _extract_imports(self, content: str) -> list[str]:
        """Extract import statements from file content."""
        imports = []

        # Python imports
        for match in re.finditer(r'^(?:import|from)\s+([a-z_][a-z0-9_.]*)', content, re.MULTILINE):
            imports.append(match.group(1))

        # JavaScript/TypeScript imports
        for match in re.finditer(r'import\s+.*?\s+from\s+[\'"]([^\'"]+)[\'"]', content):
            imports.append(match.group(1))

        return imports[:10]  # Limit imports

    def _extract_calls(self, source: str) -> list[str]:
        """Extract function calls from source code."""
        calls = []
        for match in re.finditer(r'\b([a-z_][a-z0-9_]*)\s*\(', source):
            call = match.group(1)
            if call not in {"if", "while", "for", "switch", "catch", "print", "len", "range", "str", "int"}:
                calls.append(call)
        return list(set(calls))[:10]  # Deduplicate and limit

    def _fetch_symbol_info(self, name: str) -> SymbolInfo | None:
        """Fetch full symbol info by name (from cache or search)."""
        if name in self._symbol_cache:
            return self._symbol_cache[name]
        return self._find_symbol_in_codebase(name)

    def get_cached_symbols(self) -> list[SymbolInfo]:
        """Get all cached symbols."""
        return list(self._symbol_cache.values())

    def clear_cache(self) -> None:
        """Clear the symbol cache."""
        self._symbol_cache.clear()

    def is_enabled(self) -> bool:
        """Check if the engine is enabled and initialized."""
        return self._initialized and self.config.enabled


# Global instance for plugin use
_context_engine: ContextEngine | None = None


def get_context_engine() -> ContextEngine:
    """Get or create the global context engine instance."""
    global _context_engine
    if _context_engine is None:
        _context_engine = ContextEngine()
        _context_engine.initialize()
    return _context_engine


def reset_context_engine() -> None:
    """Reset the global context engine (mainly for testing)."""
    global _context_engine
    _context_engine = None
