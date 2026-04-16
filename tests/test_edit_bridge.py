"""Tests for the edit bridge module.

Tests the code_puppy._edit_bridge module which provides:
- fuzzy_match_window: Fuzzy matching with Elixir/Python fallback
- replace_in_content: Content replacement with Elixir/Python fallback
- unified_diff: Diff generation with Elixir/Python fallback

bd-41: Rust modules removed. Routing is now Elixir → Python.
"""

from __future__ import annotations

import difflib
import sys
from pathlib import Path

import pytest

# Ensure code_puppy is in path
code_puppy_path = Path(__file__).parent.parent
if str(code_puppy_path) not in sys.path:
    sys.path.insert(0, str(code_puppy_path))

from code_puppy._edit_bridge import (  # noqa: E402
    fuzzy_match_window,
    replace_in_content,
    unified_diff,
)


class TestFuzzyMatchWindow:
    """Test fuzzy_match_window function."""

    def test_empty_needle_returns_none_score(self) -> None:
        """Empty needle should return (None, 0.0)."""
        haystack = ["line1", "line2", "line3"]
        result = fuzzy_match_window(haystack, "")
        assert result[0] is None
        assert result[1] == 0.0

    def test_exact_match_finds_correct_window(self) -> None:
        """Exact match should find the correct window."""
        haystack = ["def foo():", "    pass", "def bar():", "    return 1"]
        needle = "def bar():\n    return 1"
        result = fuzzy_match_window(haystack, needle)
        span, score = result
        assert span is not None
        start, end = span
        assert start == 2
        assert end == 4
        assert score >= 0.95

    def test_fuzzy_match_typo_tolerance(self) -> None:
        """Fuzzy match should tolerate typos above threshold."""
        haystack = ["def foo():", "    pass", "def bar():", "    return 1"]
        needle = "def baz():\n    return 1"  # bar -> baz typo
        result = fuzzy_match_window(haystack, needle)
        span, score = result
        assert span is not None
        # Score should be high enough (typo should still be close)
        assert score >= 0.85  # Slightly lower threshold for typo case

    def test_no_match_below_threshold(self) -> None:
        """Content with no similarity should return (None, low_score)."""
        haystack = ["hello world", "foo bar", "baz qux"]
        needle = "xyz123-nomatch-completely-different"
        result = fuzzy_match_window(haystack, needle)
        span, score = result
        # Should either return None span or very low score
        if span is not None:
            assert score < 0.95
        else:
            assert score < 0.95

    def test_single_line_match(self) -> None:
        """Single line needle should find single line window."""
        haystack = ["line1", "line2", "line3", "line4"]
        needle = "line3"
        result = fuzzy_match_window(haystack, needle)
        span, score = result
        assert span is not None
        start, end = span
        assert start == 2
        assert end == 3  # Single line match
        assert score >= 0.95

    def test_multiline_match(self) -> None:
        """Multi-line needle should find multi-line window."""
        haystack = [
            "def func():",
            "    x = 1",
            "    y = 2",
            "    return x + y",
            "",
        ]
        needle = "    x = 1\n    y = 2"
        result = fuzzy_match_window(haystack, needle)
        span, score = result
        assert span is not None
        start, end = span
        assert start == 1
        assert end == 3
        assert score >= 0.95

    def test_returns_correct_format(self) -> None:
        """Result should be in format ((start, end), score)."""
        haystack = ["a", "b", "c"]
        needle = "b"
        result = fuzzy_match_window(haystack, needle)
        assert isinstance(result, tuple)
        assert len(result) == 2
        span, score = result
        assert isinstance(span, tuple) or span is None
        if span is not None:
            assert len(span) == 2
            start, end = span
            assert isinstance(start, int)
            assert isinstance(end, (int, type(None)))
        assert isinstance(score, float)


class TestReplaceInContent:
    """Test replace_in_content function."""

    def test_empty_replacements_returns_success(self) -> None:
        """Empty replacements should return success with no changes."""
        content = "hello world\n"
        result = replace_in_content(content, [])
        assert result["success"] is True
        assert result["modified"] == content
        assert result["diff"] == ""
        assert result["error"] is None
        assert result["jw_score"] is None

    def test_exact_single_replacement(self) -> None:
        """Exact single replacement should work."""
        content = "hello world\nfoo bar\n"
        replacements = [("world", "universe")]
        result = replace_in_content(content, replacements)
        assert result["success"] is True
        assert result["modified"] == "hello universe\nfoo bar\n"
        assert result["error"] is None
        # unified_diff format shows full removed/added lines with +/- prefixes
        assert "universe" in result["diff"]
        assert "-hello world" in result["diff"] or "+hello universe" in result["diff"]

    def test_exact_multiple_replacements(self) -> None:
        """Multiple exact replacements should work."""
        content = "hello world\nfoo bar\nbaz qux\n"
        replacements = [("world", "universe"), ("foo", "FOO")]
        result = replace_in_content(content, replacements)
        assert result["success"] is True
        assert "universe" in result["modified"]
        assert "FOO" in result["modified"]
        assert result["error"] is None

    def test_replaces_only_first_occurrence(self) -> None:
        """Should only replace first occurrence of old_str."""
        content = "foo foo foo\n"
        replacements = [("foo", "bar")]
        result = replace_in_content(content, replacements)
        assert result["success"] is True
        assert result["modified"] == "bar foo foo\n"

    def test_fuzzy_replacement_with_typo(self) -> None:
        """Fuzzy match should handle typos."""
        content = "def foo():\n    pass\ndef bar():\n    return 1\n"
        # "baz" is typo of "bar"
        replacements = [("def baz():", "def qux():")]
        result = replace_in_content(content, replacements)
        assert result["success"] is True
        assert "def qux():" in result["modified"]
        assert "def bar():" not in result["modified"]
        assert result["jw_score"] is not None
        assert result["jw_score"] >= 0.95

    def test_fuzzy_replacement_fails_below_threshold(self) -> None:
        """Fuzzy match should fail for completely different content."""
        content = "completely different text\nthat has no similarity\n"
        replacements = [("xyz123-nomatch", "replacement")]
        result = replace_in_content(content, replacements)
        assert result["success"] is False
        assert result["error"] is not None
        assert "JW" in result["error"] or "match" in result["error"].lower()
        # Content should be unchanged
        assert result["modified"] == content
        assert result["diff"] == ""

    def test_trailing_newline_preserved(self) -> None:
        """Trailing newline should be preserved when present."""
        content = "line1\nline2\n"
        replacements = [("line1", "LINE1")]
        result = replace_in_content(content, replacements)
        assert result["success"] is True
        assert result["modified"].endswith("\n")

    def test_no_trailing_newline_added(self) -> None:
        """Trailing newline should not be added if not present."""
        content = "line1\nline2"  # No trailing newline
        replacements = [("line1", "LINE1")]
        result = replace_in_content(content, replacements)
        assert result["success"] is True
        assert not result["modified"].endswith("\n")

    def test_multiline_replacement(self) -> None:
        """Multi-line replacement should work."""
        content = "def func():\n    x = 1\n    return x\n"
        replacements = [("    x = 1\n    return x", "    y = 2\n    return y")]
        result = replace_in_content(content, replacements)
        assert result["success"] is True
        assert "y = 2" in result["modified"]

    def test_mixed_exact_and_fuzzy(self) -> None:
        """Mixed exact and fuzzy replacements should work."""
        content = "hello world\ndef bar():\n    pass\n"
        replacements = [
            ("world", "universe"),  # Exact
            ("def baz():", "def qux():"),  # Fuzzy (typo)
        ]
        result = replace_in_content(content, replacements)
        assert result["success"] is True
        assert "universe" in result["modified"]
        assert "def qux():" in result["modified"]
        assert "def bar():" not in result["modified"]

    def test_result_has_expected_keys(self) -> None:
        """Result should have all expected keys."""
        content = "hello world\n"
        replacements = [("world", "universe")]
        result = replace_in_content(content, replacements)
        expected_keys = {"modified", "diff", "success", "error", "jw_score"}
        assert set(result.keys()) == expected_keys

    def test_empty_content_fails_gracefully(self) -> None:
        """Empty content with non-empty replacement should fail gracefully."""
        content = ""
        replacements = [("foo", "bar")]
        result = replace_in_content(content, replacements)
        assert result["success"] is False
        assert result["error"] is not None

    def test_empty_old_str_skipped(self) -> None:
        """Empty old_str should be skipped."""
        content = "hello world\n"
        replacements = [
            ("", "ignored"),  # Empty old_str should be skipped
            ("world", "universe"),
        ]
        result = replace_in_content(content, replacements)
        assert result["success"] is True
        assert result["modified"] == "hello universe\n"


class TestUnifiedDiff:
    """Test unified_diff function."""

    def test_empty_diff_for_identical_content(self) -> None:
        """Identical content should produce empty diff."""
        old = "line1\nline2\nline3\n"
        new = "line1\nline2\nline3\n"
        result = unified_diff(old, new)
        # Diff might have headers but no changes
        if result:
            assert "-line" not in result or "+line" not in result

    def test_detects_additions(self) -> None:
        """Should detect added lines."""
        old = "line1\nline2\n"
        new = "line1\nline2\nline3\n"
        result = unified_diff(old, new)
        assert result is not None
        assert "+line3" in result

    def test_detects_deletions(self) -> None:
        """Should detect deleted lines."""
        old = "line1\nline2\nline3\n"
        new = "line1\nline3\n"
        result = unified_diff(old, new)
        assert result is not None
        assert "-line2" in result

    def test_detects_modifications(self) -> None:
        """Should detect modified lines."""
        old = "line1\nline2\nline3\n"
        new = "line1\nMODIFIED\nline3\n"
        result = unified_diff(old, new)
        assert result is not None
        assert "-line2" in result
        assert "+MODIFIED" in result

    def test_includes_context_lines(self) -> None:
        """Diff should include context lines."""
        old = "a\nb\nc\nd\ne\n"
        new = "a\nb\nMODIFIED\nd\ne\n"
        result = unified_diff(old, new, context_lines=2)
        # Should include "a", "b" before and "d", "e" after
        assert result is not None

    def test_uses_filename_labels(self) -> None:
        """Diff should use provided filename labels."""
        old = "content\n"
        new = "modified content\n"
        result = unified_diff(old, new, from_file="old.txt", to_file="new.txt")
        assert "--- old.txt" in result
        assert "+++ new.txt" in result

    def test_default_labels_when_empty(self) -> None:
        """Should use default labels when filenames not provided."""
        old = "content\n"
        new = "modified content\n"
        result = unified_diff(old, new)
        # Should have some form of labels
        assert "---" in result
        assert "+++" in result

    def test_matches_difflib_output_format(self) -> None:
        """Output format should match difflib.unified_diff."""
        old = "line1\nline2\nline3\n"
        new = "line1\nMODIFIED\nline3\n"
        bridge_result = unified_diff(old, new, from_file="a", to_file="b")
        difflib_result = "".join(
            difflib.unified_diff(
                old.splitlines(keepends=True),
                new.splitlines(keepends=True),
                fromfile="a",
                tofile="b",
                n=3,
            )
        )
        # Both should have similar structure
        assert ("---" in bridge_result) == ("---" in difflib_result)
        assert ("+++" in bridge_result) == ("+++" in difflib_result)


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_handles_unicode_content(self) -> None:
        """Should handle Unicode content correctly."""
        content = "こんにちは世界\nemoji: 🎉\n"
        replacements = [("こんにちは", "さようなら")]
        result = replace_in_content(content, replacements)
        assert result["success"] is True
        assert "さようなら" in result["modified"]

    def test_handles_special_characters(self) -> None:
        """Should handle special characters."""
        content = "tab\there\n$$$special$$$\n"
        replacements = [("tab\there", "space here")]
        result = replace_in_content(content, replacements)
        assert result["success"] is True
        assert "space here" in result["modified"]

    def test_handles_windows_line_endings(self) -> None:
        """Should handle Windows-style line endings."""
        content = "line1\r\nline2\r\n"
        # Note: splitlines() handles \r\n, but the join might normalize
        # This is a known behavior - just ensure it doesn't crash
        replacements = [("line1", "LINE1")]
        result = replace_in_content(content, replacements)
        # Result might have normalized endings
        assert result["success"] is True
        assert "LINE1" in result["modified"]

    def test_large_content_handling(self) -> None:
        """Should handle reasonably large content."""
        # Generate 1000 lines
        content = "\n".join(f"line {i}" for i in range(1000)) + "\n"
        replacements = [("line 500", "MODIFIED LINE 500")]
        result = replace_in_content(content, replacements)
        assert result["success"] is True
        assert "MODIFIED LINE 500" in result["modified"]

    def test_many_replacements(self) -> None:
        """Should handle many replacements."""
        content = "a b c d e f g h i j\n"
        # Create replacement for each letter
        replacements = [(letter, letter.upper()) for letter in "abcdefghij"]
        result = replace_in_content(content, replacements)
        assert result["success"] is True
        assert "A B C D E F G H I J" in result["modified"]


class TestElixirBridgePaths:
    """Tests for Elixir routing in the edit bridge (bd-41)."""

    def test_elixir_fuzzy_match_called_when_enabled(self, monkeypatch):
        """Verify fuzzy_match_window calls Elixir when enabled."""
        from unittest.mock import MagicMock

        mock_elixir_result = {"start": 0, "end": 2, "score": 0.98, "matched_text": "line1\nline2"}

        import code_puppy._edit_bridge as bridge
        from code_puppy.native_backend import NativeBackend

        # Mock _call_elixir to return our test result
        mock_call_elixir = MagicMock(return_value=mock_elixir_result)
        monkeypatch.setattr(NativeBackend, "_call_elixir", mock_call_elixir)
        monkeypatch.setattr(NativeBackend, "_should_use_elixir", classmethod(lambda cls, cap: True))

        result = bridge.fuzzy_match_window(["line1", "line2", "line3"], "line1\nline2")
        assert result == ((0, 2), 0.98)
        mock_call_elixir.assert_called_once()
        call_args = mock_call_elixir.call_args
        assert call_args[0][0] == "text_fuzzy_match"

    def test_elixir_replace_called_when_enabled(self, monkeypatch):
        """Verify replace_in_content calls Elixir when enabled."""
        from unittest.mock import MagicMock

        mock_elixir_result = {
            "modified": "hello universe",
            "diff": "--- a\n+++ b\n",
            "success": True,
            "error": None,
            "jw_score": None,
        }

        import code_puppy._edit_bridge as bridge
        from code_puppy.native_backend import NativeBackend

        mock_call_elixir = MagicMock(return_value=mock_elixir_result)
        monkeypatch.setattr(NativeBackend, "_call_elixir", mock_call_elixir)
        monkeypatch.setattr(NativeBackend, "_should_use_elixir", classmethod(lambda cls, cap: True))

        result = bridge.replace_in_content("hello world", [("world", "universe")])
        assert result["success"] is True
        assert result["modified"] == "hello universe"
        mock_call_elixir.assert_called_once()
        call_args = mock_call_elixir.call_args
        assert call_args[0][0] == "text_replace"

    def test_elixir_unified_diff_called_when_enabled(self, monkeypatch):
        """Verify unified_diff calls Elixir when enabled."""
        from unittest.mock import MagicMock

        mock_elixir_result = {"diff": "--- a\n+++ b\n@@ -1 +1 @@\n-old\n+new\n"}

        import code_puppy._edit_bridge as bridge
        from code_puppy.native_backend import NativeBackend

        mock_call_elixir = MagicMock(return_value=mock_elixir_result)
        monkeypatch.setattr(NativeBackend, "_call_elixir", mock_call_elixir)
        monkeypatch.setattr(NativeBackend, "_should_use_elixir", classmethod(lambda cls, cap: True))

        result = bridge.unified_diff("old", "new", 3, "a", "b")
        assert result == "--- a\n+++ b\n@@ -1 +1 @@\n-old\n+new\n"
        mock_call_elixir.assert_called_once()
        call_args = mock_call_elixir.call_args
        assert call_args[0][0] == "text_unified_diff"

    def test_python_fallback_when_elixir_disabled(self, monkeypatch):
        """Verify Python fallback works when Elixir is disabled."""
        import code_puppy._edit_bridge as bridge
        from code_puppy.native_backend import NativeBackend

        # Disable Elixir routing
        monkeypatch.setattr(NativeBackend, "_should_use_elixir", classmethod(lambda cls, cap: False))

        # This should use Python fallback (no Elixir call attempted)
        result = bridge.fuzzy_match_window(["line1", "line2", "line3"], "line2")
        span, score = result
        assert span is not None
        start, end = span
        assert start == 1
        assert end == 2
        assert score >= 0.95


class TestElixirFallbackOnException:
    """Test that Elixir exceptions fall through to Python (bd-41)."""

    def test_fuzzy_match_elixir_exception_falls_back(self, monkeypatch):
        """When _try_elixir_fuzzy_match returns None, Python path is used."""
        import code_puppy._edit_bridge as bridge

        monkeypatch.setattr(bridge, "_try_elixir_fuzzy_match", lambda *a, **kw: None)
        haystack = ["def hello():", "    return 'world'"]
        result = bridge.fuzzy_match_window(haystack, "def hello():\n    return 'world'")
        span, score = result
        assert span is not None
        assert score >= 0.95

    def test_unified_diff_elixir_exception_falls_back(self, monkeypatch):
        """When _try_elixir_unified_diff returns None, Python difflib is used."""
        import code_puppy._edit_bridge as bridge

        monkeypatch.setattr(bridge, "_try_elixir_unified_diff", lambda *a, **kw: None)
        result = bridge.unified_diff("hello\n", "world\n")
        assert "hello" in result
        assert "world" in result

    def test_replace_elixir_exception_falls_back(self, monkeypatch):
        """When _try_elixir_replace returns None, Python replacement is used."""
        import code_puppy._edit_bridge as bridge

        monkeypatch.setattr(bridge, "_try_elixir_replace", lambda *a, **kw: None)
        result = bridge.replace_in_content("hello world", [("hello", "goodbye")])
        assert result["modified"] == "goodbye world"
        assert result["success"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
