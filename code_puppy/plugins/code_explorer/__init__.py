"""Code Explorer Plugin — Symbol-augmented code exploration.

Provides enhanced code exploration with turbo_parse symbol integration.
Exposes tools for exploring files with structural understanding.
"""

from code_puppy.code_context import (
    CodeContext,
    CodeExplorer,
    FileOutline,
    SymbolInfo,
    enhance_read_file_result,
    explore_directory,
    format_outline,
    get_code_context,
    get_explorer_instance,
    get_file_outline,
)

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
