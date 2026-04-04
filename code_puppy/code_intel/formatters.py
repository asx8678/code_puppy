"""Formatters for code symbols and neighborhoods.

Provides clean, context-window-friendly formatting of code symbols
and their relationships for prompt injection.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .context_engine import SymbolInfo
    from .relevance_scorer import RelevanceScore

logger = logging.getLogger(__name__)


@dataclass
class FormattedSymbol:
    """A formatted symbol ready for prompt injection."""

    name: str
    content: str
    symbol_type: str
    file_path: Path
    line_number: int | None = None
    relevance_score: float = 0.0
    related_symbols: list[str] | None = None


class CodeFormatter:
    """Formats code symbols and neighborhoods for prompt injection."""

    def __init__(
        self,
        max_chars_per_symbol: int = 2000,
        max_total_chars: int = 8000,
        include_line_numbers: bool = True,
        include_related: bool = True,
    ):
        self.max_chars_per_symbol = max_chars_per_symbol
        self.max_total_chars = max_total_chars
        self.include_line_numbers = include_line_numbers
        self.include_related = include_related

    def format_symbol(self, symbol: SymbolInfo, score: RelevanceScore) -> FormattedSymbol:
        """Format a single symbol for display.

        Args:
            symbol: The symbol to format
            score: The relevance score for context

        Returns:
            FormattedSymbol with formatted content
        """
        # Build the content
        lines = []

        # Header with location
        header = self._format_header(symbol, score)
        lines.append(header)

        # Source code
        source = self._format_source(symbol)
        lines.append(source)

        # Related symbols (callers/callees)
        if self.include_related:
            related = self._format_related(symbol)
            if related:
                lines.append(related)

        content = "\n".join(lines)

        # Truncate if too long
        if len(content) > self.max_chars_per_symbol:
            content = content[: self.max_chars_per_symbol - 3] + "..."

        return FormattedSymbol(
            name=symbol.name,
            content=content,
            symbol_type=symbol.symbol_type,
            file_path=symbol.file_path,
            line_number=symbol.line_number,
            relevance_score=score.score,
            related_symbols=symbol.calls,
        )

    def format_symbols_for_prompt(
        self, symbols: list[tuple[SymbolInfo, RelevanceScore]]
    ) -> str | None:
        """Format multiple symbols into a prompt-ready string.

        Args:
            symbols: List of (symbol, score) tuples, should be pre-sorted by relevance

        Returns:
            Formatted string for prompt injection, or None if empty
        """
        if not symbols:
            return None

        sections = []
        total_chars = 0

        # Header section
        header = "\n\n## 📋 Relevant Code Context\n"
        header += "The following code symbols may be relevant to your task:\n"
        sections.append(header)
        total_chars += len(header)

        # Format each symbol, respecting total limit
        for symbol, score in symbols:
            formatted = self.format_symbol(symbol, score)

            # Check if adding this would exceed limit
            if total_chars + len(formatted.content) > self.max_total_chars:
                # Add truncation notice
                notice = "\n... (more symbols available but truncated for space) ...\n"
                sections.append(notice)
                break

            sections.append(formatted.content)
            total_chars += len(formatted.content)

        # Footer
        footer = "\nUse this code context as needed for your task.\n"
        if total_chars + len(footer) <= self.max_total_chars:
            sections.append(footer)

        result = "\n".join(sections)
        return result if len(result) > len(header) else None

    def _format_header(self, symbol: SymbolInfo, score: RelevanceScore) -> str:
        """Format the symbol header with metadata."""
        parts = [f"### {symbol.name}"]

        if symbol.symbol_type:
            parts.append(f"({symbol.symbol_type})")

        # Location info
        location = self._format_location(symbol)
        if location:
            parts.append(f"at {location}")

        # Score (for debugging, can be removed in production)
        if logger.isEnabledFor(logging.DEBUG):
            parts.append(f"[relevance: {score.score:.1f}]")

        return " ".join(parts)

    def _format_location(self, symbol: SymbolInfo) -> str | None:
        """Format file location information."""
        try:
            # Show relative path if possible
            cwd = Path.cwd()
            if symbol.file_path.is_relative_to(cwd):
                path = symbol.file_path.relative_to(cwd)
            else:
                path = symbol.file_path.name

            if symbol.line_number and self.include_line_numbers:
                return f"`{path}:{symbol.line_number}`"
            return f"`{path}`"
        except (ValueError, OSError):
            return f"`{symbol.file_path.name}`"

    def _format_source(self, symbol: SymbolInfo) -> str:
        """Format the source code content."""
        if not symbol.source_code:
            return "*Source not available*"

        source = symbol.source_code.strip()

        # Wrap in code block with appropriate language
        lang = self._detect_language(symbol.file_path)
        return f"```{lang}\n{source}\n```"

    def _format_related(self, symbol: SymbolInfo) -> str | None:
        """Format related symbols (callers/callees)."""
        lines = []

        if symbol.calls:
            calls_str = ", ".join(f"`{c}`" for c in symbol.calls[:5])
            if len(symbol.calls) > 5:
                calls_str += f", ... ({len(symbol.calls) - 5} more)"
            lines.append(f"**Calls:** {calls_str}")

        if symbol.called_by:
            called_str = ", ".join(f"`{c}`" for c in symbol.called_by[:5])
            if len(symbol.called_by) > 5:
                called_str += f", ... ({len(symbol.called_by) - 5} more)"
            lines.append(f"**Called by:** {called_str}")

        if symbol.imports:
            imports_str = ", ".join(f"`{i}`" for i in symbol.imports[:5])
            if len(symbol.imports) > 5:
                imports_str += f", ... ({len(symbol.imports) - 5} more)"
            lines.append(f"**Imports:** {imports_str}")

        if lines:
            return "\n".join(lines)
        return None

    def _detect_language(self, file_path: Path) -> str:
        """Detect programming language from file extension."""
        suffix = file_path.suffix.lower()

        language_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".jsx": "jsx",
            ".tsx": "tsx",
            ".rs": "rust",
            ".go": "go",
            ".java": "java",
            ".kt": "kotlin",
            ".scala": "scala",
            ".rb": "ruby",
            ".php": "php",
            ".cs": "csharp",
            ".cpp": "cpp",
            ".c": "c",
            ".h": "c",
            ".swift": "swift",
            ".m": "objectivec",
            ".r": "r",
            ".sql": "sql",
            ".sh": "bash",
            ".bash": "bash",
            ".zsh": "zsh",
            ".fish": "fish",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".json": "json",
            ".toml": "toml",
            ".html": "html",
            ".css": "css",
            ".scss": "scss",
            ".sass": "sass",
            ".less": "less",
            ".xml": "xml",
            ".md": "markdown",
            ".dockerfile": "dockerfile",
            ".tf": "hcl",
            ".hcl": "hcl",
        }

        return language_map.get(suffix, "")

    def format_simple_list(
        self, symbols: list[tuple[SymbolInfo, RelevanceScore]]
    ) -> str | None:
        """Format as a simple list for compact contexts.

        Args:
            symbols: List of (symbol, score) tuples

        Returns:
            Compact formatted string or None
        """
        if not symbols:
            return None

        lines = ["\n\n## Relevant Code Symbols\n"]

        for symbol, score in symbols[:10]:  # Limit to top 10
            location = self._format_location(symbol)
            score_str = f"[{score.score:.1f}]" if logger.isEnabledFor(logging.DEBUG) else ""
            lines.append(f"- `{symbol.name}` ({symbol.symbol_type}) at {location} {score_str}")

        lines.append("\nUse these symbols as reference for your task.")

        result = "\n".join(lines)
        if len(result) > self.max_total_chars:
            result = result[: self.max_total_chars - 3] + "..."

        return result
