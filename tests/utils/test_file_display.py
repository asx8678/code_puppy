"""Tests for file_display utilities (deepagents ADOPT #3, #4, #6).

These tests cover:
- Part 1: O_NOFOLLOW safe file writes
- Part 2: Line number formatting with continuation
- Part 3: Truncation with guidance message
"""

import os
import sys
import tempfile
from unittest import mock

import pytest

from code_puppy.utils.file_display import (
    DEFAULT_TRUNCATION_HINT,
    MAX_LINE_LENGTH,
    TRUNCATION_HINTS,
    format_content_with_line_numbers,
    open_nofollow,
    safe_write_file,
    truncate_with_guidance,
)


# =============================================================================
# Part 2: Line Number Formatting with Continuation (ADOPT #4)
# =============================================================================


class TestFormatContentWithLineNumbers:
    """Test line number formatting with continuation markers."""

    def test_simple_three_line_file(self):
        """Simple 3-line file → numbered output like cat -n style."""
        content = "hello\nworld\n!"
        result = format_content_with_line_numbers(content)

        assert "1\thello" in result
        assert "2\tworld" in result
        assert "3\t!" in result

    def test_list_of_strings_input(self):
        """Accept list of strings as input."""
        lines = ["hello", "world", "!"]
        result = format_content_with_line_numbers(lines)

        assert "1\thello" in result
        assert "2\tworld" in result

    def test_start_line_100(self):
        """Line numbers start at custom value."""
        content = "line1\nline2"
        result = format_content_with_line_numbers(content, start_line=100)

        assert "100\tline1" in result
        assert "101\tline2" in result

    def test_empty_content(self):
        """Empty content → single line with empty content."""
        result = format_content_with_line_numbers("")
        # Empty string produces one line entry with just the line number
        assert "1\t" in result

    def test_empty_list(self):
        """Empty list → empty output."""
        result = format_content_with_line_numbers([])
        assert result == ""

    def test_long_line_split_into_chunks(self):
        """Single long line (12000 chars) → split into 3 chunks with continuation."""
        long_content = "a" * 12000
        result = format_content_with_line_numbers([long_content])

        # Should have 3 chunks with markers 1, 1.1, 1.2
        assert "1\t" in result
        assert "1.1" in result
        assert "1.2" in result

        # Verify total length accounts for all content plus formatting
        lines = result.split("\n")
        assert len(lines) == 3

        # Verify continuation markers are right-aligned
        for line in lines:
            if "1.1" in line or "1.2" in line:
                assert "1." in line

    def test_multiple_long_lines_interleaved(self):
        """Multiple long lines interleaved with normal lines → correct numbering."""
        content = ["short", "b" * 6000, "normal", "c" * 5500]
        result = format_content_with_line_numbers(content)

        lines = result.split("\n")
        # line 1: short (with padding: "     1\t")
        assert any("1\tshort" in line for line in lines)
        # line 2: long (should be split into 2 chunks: 2 and 2.1)
        assert any("     2\t" in line for line in lines)
        assert any("2.1" in line for line in lines)
        # line 3 should be 3 (normal), not affected by line 2's continuation
        assert any("     3\tnormal" in line for line in lines)

    def test_custom_max_line_length(self):
        """Respect custom max_line_length parameter."""
        content = "a" * 30
        result = format_content_with_line_numbers([content], max_line_length=10)

        # Should be split into 3 chunks (30 / 10)
        lines = result.split("\n")
        assert len(lines) == 3

    def test_line_number_width_formatting(self):
        """Line numbers are right-aligned with specified width."""
        content = "line"
        result = format_content_with_line_numbers([content], line_number_width=4)

        # Should have "   1\tline" (3 spaces + 1)
        assert "   1\t" in result

    def test_exact_boundary_no_split(self):
        """Line exactly at max length should NOT be split."""
        content = "a" * MAX_LINE_LENGTH
        result = format_content_with_line_numbers([content])

        lines = result.split("\n")
        # Should be exactly one line
        assert len(lines) == 1
        assert "     1\t" in lines[0]  # With padding


# =============================================================================
# Part 3: Truncation with Guidance (ADOPT #6)
# =============================================================================


class TestTruncateWithGuidance:
    """Test truncation with helpful guidance messages."""

    def test_string_under_limit_unchanged(self):
        """String under limit → unchanged."""
        content = "short text"
        result = truncate_with_guidance(content, limit_chars=1000)

        assert result == content

    def test_string_over_limit_truncated(self):
        """String over limit → truncated + guidance appended."""
        content = "a" * 100000
        result = truncate_with_guidance(content, limit_chars=80_000)

        # Should end with guidance message
        assert result.endswith("]")  # Guidance ends with ]
        assert "truncated" in result.lower()
        assert "paginating" in result.lower()

        # Should be truncated to limit + guidance
        assert len(result) <= 80_000 + 200  # Some buffer for guidance

    def test_list_under_total_unchanged(self):
        """List under total → unchanged."""
        items = ["item1", "item2", "item3"]
        result = truncate_with_guidance(items, limit_chars=1000)

        assert result == items

    def test_list_over_total_truncated(self):
        """List over total → proportionally truncated + guidance item."""
        # Create list where total chars exceed limit
        items = ["x" * 5000 for _ in range(20)]  # 100k total
        result = truncate_with_guidance(items, limit_chars=80_000)

        # Should be shorter list plus guidance
        assert len(result) < len(items)
        assert result[-1].startswith("... [")

    def test_custom_hint(self):
        """Custom hint appears in output."""
        content = "a" * 1000
        custom_hint = "... [custom guidance message here]"
        result = truncate_with_guidance(content, limit_chars=500, hint=custom_hint)

        assert custom_hint in result

    def test_tool_specific_hints(self):
        """Tool-specific hints are used when tool_name provided."""
        content = "a" * 1000

        for tool_name in ["grep", "list_files", "read_file", "shell"]:
            result = truncate_with_guidance(content, limit_chars=500, tool_name=tool_name)
            assert TRUNCATION_HINTS[tool_name] in result

    def test_hint_with_limit_placeholder(self):
        """Hint with {limit} placeholder gets formatted."""
        content = "a" * 1000
        hint = "Limit was {limit} chars"
        result = truncate_with_guidance(content, limit_chars=500, hint=hint)

        assert "Limit was 500 chars" in result

    def test_zero_length_input(self):
        """Zero-length input → unchanged."""
        result = truncate_with_guidance("")
        assert result == ""

    def test_empty_list_input(self):
        """Empty list → unchanged."""
        result = truncate_with_guidance([])
        assert result == []

    def test_exactly_at_limit_not_truncated(self):
        """Exactly at limit → not truncated."""
        content = "a" * 80_000
        result = truncate_with_guidance(content, limit_chars=80_000)

        assert result == content
        assert "truncated" not in result.lower()

    def test_default_truncation_hint_format(self):
        """Default hint contains expected components."""
        assert "{limit}" in DEFAULT_TRUNCATION_HINT
        assert "truncated" in DEFAULT_TRUNCATION_HINT.lower()


# =============================================================================
# Part 1: O_NOFOLLOW Safe File Writes (ADOPT #3)
# =============================================================================


class TestOpenNoFollow:
    """Test O_NOFOLLOW file opening for security."""

    @pytest.mark.skipif(
        not hasattr(os, "O_NOFOLLOW"),
        reason="O_NOFOLLOW not available on this platform (Windows)"
    )
    def test_regular_file_write_succeeds(self, tmp_path):
        """Normal file creation still works."""
        target = tmp_path / "normal_file.txt"

        with open_nofollow(str(target), "w") as f:
            f.write("safe content")

        assert target.exists()
        assert target.read_text() == "safe content"

    @pytest.mark.skipif(
        not hasattr(os, "O_NOFOLLOW"),
        reason="O_NOFOLLOW not available on this platform (Windows)"
    )
    def test_symlink_write_fails_with_eloop(self, tmp_path):
        """Writing through symlink fails with ELOOP errno."""
        # Create a real file
        real_file = tmp_path / "real_target.txt"
        real_file.write_text("original content")

        # Create a symlink pointing to the real file
        symlink = tmp_path / "evil_link.txt"
        symlink.symlink_to(real_file)

        # Attempting to write through symlink should fail
        with pytest.raises(OSError) as exc_info:
            with open_nofollow(str(symlink), "w") as f:
                f.write("attacker content")

        # Verify it's the right error (ELOOP = too many symbolic links)
        import errno
        assert exc_info.value.errno == errno.ELOOP

        # Verify target file was NOT modified
        assert real_file.read_text() == "original content"



    @pytest.mark.skipif(
        hasattr(os, "O_NOFOLLOW"),
        reason="Only for systems without O_NOFOLLOW"
    )
    def test_fallback_on_windows(self, tmp_path):
        """On Windows without O_NOFOLLOW, should use regular open."""
        target = tmp_path / "windows_file.txt"

        with open_nofollow(str(target), "w") as f:
            f.write("windows content")

        assert target.exists()
        assert target.read_text() == "windows content"

    def test_unsupported_mode_raises(self, tmp_path):
        """Only 'w' and 'wb' modes are supported."""
        target = tmp_path / "test.txt"

        with pytest.raises(ValueError) as exc_info:
            open_nofollow(str(target), "r")

        assert "Unsupported mode" in str(exc_info.value)

    def test_binary_mode_write(self, tmp_path):
        """Binary mode writes work correctly."""
        target = tmp_path / "binary_file.bin"

        with open_nofollow(str(target), "wb") as f:
            f.write(b"binary content")

        assert target.exists()
        assert target.read_bytes() == b"binary content"


class TestSafeWriteFile:
    """Test safe_write_file convenience function."""

    @pytest.mark.skipif(
        not hasattr(os, "O_NOFOLLOW"),
        reason="O_NOFOLLOW not available on this platform"
    )
    def test_safe_write_regular_file(self, tmp_path):
        """safe_write_file works for regular files."""
        target = tmp_path / "safe.txt"

        safe_write_file(str(target), "safe content")

        assert target.exists()
        assert target.read_text() == "safe content"

    @pytest.mark.skipif(
        not hasattr(os, "O_NOFOLLOW"),
        reason="O_NOFOLLOW not available on this platform"
    )
    def test_safe_write_through_symlink_fails(self, tmp_path):
        """safe_write_file fails when trying to write through symlink."""
        real_file = tmp_path / "real.txt"
        real_file.write_text("original")

        symlink = tmp_path / "link.txt"
        symlink.symlink_to(real_file)

        import errno
        with pytest.raises(OSError) as exc_info:
            safe_write_file(str(symlink), "attacker")

        assert exc_info.value.errno == errno.ELOOP
        assert real_file.read_text() == "original"


# =============================================================================
# Integration with existing tools
# =============================================================================


class TestIntegrationWithTools:
    """Test integration with actual tool usage patterns."""

    def test_file_operations_import(self):
        """file_operations module can import file_display utilities."""
        from code_puppy.tools.file_operations import (
            format_content_with_line_numbers,
            truncate_with_guidance,
        )

        # Verify they work
        result = format_content_with_line_numbers(["line1", "line2"])
        assert "1\tline1" in result

    def test_utils_module_exports(self):
        """All utilities are exported from utils module."""
        from code_puppy.utils import (
            format_content_with_line_numbers,
            open_nofollow,
            safe_write_file,
            truncate_with_guidance,
        )

        # Just verify they exist and are callable
        assert callable(format_content_with_line_numbers)
        assert callable(truncate_with_guidance)
        assert callable(open_nofollow)
        assert callable(safe_write_file)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
