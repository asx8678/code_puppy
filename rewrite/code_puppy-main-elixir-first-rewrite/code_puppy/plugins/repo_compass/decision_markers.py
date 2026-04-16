"""Decision marker scanning for source code context.

Scans Python and source files for decision markers like # WHY:, # DECISION:, etc.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DecisionMarker:
    """A decision marker found in source code.

    Attributes:
        path: Relative path to the file containing the marker
        line_number: 1-indexed line number of the marker
        marker_type: Type of marker (WHY, DECISION, TRADEOFF, ADR, HACK)
        text: The marker line text itself
        context: ±3 lines of surrounding context
    """

    path: str
    line_number: int
    marker_type: str
    text: str
    context: str


# Marker regex patterns to search for (hash-style comments - Python, Ruby, etc.)
_HASH_MARKER_PATTERNS = [
    (r"#\s*WHY:", "WHY"),
    (r"#\s*DECISION:", "DECISION"),
    (r"#\s*TRADEOFF:", "TRADEOFF"),
    (r"#\s*ADR:", "ADR"),
    (r"#\s*HACK\([^)]+\)", "HACK"),
]

# Marker patterns for C-style comments (// style - JS, TS, Rust, Go, Java, etc.)
_CSTYLE_MARKER_PATTERNS = [
    (r"//\s*WHY:", "WHY"),
    (r"//\s*DECISION:", "DECISION"),
    (r"//\s*TRADEOFF:", "TRADEOFF"),
    (r"//\s*ADR:", "ADR"),
    (r"//\s*HACK\([^)]+\)", "HACK"),
]

# Source file extensions to scan
_SOURCE_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".rs",
    ".go",
    ".rb",
    ".java",
    ".kt",
    ".swift",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
}

# Directories to ignore (same as indexer)
_IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
    ".venv",
    "venv",
    "target",  # Rust build
    "vendor",  # Go deps
}


def _is_hidden(path: Path) -> bool:
    """Check if a path is hidden (starts with .)."""
    return any(part.startswith(".") for part in path.parts if part not in {".", ".."})


def _iter_source_files(root: Path, max_files: int) -> list[Path]:
    """Iterate over source files to scan, limited by max_files."""
    candidates: list[Path] = []

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)

        # Skip ignored directories
        if any(part in _IGNORED_DIRS for part in rel.parts):
            continue

        # Skip hidden files
        if _is_hidden(rel):
            continue

        # Only include source files
        if path.suffix not in _SOURCE_EXTENSIONS:
            continue

        candidates.append(path)

        if len(candidates) >= max_files:
            break

    return candidates


def _get_context_lines(
    lines: list[str], marker_line: int, context_radius: int = 3
) -> str:
    """Extract context lines around the marker.

    Args:
        lines: All lines in the file
        marker_line: 0-indexed line number of marker
        context_radius: Number of lines before/after to include

    Returns:
        Context string with line numbers
    """
    start = max(0, marker_line - context_radius)
    end = min(len(lines), marker_line + context_radius + 1)

    context_parts: list[str] = []
    for i in range(start, end):
        line_num = i + 1  # 1-indexed
        prefix = ">>> " if i == marker_line else "    "
        context_parts.append(f"{prefix}{line_num}: {lines[i].rstrip()}")

    return "\n".join(context_parts)


def _get_patterns_for_file(path: Path) -> list[tuple[str, str]]:
    """Get appropriate marker patterns for a file based on extension."""
    cstyle_exts = {
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".rs",
        ".go",
        ".java",
        ".kt",
        ".swift",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
    }
    if path.suffix in cstyle_exts:
        return _CSTYLE_MARKER_PATTERNS
    return _HASH_MARKER_PATTERNS


def _is_inside_string(line: str, pos: int) -> bool:
    """Check if position `pos` in `line` is inside a string literal.

    Handles single and double quotes, including escaped quotes.
    Note: Does not handle triple-quoted strings (rare edge case).

    Args:
        line: The line of text to check
        pos: The position (0-indexed) to check

    Returns:
        True if the position is inside a string literal, False otherwise
    """
    in_string = False
    string_char = None
    escaped = False

    for i, char in enumerate(line):
        if i >= pos:
            break

        if escaped:
            escaped = False
            continue

        if char == "\\":
            escaped = True
            continue

        if in_string:
            if char == string_char:
                in_string = False
                string_char = None
        else:
            if char in ('"', "'"):
                in_string = True
                string_char = char

    return in_string


def _scan_file(path: Path, root: Path) -> list[DecisionMarker]:
    """Scan a single file for decision markers.

    Args:
        path: Path to the file to scan
        root: Project root for relative path calculation

    Returns:
        List of DecisionMarker found in the file
    """
    markers: list[DecisionMarker] = []

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError, ValueError):
        return markers

    lines = text.split("\n")
    rel_path = str(path.relative_to(root))
    patterns = _get_patterns_for_file(path)

    for line_idx, line in enumerate(lines):
        for pattern, marker_type in patterns:
            match = re.search(pattern, line)
            if match:
                # Skip matches inside string literals
                if _is_inside_string(line, match.start()):
                    continue
                context = _get_context_lines(lines, line_idx)
                marker = DecisionMarker(
                    path=rel_path,
                    line_number=line_idx + 1,  # 1-indexed
                    marker_type=marker_type,
                    text=line.strip(),
                    context=context,
                )
                markers.append(marker)
                break  # Only match first pattern per line

    return markers


def scan_decision_markers(
    root: Path, max_files: int = 40, max_markers: int = 10
) -> list[DecisionMarker]:
    """Scan source files for decision markers.

    Args:
        root: Project root directory path
        max_files: Maximum number of files to scan
        max_markers: Maximum number of markers to return

    Returns:
        List of DecisionMarker, limited to max_markers
    """
    all_markers: list[DecisionMarker] = []

    try:
        files = _iter_source_files(root, max_files)
    except (OSError, PermissionError) as exc:
        logger.debug("Failed to iterate source files: %s", exc)
        return all_markers

    for file_path in files:
        try:
            markers = _scan_file(file_path, root)
            all_markers.extend(markers)

            if len(all_markers) >= max_markers:
                break
        except Exception as exc:
            logger.debug("Failed to scan %s: %s", file_path, exc)
            continue

    return all_markers[:max_markers]
