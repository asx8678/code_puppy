"""Repository indexer (Python-only implementation).

bd-50: Native acceleration layer removed. This module re-exports
the pure Python implementation from indexer.py.
"""

from pathlib import Path

# Re-export from Python implementation
from code_puppy.plugins.repo_compass.indexer import (
    FileSummary,
    build_structure_map as _python_build_structure_map,
)

# bd-50: Native acceleration removed, always False
TURBO_INDEXER_AVAILABLE = False


def build_structure_map(
    root: Path,
    max_files: int = 40,
    max_symbols_per_file: int = 8,
    *,
    force_python: bool = False,  # Ignored, Python is always used
) -> list[FileSummary]:
    """Build a structure map of the repository.

    bd-50: Native acceleration removed. Uses pure Python implementation.
    """
    return _python_build_structure_map(root, max_files, max_symbols_per_file)


def get_indexer_status() -> dict:
    """Return diagnostic info about the indexer backend.

    bd-50: Native acceleration removed, always uses Python backend.
    """
    return {
        "backend": "python",
    }


__all__ = [
    "FileSummary",
    "build_structure_map",
    "get_indexer_status",
    "TURBO_INDEXER_AVAILABLE",
]
