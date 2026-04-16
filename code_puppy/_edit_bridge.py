"""Bridge to Elixir edit engine with Python fallback.

This module provides transparent routing for edit operations:
- fuzzy_match_window: Find best matching window using Jaro-Winkler similarity
- replace_in_content: Apply replacements with exact/fuzzy matching + diff generation
- unified_diff: Generate unified diff between two content strings

Routing priority (bd-41): Elixir → Python

When the Elixir file_service is available and enabled, it is tried first.
When unavailable, the bridge falls back to the Python implementations.
"""

from __future__ import annotations

import difflib

__all__ = [
    "fuzzy_match_window",
    "replace_in_content",
    "unified_diff",
]


def _try_elixir_replace(
    content: str,
    replacements: list[tuple[str, str]],
) -> dict | None:
    """Try to route replace_in_content through Elixir (bd-39, bd-41).

    Returns the result dict if Elixir is available and succeeds,
    or None to signal fallback to Python.
    """
    try:
        from code_puppy.native_backend import NativeBackend

        if not NativeBackend._should_use_elixir("edit_ops"):
            return None

        # Convert tuple list to the JSON-RPC format Elixir expects
        elixir_replacements = [
            {"old_str": old, "new_str": new} for old, new in replacements
        ]

        result = NativeBackend._call_elixir(
            "text_replace",
            {"content": content, "replacements": elixir_replacements},
        )

        # Elixir returns the same dict shape we need
        return {
            "modified": result.get("modified", content),
            "diff": result.get("diff", ""),
            "success": result.get("success", False),
            "error": result.get("error"),
            "jw_score": result.get("jw_score"),
        }
    except Exception:
        # Any failure → fall through to Python
        return None


def _try_elixir_fuzzy_match(
    haystack_lines: list[str],
    needle: str,
) -> tuple[tuple[int, int | None] | None, float] | None:
    """Try to route fuzzy_match_window through Elixir (bd-41).

    Returns the result tuple if Elixir is available and succeeds,
    or None to signal fallback to Python.
    """
    try:
        from code_puppy.native_backend import NativeBackend

        if not NativeBackend._should_use_elixir("edit_ops"):
            return None

        result = NativeBackend._call_elixir(
            "text_fuzzy_match",
            {"haystack_lines": haystack_lines, "needle": needle},
        )

        start = result.get("start", 0)
        end = result.get("end")  # Can be None for no match
        score = result.get("score", 0.0)

        span: tuple[int, int | None] | None = (start, end) if end is not None else None
        return (span, score)
    except Exception:
        # Any failure → fall through to Python
        return None


def fuzzy_match_window(
    haystack_lines: list[str],
    needle: str,
) -> tuple[tuple[int, int | None] | None, float]:
    """Bridge to Elixir fuzzy_match_window with Python fallback.

    Returns ((start, end), score) matching the Python _find_best_window signature.
    When Elixir is available, routes through the Elixir implementation.

    Args:
        haystack_lines: List of lines to search within (the "haystack")
        needle: The text to find (the "needle")

    Returns:
        Tuple of ((start_index, end_index), score). If no match found,
        returns (None, score) where score < 0.95.
    """
    # bd-41: Try Elixir first
    elixir_result = _try_elixir_fuzzy_match(haystack_lines, needle)
    if elixir_result is not None:
        return elixir_result

    # Python fallback - directly import the internal implementation to avoid recursion
    # Do NOT call _find_best_window which routes back to the bridge!
    from code_puppy.tools.common import _do_fuzzy_match_python

    return _do_fuzzy_match_python(haystack_lines, needle, None, None)


def replace_in_content(
    content: str,
    replacements: list[tuple[str, str]],
) -> dict:
    """Bridge to Elixir replace_in_content with Python fallback.

    Routing priority (bd-41): Elixir → Python

    Returns dict with: modified, diff, success, error, jw_score
    matching the format _apply_replacements returns.

    Args:
        content: Original content string
        replacements: List of (old_str, new_str) tuples to apply

    Returns:
        Dict with keys:
        - modified: str - the modified content after all replacements
        - diff: str - unified diff between original and modified
        - success: bool - whether all replacements succeeded
        - error: str | None - error message if fuzzy match failed
        - jw_score: float | None - the JW score if fuzzy match was attempted
    """
    # bd-41: Try Elixir first
    elixir_result = _try_elixir_replace(content, replacements)
    if elixir_result is not None:
        return elixir_result

    # Python fallback - replicate the logic from _apply_replacements
    # but only the inner replacement + diff generation (no file I/O)
    from code_puppy.tools.common import _find_best_window

    # Threshold for fuzzy matching
    FUZZY_THRESHOLD = 0.95

    # Handle empty inputs early
    if not replacements:
        return {
            "modified": content,
            "diff": "",
            "success": True,
            "error": None,
            "jw_score": None,
        }

    original = content
    modified = content
    modified_lines: list[str] | None = None
    last_jw_score: float | None = None

    for old_str, new_str in replacements:
        # Skip empty old_str - nothing to match
        if not old_str:
            continue

        # Fast path: exact match - replace first occurrence only
        if old_str in modified:
            modified = modified.replace(old_str, new_str, 1)
            # Invalidate cached lines since content changed
            modified_lines = None
            continue

        # Lazy initialization of cached lines for fuzzy matching
        if modified_lines is None:
            modified_lines = modified.splitlines()

        # Pre-compute needle lines and length for cache
        needle_stripped = old_str.rstrip("\n")
        needle_lines = needle_stripped.splitlines()
        needle_len = len(needle_stripped)

        loc, score = _find_best_window(
            modified_lines,
            old_str,
            _needle_lines_cache=needle_lines,
            _needle_len_cache=needle_len,
        )

        last_jw_score = score

        if score < FUZZY_THRESHOLD or loc is None:
            return {
                "modified": original,
                "diff": "",
                "success": False,
                "error": f"No suitable match in content (JW {score:.3f} < {FUZZY_THRESHOLD})",
                "jw_score": score,
            }

        start, end = loc
        # Use slice-assignment to modify lines in-place, preserving cache
        new_lines = new_str.rstrip("\n").splitlines()
        modified_lines[start:end] = new_lines

        # Rebuild the string for subsequent exact matches
        modified = "\n".join(modified_lines)
        if original.endswith("\n") and not modified.endswith("\n"):
            modified += "\n"

    # Generate unified diff
    if modified == original:
        diff_text = ""
    else:
        original_lines = original.splitlines(keepends=True)
        modified_lines_out = modified.splitlines(keepends=True)
        diff_text = "".join(
            difflib.unified_diff(
                original_lines,
                modified_lines_out,
                fromfile="original",
                tofile="modified",
                n=3,
            )
        )

    return {
        "modified": modified,
        "diff": diff_text,
        "success": True,
        "error": None,
        "jw_score": last_jw_score,
    }


def _try_elixir_unified_diff(
    old: str,
    new: str,
    context_lines: int = 3,
    from_file: str = "",
    to_file: str = "",
) -> str | None:
    """Try to route unified_diff through Elixir (bd-41).

    Returns the diff string if Elixir is available and succeeds,
    or None to signal fallback to Python.
    """
    try:
        from code_puppy.native_backend import NativeBackend

        if not NativeBackend._should_use_elixir("edit_ops"):
            return None

        result = NativeBackend._call_elixir(
            "text_unified_diff",
            {
                "old": old,
                "new": new,
                "context_lines": context_lines,
                "from_file": from_file,
                "to_file": to_file,
            },
        )

        return result.get("diff", "")
    except Exception:
        # Any failure → fall through to Python
        return None


def unified_diff(
    old: str,
    new: str,
    context_lines: int = 3,
    from_file: str = "",
    to_file: str = "",
) -> str:
    """Bridge to Elixir unified_diff with difflib.unified_diff fallback.

    Routing priority (bd-41): Elixir → Python

    Args:
        old: Original content
        new: New content
        context_lines: Number of context lines (default 3)
        from_file: Label for original file
        to_file: Label for new file

    Returns:
        Unified diff string
    """
    # bd-41: Try Elixir first
    elixir_result = _try_elixir_unified_diff(old, new, context_lines, from_file, to_file)
    if elixir_result is not None:
        return elixir_result

    # Python fallback using difflib
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=from_file or "original",
            tofile=to_file or "modified",
            n=context_lines,
        )
    )
