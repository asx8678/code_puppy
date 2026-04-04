"""Relevance scoring for code symbols.

Scores symbols based on multiple factors:
- Direct focus: mentioned in conversation
- Callers: functions that call the focused function
- Callees: functions called by the focused function
- Imports: modules imported by relevant files
- Recency: recently modified files
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .context_engine import SymbolInfo

logger = logging.getLogger(__name__)


@dataclass
class ScoringFactors:
    """Weights for relevance scoring factors.

    All weights should be positive. Higher = more important.
    """

    direct_mention: float = 10.0
    caller: float = 5.0
    callee: float = 5.0
    import_relationship: float = 3.0
    recent_modification: float = 2.0
    symbol_type_boost: float = 1.0  # Multiplier for certain symbol types


@dataclass
class RelevanceScore:
    """Score result for a symbol."""

    symbol_name: str
    score: float
    factors: dict[str, float] = field(default_factory=dict)
    explanation: str = ""

    def __post_init__(self):
        # Round for cleaner display
        self.score = round(self.score, 2)


class RelevanceScorer:
    """Scores code symbols by relevance to conversation context."""

    def __init__(self, factors: ScoringFactors | None = None):
        self.factors = factors or ScoringFactors()
        self._conversation_text: str = ""
        self._recent_files: set[str] = set()
        self._focus_symbols: set[str] = set()

    def set_conversation_context(
        self, text: str, recent_files: list[str] | None = None
    ) -> None:
        """Set the current conversation context for scoring.

        Args:
            text: Recent conversation text (user messages, code snippets)
            recent_files: List of recently modified file paths
        """
        self._conversation_text = text.lower()
        self._recent_files = set(recent_files or [])
        self._focus_symbols = self._extract_focus_symbols(text)
        logger.debug(
            f"Context set: {len(self._focus_symbols)} focus symbols, "
            f"{len(self._recent_files)} recent files"
        )

    def _extract_focus_symbols(self, text: str) -> set[str]:
        """Extract symbols that are directly mentioned in conversation.

        Looks for:
        - Function names followed by parentheses
        - Class names in CamelCase
        - File names with extensions
        - Explicit mentions like "the X function/class"
        """
        symbols = set()
        text_lower = text.lower()

        # Function calls: name() or name(...) patterns
        func_pattern = r'\b([a-z_][a-z0-9_]*)\s*\('
        for match in re.finditer(func_pattern, text_lower):
            symbols.add(match.group(1))

        # Class names: CamelCase patterns
        class_pattern = r'\b([A-Z][a-zA-Z0-9_]*[a-z][a-zA-Z0-9_]*)\b'
        for match in re.finditer(class_pattern, text):
            name = match.group(1)
            # Filter out common false positives
            if name not in {"True", "False", "None", "Http", "Json", "Api", "Url"}:
                symbols.add(name)

        # Explicit mentions: "the X function", "X class", etc.
        explicit_patterns = [
            r'the\s+([a-z_][a-z0-9_]*)\s+function',
            r'the\s+([a-z_][a-z0-9_]*)\s+method',
            r'the\s+([A-Z][a-zA-Z0-9_]*)\s+class',
            r'function\s+([a-z_][a-z0-9_]*)',
            r'method\s+([a-z_][a-z0-9_]*)',
            r'class\s+([A-Z][a-zA-Z0-9_]*)',
        ]
        for pattern in explicit_patterns:
            for match in re.finditer(pattern, text_lower):
                symbols.add(match.group(1))

        return symbols

    def score_symbol(self, symbol: SymbolInfo) -> RelevanceScore:
        """Calculate relevance score for a single symbol.

        Args:
            symbol: The symbol information to score

        Returns:
            RelevanceScore with total and breakdown by factor
        """
        score = 0.0
        factors: dict[str, float] = {}

        # Direct mention in conversation
        if self._is_directly_mentioned(symbol):
            score += self.factors.direct_mention
            factors["direct_mention"] = self.factors.direct_mention

        # Caller relationship to focus symbols
        if self._is_caller_of_focus(symbol):
            score += self.factors.caller
            factors["caller"] = self.factors.caller

        # Callee relationship to focus symbols
        if self._is_callee_of_focus(symbol):
            score += self.factors.callee
            factors["callee"] = self.factors.callee

        # Import relationship
        if self._has_import_relationship(symbol):
            score += self.factors.import_relationship
            factors["import_relationship"] = self.factors.import_relationship

        # Recent modification
        if self._is_recently_modified(symbol):
            score += self.factors.recent_modification
            factors["recent_modification"] = self.factors.recent_modification

        # Symbol type boost (classes and functions get slight boost)
        if symbol.symbol_type in {"class", "function", "method"}:
            boost = self.factors.symbol_type_boost
            score *= boost
            factors["type_boost"] = boost

        # Build explanation
        explanation = self._build_explanation(symbol, factors)

        return RelevanceScore(
            symbol_name=symbol.name,
            score=score,
            factors=factors,
            explanation=explanation,
        )

    def score_symbols(self, symbols: list[SymbolInfo]) -> list[RelevanceScore]:
        """Score multiple symbols and return sorted by relevance (highest first).

        Args:
            symbols: List of symbols to score

        Returns:
            List of RelevanceScore, sorted by score descending
        """
        scores = [self.score_symbol(s) for s in symbols]
        scores.sort(key=lambda x: x.score, reverse=True)
        return scores

    def _is_directly_mentioned(self, symbol: SymbolInfo) -> bool:
        """Check if symbol is directly mentioned in conversation."""
        name_lower = symbol.name.lower()
        if name_lower in self._focus_symbols:
            return True
        # Also check if the name appears as a word in the text
        pattern = r'\b' + re.escape(name_lower) + r'\b'
        return bool(re.search(pattern, self._conversation_text))

    def _is_caller_of_focus(self, symbol: SymbolInfo) -> bool:
        """Check if this symbol calls any focus symbols.

        This requires the symbol to have call information.
        """
        if not symbol.calls:
            return False
        # Check if any focus symbol is in the calls list
        for focus in self._focus_symbols:
            if focus in symbol.calls or any(
                focus in call.lower() for call in symbol.calls
            ):
                return True
        return False

    def _is_callee_of_focus(self, symbol: SymbolInfo) -> bool:
        """Check if this symbol is called by any focus symbols.

        This is inferred from the conversation - if we're discussing
        a function and mention it calls X, then X is a callee.
        """
        # For now, check if the symbol name appears in conversation
        # alongside "called by" or similar patterns
        name_lower = symbol.name.lower()
        patterns = [
            rf'called\s+by\s+.*{re.escape(name_lower)}',
            rf'{re.escape(name_lower)}.*\s+calls?\s',
            rf'calls?\s.*{re.escape(name_lower)}',
        ]
        for pattern in patterns:
            if re.search(pattern, self._conversation_text):
                return True
        return False

    def _has_import_relationship(self, symbol: SymbolInfo) -> bool:
        """Check if symbol's file imports from or is imported by focus files."""
        # Check if the symbol's file path contains any focus symbol names
        path_lower = str(symbol.file_path).lower()
        for focus in self._focus_symbols:
            if focus in path_lower:
                return True

        # Check if symbol imports are mentioned
        if symbol.imports:
            for imp in symbol.imports:
                imp_lower = imp.lower()
                if any(focus in imp_lower for focus in self._focus_symbols):
                    return True

        return False

    def _is_recently_modified(self, symbol: SymbolInfo) -> bool:
        """Check if the symbol's file was recently modified."""
        path_str = str(symbol.file_path)
        # Check exact match
        if path_str in self._recent_files:
            return True
        # Check basename match
        basename = Path(path_str).name
        for recent in self._recent_files:
            if Path(recent).name == basename:
                return True
        return False

    def _build_explanation(self, symbol: SymbolInfo, factors: dict[str, float]) -> str:
        """Build a human-readable explanation of the score."""
        if not factors:
            return "Low relevance"

        parts = []
        if "direct_mention" in factors:
            parts.append("directly mentioned")
        if "caller" in factors:
            parts.append("calls focused function")
        if "callee" in factors:
            parts.append("called by focused function")
        if "import_relationship" in factors:
            parts.append("related imports")
        if "recent_modification" in factors:
            parts.append("recently modified file")

        return f"Relevant: {', '.join(parts)}"

    def get_focus_symbols(self) -> set[str]:
        """Return the currently identified focus symbols."""
        return self._focus_symbols.copy()

    def clear_context(self) -> None:
        """Clear all conversation context."""
        self._conversation_text = ""
        self._recent_files.clear()
        self._focus_symbols.clear()
