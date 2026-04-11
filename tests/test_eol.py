"""Comprehensive tests for code_puppy/utils/eol.py.

Covers:
- looks_textish: empty, pure text, binary, threshold boundaries, NUL detection
- normalize_eol: CRLF→LF, orphan CR, binary passthrough, empty input
"""


from code_puppy.utils.eol import looks_textish, normalize_eol


# ===========================================================================
# looks_textish
# ===========================================================================


class TestLooksTextish:
    """Tests for the binary-detection heuristic."""

    def test_empty_string_is_text(self) -> None:
        assert looks_textish("") is True

    def test_pure_ascii_text(self) -> None:
        assert looks_textish("Hello, world!\nSecond line.\n") is True

    def test_python_source_code(self) -> None:
        code = 'def foo():\n    return "bar"\n\nif __name__ == "__main__":\n    foo()\n'
        assert looks_textish(code) is True

    def test_text_with_tabs_and_crlf(self) -> None:
        assert looks_textish("col1\tcol2\r\ncol3\tcol4\r\n") is True

    def test_nul_byte_means_binary(self) -> None:
        """NUL byte is the strongest binary signal."""
        assert looks_textish("hello\x00world") is False

    def test_nul_at_start(self) -> None:
        assert looks_textish("\x00abc") is False

    def test_nul_at_end(self) -> None:
        assert looks_textish("abc\x00") is False

    def test_single_nul_byte(self) -> None:
        assert looks_textish("\x00") is False

    def test_high_control_char_ratio_means_binary(self) -> None:
        """String with >10% control characters should be detected as binary."""
        # 8 control chars + 2 printable = 20% control → not text
        content = "\x01\x02\x03\x04\x05\x06\x07\x08ab"
        assert looks_textish(content) is False

    def test_exactly_at_90_percent_threshold(self) -> None:
        """Exactly 90% printable should pass."""
        # 9 printable + 1 control = 90% printable → text
        content = "abcdefghi\x01"
        assert looks_textish(content) is True

    def test_just_below_90_percent_threshold(self) -> None:
        """89% printable should fail."""
        # 89 printable chars + 11 control chars
        content = "a" * 89 + "\x01" * 11
        assert looks_textish(content) is False

    def test_just_above_90_percent_threshold(self) -> None:
        """91% printable should pass."""
        # 91 printable chars + 9 control chars
        content = "a" * 91 + "\x01" * 9
        assert looks_textish(content) is True

    def test_unicode_text_is_text(self) -> None:
        """Unicode with CJK, emoji, etc. should be text."""
        assert looks_textish("日本語テキスト 🐶\n") is True

    def test_whitespace_only_is_text(self) -> None:
        """Pure whitespace (tabs, newlines, spaces) should be text."""
        assert looks_textish("\t\n\r   \n\t") is True

    def test_mixed_whitespace_and_printable(self) -> None:
        assert looks_textish("  hello\n\tworld  \n") is True


# ===========================================================================
# normalize_eol
# ===========================================================================


class TestNormalizeEol:
    """Tests for CRLF→LF normalization with binary safety."""

    def test_empty_string(self) -> None:
        assert normalize_eol("") == ""

    def test_already_lf(self) -> None:
        content = "line1\nline2\nline3\n"
        assert normalize_eol(content) == content

    def test_crlf_to_lf(self) -> None:
        content = "line1\r\nline2\r\nline3\r\n"
        expected = "line1\nline2\nline3\n"
        assert normalize_eol(content) == expected

    def test_mixed_crlf_and_lf(self) -> None:
        content = "line1\r\nline2\nline3\r\n"
        expected = "line1\nline2\nline3\n"
        assert normalize_eol(content) == expected

    def test_orphan_cr_to_lf(self) -> None:
        """Old Mac-style CR-only line endings should become LF."""
        content = "line1\rline2\rline3\r"
        expected = "line1\nline2\nline3\n"
        assert normalize_eol(content) == expected

    def test_mixed_all_three_styles(self) -> None:
        content = "line1\r\nline2\rline3\n"
        expected = "line1\nline2\nline3\n"
        assert normalize_eol(content) == expected

    def test_binary_content_unchanged(self) -> None:
        """Binary content with \r\n bytes should NOT be modified."""
        binary_like = "PK\x00\x03\x04\r\n\x00\x00\x00"
        assert normalize_eol(binary_like) == binary_like

    def test_high_control_content_unchanged(self) -> None:
        """Content that fails the printable ratio should pass through."""
        # 50% control characters → binary → unchanged
        content = "ab\x01\x02\r\ncd\x03\x04"
        assert normalize_eol(content) == content

    def test_no_line_endings(self) -> None:
        content = "just a string"
        assert normalize_eol(content) == content

    def test_single_crlf(self) -> None:
        assert normalize_eol("\r\n") == "\n"

    def test_single_cr(self) -> None:
        assert normalize_eol("\r") == "\n"

    def test_single_lf(self) -> None:
        assert normalize_eol("\n") == "\n"

    def test_consecutive_crlf(self) -> None:
        """Multiple blank lines with CRLF should all convert."""
        content = "a\r\n\r\n\r\nb"
        expected = "a\n\n\nb"
        assert normalize_eol(content) == expected

    def test_real_world_windows_file(self) -> None:
        """Simulate a real Windows Python file."""
        content = (
            "# -*- coding: utf-8 -*-\r\n"
            "import os\r\n"
            "\r\n"
            "def main():\r\n"
            '    print("hello")\r\n'
        )
        expected = (
            "# -*- coding: utf-8 -*-\n"
            "import os\n"
            "\n"
            "def main():\n"
            '    print("hello")\n'
        )
        assert normalize_eol(content) == expected
