"""Bridge to Rust turbo_ops indexer with Python fallback.

This module provides a unified API for directory indexing that:
1. Uses the Rust `turbo_ops.index_directory()` when available (5-10x faster)
2. Falls back to the pure Python implementation when Rust is unavailable

bd-61: Migrated to use NativeBackend for unified acceleration access.
"""

from dataclasses import dataclass
from pathlib import Path

from code_puppy.native_backend import NativeBackend

# Import Python fallback
from code_puppy.plugins.repo_compass.indexer import (
    build_structure_map as _python_build_structure_map,
    FileSummary as PythonFileSummary,
    IGNORED_DIRS,
)

# Legacy compatibility: check NativeBackend status
TURBO_INDEXER_AVAILABLE = NativeBackend.is_available(NativeBackend.Capabilities.REPO_INDEX)


@dataclass(frozen=True, slots=True)
class FileSummary:
    """Unified FileSummary that works with both Rust and Python backends."""
    path: str
    kind: str
    symbols: tuple[str, ...] = ()

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

    Uses Rust acceleration via NativeBackend when available for 5-10x speedup.

    Args:
        root: Root directory to scan
        max_files: Maximum number of files to include
        max_symbols_per_file: Maximum symbols to extract per file
        force_python: Force use of Python implementation (for testing)

    Returns:
        List of FileSummary objects describing the repo structure
    """
    prefer_native = not force_python
    results = NativeBackend.index_directory(
        str(root), max_files, max_symbols_per_file, _prefer_native=prefer_native
    )

    # Convert result dicts to FileSummary objects
    return [
        FileSummary(
            path=r["path"],
            kind=r["kind"],
            symbols=tuple(r.get("symbols", [])),
        )
        for r in results
    ]


def get_indexer_status() -> dict:
    """Return diagnostic info about the indexer backend."""
    status = NativeBackend.get_status()
    repo_index_status = status.get(NativeBackend.Capabilities.REPO_INDEX)

    return {
        "rust_available": repo_index_status.available if repo_index_status else False,
        "backend": "turbo_ops" if (repo_index_status and repo_index_status.active) else "python",
        "native_backend_status": repo_index_status.status if repo_index_status else "unknown",
    }


# Re-export for convenience
__all__ = [
    "FileSummary",
    "build_structure_map",
    "get_indexer_status",
    "TURBO_INDEXER_AVAILABLE",
]
