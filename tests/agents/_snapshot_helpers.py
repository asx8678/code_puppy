"""Helpers for snapshot testing of system prompts.

Based on deepagents' pattern (tests/unit_tests/smoke_tests/test_system_prompt.py).
"""

from __future__ import annotations

import re
from pathlib import Path


SNAPSHOT_DIR = Path(__file__).parent.parent / "snapshots" / "system_prompts"
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)


def normalize_for_snapshot(text: str) -> str:
    """Normalize dynamic content in system prompts for deterministic snapshots.

    Replaces dynamic values with placeholders to ensure snapshots are stable
    across runs, machines, and dates.

    Normalizations applied:
    - Date patterns (YYYY-MM-DD) -> <DATE>
    - Agent IDs (name-xxxxxx format) -> <AGENT_ID>
    - Absolute paths -> <WORKING_DIR>
    - Session IDs -> <SESSION_ID>
    - User-specific paths (home dirs) -> <HOME>
    - Current working directory paths -> <CWD>

    Args:
        text: The original system prompt text.

    Returns:
        Normalized text suitable for snapshot comparison.
    """
    result = text

    # Normalize dates (YYYY-MM-DD format)
    result = re.sub(r"\d{4}-\d{2}-\d{2}", "<DATE>", result)

    # Normalize agent IDs like "code-puppy-a3f2b1" or "pack-leader-123456"
    # Match pattern: word-word-6hex or similar agent ID formats
    result = re.sub(r"[a-z]+-[a-z]+-[a-f0-9]{6,8}", "<AGENT_ID>", result)

    # Normalize paths that look like the current working directory
    # This handles absolute paths that include the project path
    cwd = str(Path.cwd())
    result = result.replace(cwd, "<CWD>")

    # Normalize home directory paths
    home = str(Path.home())
    result = result.replace(home, "<HOME>")

    # Normalize macOS platform-specific info (can vary by machine)
    # Example: "macOS-14.5-arm64-arm-64bit" -> "<PLATFORM>"
    result = re.sub(
        r"macOS-\d+\.\d+-[a-zA-Z0-9_-]+-[a-zA-Z0-9_-]+-[a-zA-Z0-9_-]+",
        "<PLATFORM>",
        result,
    )

    # Normalize Linux platform strings similarly
    result = re.sub(
        r"Linux-[a-zA-Z0-9_-]+-([a-zA-Z0-9_-]+)-.*",
        r"Linux-<ARCH>-\1-<KERNEL>",
        result,
    )

    return result


def assert_snapshot(name: str, actual: str, *, update: bool) -> None:
    """Compare actual text to a snapshot file, or write it if update=True.

    Args:
        name: Unique name for this snapshot (usually the agent name).
        actual: The text to compare / save.
        update: If True, write the actual text to the snapshot file (refreshing it).
                If False, compare against the existing snapshot.
                Raises AssertionError on mismatch.

    Raises:
        AssertionError: If content differs from the saved snapshot (and update=False),
                       or if a new snapshot was created (first-time setup).
    """
    snapshot_path = SNAPSHOT_DIR / f"{name}.md"

    if update or not snapshot_path.exists():
        snapshot_path.write_text(actual, encoding="utf-8")
        if update:
            return
        # First-time creation — let the test know to re-run
        raise AssertionError(
            f"Created new snapshot at {snapshot_path}. "
            f"Re-run tests to verify, or commit the snapshot if correct."
        )

    expected = snapshot_path.read_text(encoding="utf-8")
    if actual != expected:
        # Provide a compact diff hint
        raise AssertionError(
            f"Snapshot mismatch for '{name}'.\n"
            f"File: {snapshot_path}\n"
            f"Expected length: {len(expected)}, Actual length: {len(actual)}\n"
            f"First diff at char {_first_diff_position(expected, actual)}.\n"
            f"If this change is intentional, run: "
            f"pytest tests/agents/test_system_prompt_snapshots.py --update-snapshots"
        )


def _first_diff_position(a: str, b: str) -> int:
    """Return the character index of the first difference, or min length if one is a prefix."""
    for i, (ca, cb) in enumerate(zip(a, b)):
        if ca != cb:
            return i
    return min(len(a), len(b))
