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

# Re-export all public APIs from the code_context package
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
