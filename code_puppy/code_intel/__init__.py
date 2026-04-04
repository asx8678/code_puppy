"""Code intelligence: Tree-sitter parser, symbol graph, and selective context engine.

This module provides functionality to:
- Parse code using Tree-sitter AST for multiple languages
- Build and maintain an incremental symbol graph
- Score code symbols by relevance based on conversation context
- Identify related code (callers, callees, imports)
- Format relevant code neighborhoods for prompt injection
"""

from .change_tracker import ChangeTracker
from .context_engine import ContextEngine, get_context_engine, ContextEngineConfig, SymbolInfo
from .formatters import CodeFormatter, FormattedSymbol
from .parser import IncrementalParser, TreeSitterParser, get_parser_for_file
from .relevance_scorer import RelevanceScorer, RelevanceScore, ScoringFactors
from .symbol_graph import Location, Reference, Symbol, SymbolGraph, SymbolKind

__all__ = [
    # New Tree-sitter based code intelligence
    "ChangeTracker",
    "IncrementalParser",
    "TreeSitterParser",
    "get_parser_for_file",
    "Location",
    "Reference",
    "Symbol",
    "SymbolGraph",
    "SymbolKind",
    # Existing context engine
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
