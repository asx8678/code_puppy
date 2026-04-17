"""Repository indexer (Python-only implementation).

bd-86: Native acceleration layer removed. This module now provides
only the pure Python implementation from indexer.py.

Provides a unified API for directory indexing using the Python implementation.
"""

from pathlib import Path

# Import the Python implementation directly
from code_puppy.plugins.repo_compass.indexer import (
    FileSummary,
    build_structure_map as _python_build_structure_map,
)

# bd-86: Native acceleration removed, always False
TURBO_INDEXER_AVAILABLE = False


def build_structure_map(
    root: Path,
    max_files: int = 40,
    max_symbols_per_file: int = 8,
    *,
    force_python: bool = False,  # Ignored, Python is always used
) -> list[FileSummary]:
    """Build a structure map of the repository.

    bd-86: Native acceleration removed. Uses pure Python implementation.

    Args:
        root: Root directory to scan
        max_files: Maximum number of files to include
        max_symbols_per_file: Maximum symbols to extract per file
        force_python: Ignored (kept for API compatibility)

    Returns:
        List of FileSummary objects describing the repo structure
    """
    return _python_build_structure_map(root, max_files, max_symbols_per_file)


def get_indexer_status() -> dict:
    """Return diagnostic info about the indexer backend.

    bd-86: Native acceleration removed, always returns Python backend status.
    """
    return {
        "elixir_available": False,
        "backend": "python",
        "native_backend_status": "unavailable",
    }


# Re-export for convenience
__all__ = [
    "FileSummary",
    "build_structure_map",
    "get_indexer_status",
    "TURBO_INDEXER_AVAILABLE",
]
