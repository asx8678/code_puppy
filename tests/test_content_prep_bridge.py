"""Tests for content_prep_bridge module.

Covers prepare_content and format_line_numbers with both
Rust-accelerated (when available) and Python fallback paths.
"""

from __future__ import annotations

from code_puppy.content_prep_bridge import (
    RUST_AVAILABLE,
    format_line_numbers,
    prepare_content,
    _looks_textish,
    _detect_encoding,
    _python_prepare_content,
    _python_format_line_numbers,
)


# =============================================================================
# RUST_AVAILABLE flag tests
# =============================================================================


class TestRustAvailableFlag:
    """Test that RUST_AVAILABLE flag exists and is properly typed."""

    def test_rust_available_flag_exists(self) -> None:
        """RUST_AVAILABLE flag must exist as a boolean."""
        assert isinstance(RUST_AVAILABLE, bool)

    def test_rust_available_is_defined(self) -> None:
        """Flag should be defined as True or False."""
        # Just verify it's defined (may be True or False depending on env)
        assert RUST_AVAILABLE is True or RUST_AVAILABLE is False


# =============================================================================
# prepare_content tests
# =============================================================================


class TestPrepareContentPlainText:
    """Test prepare_content with plain text input."""

    def test_plain_text_bytes(self) -> None:
        """Plain ASCII text should be detected as text with no flags."""
        raw = b"Hello, World!"
        result = prepare_content(raw)

        assert result["text"] == "Hello, World!"
        assert result["is_binary"] is False
        assert result["had_bom"] is False
        assert result["had_crlf"] is False
        assert result["encoding"] in ("utf-8", "utf-8-sig")

    def test_multiline_text(self) -> None:
        """Multi-line text should preserve line structure."""
        raw = b"Line 1\nLine 2\nLine 3\n"
        result = prepare_content(raw)

        assert result["text"] == "Line 1\nLine 2\nLine 3\n"
        assert result["is_binary"] is False
        assert result["had_bom"] is False
        assert result["had_crlf"] is False

    def test_empty_content(self) -> None:
        """Empty content should return empty text, text mode."""
        result = prepare_content(b"")

        assert result["text"] == ""
        assert result["is_binary"] is False
        assert result["had_bom"] is False
        assert result["had_crlf"] is False
        assert result["encoding"] == "utf-8"


class TestPrepareContentBOM:
    """Test prepare_content with UTF-8 BOM bytes."""

    def test_bom_bytes_stripped(self) -> None:
        """UTF-8 BOM should be detected and stripped."""
        raw = b"\xef\xbb\xbfHello World"
        result = prepare_content(raw)

        assert result["text"] == "Hello World"
        assert result["had_bom"] is True
        assert result["is_binary"] is False

    def test_bom_only_content(self) -> None:
        """Content that is only BOM should result in empty text."""
        raw = b"\xef\xbb\xbf"
        result = prepare_content(raw)

        assert result["text"] == ""
        assert result["had_bom"] is True

    def test_bom_with_multiline(self) -> None:
        """BOM with multi-line content should be handled correctly."""
        raw = b"\xef\xbb\xbfLine 1\nLine 2\n"
        result = prepare_content(raw)

        assert result["text"] == "Line 1\nLine 2\n"
        assert result["had_bom"] is True


class TestPrepareContentCRLF:
    """Test prepare_content with CRLF line endings."""

    def test_crlf_normalized(self) -> None:
        """CRLF sequences should be detected and normalized to LF."""
        raw = b"Line 1\r\nLine 2\r\n"
        result = prepare_content(raw)

        assert result["text"] == "Line 1\nLine 2\n"
        assert result["had_crlf"] is True
        assert result["is_binary"] is False

    def test_mixed_line_endings(self) -> None:
        """Mixed CRLF and LF should all become LF."""
        raw = b"Line 1\r\nLine 2\nLine 3\r\n"
        result = prepare_content(raw)

        assert result["text"] == "Line 1\nLine 2\nLine 3\n"
        assert result["had_crlf"] is True

    def test_orphan_cr_normalized(self) -> None:
        """Orphan CR (not part of CRLF) should be normalized too."""
        raw = b"Line 1\rLine 2\r"
        result = prepare_content(raw)

        # Orphan CRs get normalized to LF
        assert "\n" in result["text"]
        assert "\r" not in result["text"]


class TestPrepareContentBinary:
    """Test prepare_content with binary content detection."""

    def test_nul_bytes_detected_as_binary(self) -> None:
        """NUL bytes anywhere in content should mark as binary."""
        raw = b"Hello\x00World"
        result = prepare_content(raw)

        assert result["is_binary"] is True
        # NUL bytes are valid UTF-8, so they remain in the decoded text
        # The key is that is_binary=True, not that NULs get replaced

    def test_single_nul_byte(self) -> None:
        """Single NUL byte marks content as binary."""
        raw = b"\x00"
        result = prepare_content(raw)

        assert result["is_binary"] is True

    def test_high_control_char_ratio(self) -> None:
        """Content with >10% control characters should be binary."""
        # 8 control chars + 2 printable = 20% control → binary
        raw = b"\x01\x02\x03\x04\x05\x06\x07\x08ab"
        result = prepare_content(raw)

        assert result["is_binary"] is True

    def test_binary_with_bom(self) -> None:
        """Binary content that has BOM should still be detected as binary."""
        raw = b"\xef\xbb\xbfHello\x00World"
        result = prepare_content(raw)

        assert result["is_binary"] is True
        assert result["had_bom"] is True
        assert not result["text"].startswith("\ufeff")  # BOM stripped even for binary

    def test_binary_passthrough_no_eol_change(self) -> None:
        """Binary content should pass through without EOL normalization."""
        raw = b"PK\x03\x04\r\n\x00\x00\x00"  # Zip-like binary header
        result = prepare_content(raw)

        assert result["is_binary"] is True
        # Binary content: CRLF detected but NOT normalized in output
        assert result["had_crlf"] is True
        assert "\r\n" in result["text"]  # CRLF preserved in binary output


class TestPrepareContentUnicode:
    """Test prepare_content with unicode content."""

    def test_utf8_unicode_text(self) -> None:
        """UTF-8 encoded unicode should be handled correctly."""
        text = "Hello 世界 🌍"
        raw = text.encode("utf-8")
        result = prepare_content(raw)

        assert result["text"] == text
        assert result["is_binary"] is False
        assert result["encoding"] == "utf-8"

    def test_utf8_unicode_with_crlf(self) -> None:
        """Unicode content with CRLF should normalize correctly."""
        text = "Line 1\r\n世界\r\n🌍"
        raw = text.encode("utf-8")
        result = prepare_content(raw)

        expected = "Line 1\n世界\n🌍"
        assert result["text"] == expected
        assert result["had_crlf"] is True


class TestPrepareContentEncodingDetection:
    """Test encoding detection in prepare_content."""

    def test_utf8_detected(self) -> None:
        """Clean UTF-8 content should detect as utf-8."""
        raw = b"Hello World"
        result = _python_prepare_content(raw)
        assert result["encoding"] == "utf-8"

    def test_utf8_sig_detected(self) -> None:
        """Content with BOM should detect as utf-8-sig."""
        raw = b"\xef\xbb\xbfHello World"
        result = _python_prepare_content(raw)
        assert result["encoding"] == "utf-8-sig"

    def test_empty_encoding(self) -> None:
        """Empty content should default to utf-8."""
        result = _python_prepare_content(b"")
        assert result["encoding"] == "utf-8"


# =============================================================================
# format_line_numbers tests
# =============================================================================


class TestFormatLineNumbersBasic:
    """Test basic format_line_numbers functionality."""

    def test_simple_two_lines(self) -> None:
        """Simple 2-line content gets numbered output."""
        content = "hello\nworld"
        result = format_line_numbers(content)

        assert "     1\thello" in result
        assert "     2\tworld" in result

    def test_single_line(self) -> None:
        """Single line without newline still gets numbered."""
        content = "hello"
        result = format_line_numbers(content)

        assert "     1\thello" == result

    def test_empty_content(self) -> None:
        """Empty content produces single numbered empty line."""
        result = format_line_numbers("")

        assert result == "     1\t"

    def test_trailing_newline(self) -> None:
        """Content ending with newline gets empty line numbered."""
        content = "hello\n"
        result = format_line_numbers(content)

        lines = result.split("\n")
        assert len(lines) == 2
        assert "     1\thello" == lines[0]
        assert "     2\t" == lines[1]


class TestFormatLineNumbersStartLine:
    """Test format_line_numbers with custom start_line."""

    def test_start_line_100(self) -> None:
        """Line numbers should start at custom value."""
        content = "line1\nline2"
        result = format_line_numbers(content, start_line=100)

        assert "   100\tline1" in result
        assert "   101\tline2" in result

    def test_start_line_1000(self) -> None:
        """Large line numbers should format correctly."""
        content = "line1\nline2"
        result = format_line_numbers(content, start_line=1000)

        assert "  1000\tline1" in result
        assert "  1001\tline2" in result


class TestFormatLineNumbersContinuation:
    """Test format_line_numbers with long line continuation."""

    def test_long_line_split(self) -> None:
        """Long line (12000 chars) should split into 3 chunks."""
        long_line = "a" * 12000
        result = format_line_numbers(long_line)

        assert "     1\t" in result  # First chunk
        assert "   1.1\t" in result  # Second chunk
        assert "   1.2\t" in result  # Third chunk

    def test_exact_boundary_no_split(self) -> None:
        """Line exactly at boundary should NOT be split."""
        line = "a" * 5000
        result = format_line_numbers(line)

        assert ".1" not in result
        assert result == f"     1\t{line}"

    def test_just_over_boundary(self) -> None:
        """Line just over boundary (5001 chars) should split into 2 chunks."""
        line = "a" * 5001
        result = format_line_numbers(line)

        lines = result.split("\n")
        assert len(lines) == 2
        assert lines[0].startswith("     1\t")
        assert lines[1].startswith("   1.1\t")

    def test_multiple_long_lines(self) -> None:
        """Multiple long lines get separate continuation numbering."""
        content = "x" * 7500 + "\n" + "y" * 6000
        result = format_line_numbers(content)

        # Line 1: x * 7500 → split into 2 chunks: 1 and 1.1
        # Line 2: y * 6000 → split into 2 chunks: 2 and 2.1
        assert "     1\t" in result
        assert "   1.1\t" in result
        assert "     2\t" in result
        assert "   2.1\t" in result


class TestFormatLineNumbersCustomOptions:
    """Test format_line_numbers with custom parameters."""

    def test_custom_max_line_length(self) -> None:
        """Custom max_line_length should be respected."""
        line = "a" * 30
        result = format_line_numbers(line, max_line_length=10)

        # Should be split into 3 chunks (30 / 10)
        lines = result.split("\n")
        assert len(lines) == 3

    def test_custom_line_number_width(self) -> None:
        """Custom line_number_width should affect padding."""
        content = "hello"
        result = format_line_numbers(content, line_number_width=4)

        # Should have "   1\t" (3 spaces + 1)
        assert "   1\t" in result

    def test_continuation_marker_with_large_line_number(self) -> None:
        """Continuation markers should work with large line numbers."""
        long_line = "a" * 10000  # 2 chunks needed
        result = format_line_numbers(long_line, start_line=1000)

        # "1000.1" marker should be present
        assert "1000.1" in result


class TestFormatLineNumbersUnicode:
    """Test format_line_numbers with unicode content."""

    def test_unicode_content(self) -> None:
        """Unicode content should be handled correctly."""
        content = "héllo\nwörld"
        result = format_line_numbers(content)

        assert "     1\théllo" in result
        assert "     2\twörld" in result

    def test_unicode_long_line_char_based(self) -> None:
        """Long lines with unicode should use CHARACTER-based chunking.

        Python: len('£' * 3000) == 3000 characters
        Even though it's 6000 bytes in UTF-8.
        """
        # 3000 '£' characters = 3000 chars < 5000 limit
        # Should NOT be split (character-based, not byte-based)
        line = "£" * 3000
        result = format_line_numbers(line)

        # Single line, no continuation
        assert ".1\t" not in result
        assert "     1\t" in result

    def test_unicode_over_char_limit(self) -> None:
        """5001 '£' chars > 5000 limit should get continuation."""
        line = "£" * 5001
        result = format_line_numbers(line)

        assert "   1.1\t" in result


# =============================================================================
# Internal helper function tests
# =============================================================================


class TestLooksTextish:
    """Test the _looks_textish helper function."""

    def test_empty_is_text(self) -> None:
        """Empty bytes are considered text."""
        assert _looks_textish(b"") is True

    def test_pure_ascii(self) -> None:
        """Pure ASCII content is text."""
        assert _looks_textish(b"Hello, World!") is True

    def test_nul_is_binary(self) -> None:
        """NUL byte anywhere marks as binary."""
        assert _looks_textish(b"hello\x00world") is False

    def test_90_percent_threshold(self) -> None:
        """Exactly 90% printable should pass."""
        # 9 printable + 1 control = 90% printable
        content = b"abcdefghi\x01"
        assert _looks_textish(content) is True

    def test_below_threshold(self) -> None:
        """89% printable should fail."""
        # 89 printable + 11 control
        content = b"a" * 89 + b"\x01" * 11
        assert _looks_textish(content) is False

    def test_common_whitespace_counts_as_printable(self) -> None:
        """\t, \n, \r should count as printable."""
        assert _looks_textish(b"col1\tcol2\r\ncol3") is True


class TestDetectEncoding:
    """Test the _detect_encoding helper function."""

    def test_empty_is_utf8(self) -> None:
        assert _detect_encoding(b"") == "utf-8"

    def test_utf8_bom_detected(self) -> None:
        raw = b"\xef\xbb\xbfHello"
        assert _detect_encoding(raw) == "utf-8-sig"

    def test_plain_utf8(self) -> None:
        assert _detect_encoding(b"Hello World") == "utf-8"

    def test_utf16_le_bom(self) -> None:
        raw = b"\xff\xfeHello"
        assert _detect_encoding(raw) == "utf-16-le"

    def test_utf16_be_bom(self) -> None:
        raw = b"\xfe\xffHello"
        assert _detect_encoding(raw) == "utf-16-be"

    def test_latin1_fallback(self) -> None:
        """Invalid UTF-8 bytes fall back to latin-1."""
        raw = b"\x80\x81\x82"  # Invalid UTF-8 sequence
        assert _detect_encoding(raw) == "latin-1"


# =============================================================================
# Python fallback function tests
# =============================================================================


class TestPythonPrepareContent:
    """Direct tests of the Python fallback implementation."""

    def test_python_fallback_plain(self) -> None:
        raw = b"Hello World"
        result = _python_prepare_content(raw)

        assert result["text"] == "Hello World"
        assert result["is_binary"] is False

    def test_python_fallback_bom(self) -> None:
        raw = b"\xef\xbb\xbfHello"
        result = _python_prepare_content(raw)

        assert result["text"] == "Hello"
        assert result["had_bom"] is True

    def test_python_fallback_crlf(self) -> None:
        raw = b"Line 1\r\nLine 2"
        result = _python_prepare_content(raw)

        assert result["text"] == "Line 1\nLine 2"
        assert result["had_crlf"] is True


class TestPythonFormatLineNumbers:
    """Direct tests of the Python fallback for format_line_numbers."""

    def test_python_fallback_simple(self) -> None:
        result = _python_format_line_numbers("hello\nworld")

        assert "     1\thello" in result
        assert "     2\tworld" in result

    def test_python_fallback_empty(self) -> None:
        result = _python_format_line_numbers("")
        assert result == "     1\t"

    def test_python_fallback_continuation(self) -> None:
        long_line = "a" * 12000
        result = _python_format_line_numbers(long_line)

        assert "   1.1\t" in result
        assert "   1.2\t" in result


# =============================================================================
# Integration tests
# =============================================================================


class TestBridgeIntegration:
    """Integration tests for the full bridge module."""

    def test_all_functions_callable(self) -> None:
        """All public functions should be callable without errors."""
        # prepare_content
        result1 = prepare_content(b"test")
        assert isinstance(result1, dict)
        assert "text" in result1

        # format_line_numbers
        result2 = format_line_numbers("test")
        assert isinstance(result2, str)

    def test_result_dict_has_all_keys(self) -> None:
        """prepare_content result should have all required keys."""
        result = prepare_content(b"test")

        required_keys = ["text", "is_binary", "had_bom", "had_crlf", "encoding"]
        for key in required_keys:
            assert key in result, f"Missing key: {key}"

    def test_format_line_numbers_returns_string(self) -> None:
        """format_line_numbers should always return a string."""
        result = format_line_numbers("any content here")
        assert isinstance(result, str)

    def test_roundtrip_consistency(self) -> None:
        """Calling twice on same input should produce same output."""
        raw = b"Hello\r\nWorld\n\xef\xbb\xbfNotBOM"

        result1 = prepare_content(raw)
        result2 = prepare_content(raw)

        assert result1 == result2
