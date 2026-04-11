"""Tests for BOM handling in code_puppy.utils.eol."""

from code_puppy.utils.eol import strip_bom, restore_bom

# The UTF-8 BOM character
BOM = "\ufeff"


class TestStripBom:
    def test_strips_utf8_bom(self):
        content = f"{BOM}hello world"
        stripped, bom = strip_bom(content)
        assert stripped == "hello world"
        assert bom == BOM

    def test_no_bom_returns_unchanged(self):
        content = "hello world"
        stripped, bom = strip_bom(content)
        assert stripped == "hello world"
        assert bom == ""

    def test_empty_string(self):
        stripped, bom = strip_bom("")
        assert stripped == ""
        assert bom == ""

    def test_bom_only(self):
        stripped, bom = strip_bom(BOM)
        assert stripped == ""
        assert bom == BOM

    def test_bom_in_middle_not_stripped(self):
        """BOM in the middle of content is NOT stripped (only leading BOM)."""
        content = f"hello{BOM}world"
        stripped, bom = strip_bom(content)
        assert stripped == content
        assert bom == ""

    def test_multiline_with_bom(self):
        content = f"{BOM}line1\nline2\nline3"
        stripped, bom = strip_bom(content)
        assert stripped == "line1\nline2\nline3"
        assert bom == BOM


class TestRestoreBom:
    def test_restores_bom(self):
        result = restore_bom("hello", BOM)
        assert result == f"{BOM}hello"

    def test_no_bom_to_restore(self):
        result = restore_bom("hello", "")
        assert result == "hello"

    def test_roundtrip(self):
        """strip_bom -> modify -> restore_bom preserves BOM."""
        original = f"{BOM}original content"
        stripped, bom = strip_bom(original)
        modified = stripped.replace("original", "modified")
        restored = restore_bom(modified, bom)
        assert restored == f"{BOM}modified content"

    def test_roundtrip_no_bom(self):
        """Roundtrip on non-BOM content is identity."""
        original = "original content"
        stripped, bom = strip_bom(original)
        modified = stripped.replace("original", "modified")
        restored = restore_bom(modified, bom)
        assert restored == "modified content"

    def test_empty_content_with_bom(self):
        result = restore_bom("", BOM)
        assert result == BOM
