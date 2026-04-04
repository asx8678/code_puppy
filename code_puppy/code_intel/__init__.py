"""Code intelligence: selective context engine with relevance scoring.

This module provides functionality to:
- Score code symbols by relevance based on conversation context
- Identify related code (callers, callees, imports)
- Format relevant code neighborhoods for prompt injection
"""

from .context_engine import ContextEngine, get_context_engine, ContextEngineConfig, SymbolInfo
from .relevance_scorer import RelevanceScorer, RelevanceScore, ScoringFactors
from .formatters import CodeFormatter, FormattedSymbol

__all__ = [
    "ContextEngine",
    "get_context_engine",
    "ContextEngineConfig",
    "SymbolInfo",
    "RelevanceScorer",
    "RelevanceScore",
    "ScoringFactors",
    "CodeFormatter",
    "FormattedSymbol",
]
