"""Regression tests for _read_file_sync tuple contract.

Validates that _read_file_sync always returns a 3-tuple of
(content: str | None, num_tokens: int, error: str | None) and that
each error path produces the correct shape.
"""

import os
import tempfile

import pytest

from code_puppy.tools.file_operations import _read_file_sync


# ---------------------------------------------------------------------------
# 1. Success path
# ---------------------------------------------------------------------------

class TestSuccessReturnsTuple:
    """Happy-path: reading a normal file returns (content, tokens, None)."""

    def test_success_returns_tuple(self, tmp_path):
        f = tmp_path / "sample.txt"
        f.write_text("Hello, world!\nThis is a test file.\n", encoding="utf-8")

        result = _read_file_sync(str(f))

        # Must be a 3-tuple
        assert isinstance(result, tuple)
        assert len(result) == 3

        content, num_tokens, error = result

        # Content matches
        assert content == "Hello, world!\nThis is a test file.\n"
        assert isinstance(content, str)

        # Token count is a positive integer
        assert isinstance(num_tokens, int)
        assert num_tokens > 0

        # No error
        assert error is None

    def test_success_tuple_element_types(self, tmp_path):
        """Extra type-safety check: exact types, not subclasses."""
        f = tmp_path / "types.txt"
        f.write_text("abc", encoding="utf-8")

        content, num_tokens, error = _read_file_sync(str(f))

        assert type(content) is str
        assert type(num_tokens) is int
        assert error is None


# ---------------------------------------------------------------------------
# 2. Oversized file (>10 000 tokens)
# ---------------------------------------------------------------------------

class TestOversizedFile:
    """Files exceeding the 10 000 token budget return (None, 0, error)."""

    def test_oversized_file_returns_tuple_with_none_content(self, tmp_path):
        # ~40 000 characters of repeated text should exceed 10k tokens
        big_content = "The quick brown fox jumps over the lazy dog. " * 1200
        f = tmp_path / "huge.txt"
        f.write_text(big_content, encoding="utf-8")

        result = _read_file_sync(str(f))

        assert isinstance(result, tuple)
        assert len(result) == 3

        content, num_tokens, error = result

        assert content is None
        assert num_tokens == 0
        assert error is not None
        assert "10,000 tokens" in error

    def test_oversized_error_message_is_string(self, tmp_path):
        big_content = "x" * 50000
        f = tmp_path / "huge2.txt"
        f.write_text(big_content, encoding="utf-8")

        _, _, error = _read_file_sync(str(f))

        assert isinstance(error, str)
        assert "10,000 tokens" in error


# ---------------------------------------------------------------------------
# 3. Non-existent file
# ---------------------------------------------------------------------------

class TestNonexistentFile:
    """A path that does not exist returns ('', 0, error_msg)."""

    def test_nonexistent_file_returns_empty_string(self):
        path = "/nonexistent/path/that/does/not/exist.txt"

        result = _read_file_sync(path)

        assert isinstance(result, tuple)
        assert len(result) == 3

        content, num_tokens, error = result

        assert content == ""
        assert num_tokens == 0
        assert isinstance(error, str)
        assert "does not exist" in error


# ---------------------------------------------------------------------------
# 4. Permission denied
# ---------------------------------------------------------------------------

class TestPermissionDenied:
    """A file with no read permission returns ('', 0, error_msg)."""

    def test_permission_denied_returns_empty_string(self, tmp_path):
        f = tmp_path / "no_read.txt"
        f.write_text("secret stuff", encoding="utf-8")

        # Remove all permissions
        f.chmod(0o000)

        try:
            result = _read_file_sync(str(f))

            assert isinstance(result, tuple)
            assert len(result) == 3

            content, num_tokens, error = result

            assert content == ""
            assert num_tokens == 0
            assert error is not None
            assert "PERMISSION DENIED" in error
        finally:
            # Restore permissions so tmp_path cleanup can remove the file
            f.chmod(0o644)


# ---------------------------------------------------------------------------
# 5. Line-range reading
# ---------------------------------------------------------------------------

class TestLineRange:
    """Reading a subset of lines still returns a proper 3-tuple."""

    def test_line_range_success(self, tmp_path):
        f = tmp_path / "lines.txt"
        f.write_text(
            "line one\n"
            "line two\n"
            "line three\n"
            "line four\n"
            "line five\n",
            encoding="utf-8",
        )

        result = _read_file_sync(str(f), start_line=2, num_lines=2)

        assert isinstance(result, tuple)
        assert len(result) == 3

        content, num_tokens, error = result

        assert error is None
        assert isinstance(content, str)
        assert content == "line two\nline three\n"
        assert num_tokens > 0

    def test_line_range_single_line(self, tmp_path):
        f = tmp_path / "single.txt"
        f.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

        content, num_tokens, error = _read_file_sync(str(f), start_line=3, num_lines=1)

        assert error is None
        assert content == "gamma\n"

    def test_line_range_beyond_end(self, tmp_path):
        """Requesting lines past EOF should return what's available."""
        f = tmp_path / "short.txt"
        f.write_text("only one line\n", encoding="utf-8")

        content, num_tokens, error = _read_file_sync(str(f), start_line=5, num_lines=3)

        assert error is None
        assert content == ""
        assert num_tokens > 0  # empty string still has ~0 tokens but estimation may vary

    def test_line_range_invalid_start_line(self, tmp_path):
        f = tmp_path / "inv.txt"
        f.write_text("data\n", encoding="utf-8")

        content, num_tokens, error = _read_file_sync(str(f), start_line=0, num_lines=1)

        assert content == ""
        assert num_tokens == 0
        assert error is not None
        assert "start_line must be >= 1" in error
