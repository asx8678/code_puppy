"""Lightweight regression guard against disallowed legacy Zig runtime references.

This test scans active runtime paths (implementation + Elixir control plane)
for strings that should have been removed during the Zig-to-Elixir migration.
It intentionally excludes docs and historical references that legitimately
mention Zig for context.

Issue: bd-106
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Directories whose *runtime* code must stay Zig-free.
SCAN_DIRS = [
    REPO_ROOT / "code_puppy",
    REPO_ROOT / "elixir" / "code_puppy_control" / "lib",
    REPO_ROOT / "elixir" / "code_puppy_control" / "scripts",
]

# Substrings that signal a stale Zig runtime reference.
DISALLOWED_PATTERNS = [
    "zig_runner",
    "zig-out/bin/process_runner",
    "code_puppy.zig_bridge",
    "zig_bridge",
]

# Directories to skip entirely (docs, historical plans, tests with intentional refs).
EXCLUDE_DIRS = {
    "docs",
    "__pycache__",
    ".git",
    "node_modules",
    "_build",
    "deps",
}

# File extensions that are plausibly source / config (skip binaries, images, etc.).
SOURCE_EXTENSIONS = {
    ".py",
    ".ex",
    ".exs",
    ".sh",
    ".bash",
    ".toml",
    ".yaml",
    ".yml",
    ".json",
    ".cfg",
    ".ini",
    ".conf",
}


def _iter_scannable_files() -> list[Path]:
    """Yield files under SCAN_DIRS that should be checked."""
    files: list[Path] = []
    for base in SCAN_DIRS:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            # Skip excluded directories
            if any(part in EXCLUDE_DIRS for part in path.parts):
                continue
            if not path.is_file():
                continue
            if path.suffix not in SOURCE_EXTENSIONS:
                continue
            files.append(path)
    return files


def _scan_file(path: Path) -> list[tuple[int, str, str]]:
    """Return (line_number, line_text, matched_pattern) for violations."""
    hits: list[tuple[int, str, str]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return hits
    for lineno, line in enumerate(text.splitlines(), start=1):
        for pattern in DISALLOWED_PATTERNS:
            if pattern in line:
                hits.append((lineno, line.rstrip(), pattern))
    return hits


def test_no_legacy_zig_references_in_runtime_paths():
    """Runtime code must not reference legacy Zig runner or bridge paths.

    If this test fails, a disallowed Zig string was found in an active
    runtime directory.  Either remove the reference or, if it is truly
    intentional, add the file to the exclude list with a comment
    explaining why.
    """
    violations: dict[str, list[tuple[int, str, str]]] = {}
    for path in _iter_scannable_files():
        hits = _scan_file(path)
        if hits:
            violations[str(path.relative_to(REPO_ROOT))] = hits

    if not violations:
        return  # all clear

    lines = ["Disallowed legacy Zig references found in runtime paths:\n"]
    for rel_path, hits in sorted(violations.items()):
        lines.append(f"  📄 {rel_path}")
        for lineno, text, pattern in hits:
            lines.append(f"    L{lineno}: [{pattern}] {text}")
        lines.append("")

    lines.append(
        "Action: remove the reference or add the file to the exclude list "
        "with a justification comment."
    )
    pytest.fail("\n".join(lines))
