"""Bridge to Rust turbo_ops indexer with Python fallback.

This module provides a unified API for directory indexing that:
1. Uses the Rust `turbo_ops.index_directory()` when available (5-10x faster)
2. Falls back to the pure Python implementation when Rust is unavailable
"""

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

# Try to import Rust indexer
try:
    from turbo_ops import index_directory as _rust_index_directory
    from turbo_ops import FileSummary as RustFileSummary
    TURBO_INDEXER_AVAILABLE = True
except ImportError:
    TURBO_INDEXER_AVAILABLE = False
    _rust_index_directory = None
    RustFileSummary = None

# Import Python fallback
from code_puppy.plugins.repo_compass.indexer import (
    build_structure_map as _python_build_structure_map,
    FileSummary as PythonFileSummary,
    IGNORED_DIRS,
)


@dataclass(frozen=True, slots=True)
class FileSummary:
    """Unified FileSummary that works with both Rust and Python backends."""
    path: str
    kind: str
    symbols: tuple[str, ...] = ()
    
    @classmethod
    def from_rust(cls, rust_summary: "RustFileSummary") -> "FileSummary":
        """Convert Rust FileSummary to Python FileSummary."""
        return cls(
            path=rust_summary.path,
            kind=rust_summary.kind,
            symbols=tuple(rust_summary.symbols),
        )
    
    @classmethod
    def from_python(cls, py_summary: PythonFileSummary) -> "FileSummary":
        """Convert Python FileSummary (already the same structure)."""
        return cls(
            path=py_summary.path,
            kind=py_summary.kind,
            symbols=py_summary.symbols,
        )


def build_structure_map(
    root: Path,
    max_files: int = 40,
    max_symbols_per_file: int = 8,
    *,
    force_python: bool = False,
) -> list[FileSummary]:
    """Build a structure map of the repository.
    
    Uses Rust acceleration when available for 5-10x speedup.
    
    Args:
        root: Root directory to scan
        max_files: Maximum number of files to include
        max_symbols_per_file: Maximum symbols to extract per file
        force_python: Force use of Python implementation (for testing)
        
    Returns:
        List of FileSummary objects describing the repo structure
    """
    if TURBO_INDEXER_AVAILABLE and not force_python:
        # Use Rust implementation
        rust_summaries = _rust_index_directory(
            str(root),
            max_files,
            max_symbols_per_file,
            list(IGNORED_DIRS),  # Pass Python's ignored dirs to Rust
        )
        return [FileSummary.from_rust(s) for s in rust_summaries]
    else:
        # Use Python fallback
        py_summaries = _python_build_structure_map(root, max_files, max_symbols_per_file)
        return [FileSummary.from_python(s) for s in py_summaries]


def get_indexer_status() -> dict:
    """Return diagnostic info about the indexer backend."""
    return {
        "rust_available": TURBO_INDEXER_AVAILABLE,
        "backend": "turbo_ops" if TURBO_INDEXER_AVAILABLE else "python",
    }


# Re-export for convenience
__all__ = [
    "FileSummary",
    "build_structure_map",
    "get_indexer_status",
    "TURBO_INDEXER_AVAILABLE",
]
