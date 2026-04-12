"""Tests for the marker_merge module.

Tests cover all three cases of write_with_markers:
1. File does not exist → create with optional placeholder + marked section
2. File exists WITHOUT markers → append marked section at bottom
3. File exists WITH markers → replace only the managed section

Plus idempotency and edge cases.
"""

import re
from pathlib import Path

import pytest

from code_puppy.plugins.repo_compass.marker_merge import (
    read_managed_section,
    write_with_markers,
)


class TestCase1NewFile:
    """Case 1: File does not exist → create with optional placeholder."""

    def test_creates_file_with_placeholder_and_marked_section(self, tmp_path: Path):
        """Case 1a: New file with placeholder creates file with placeholder + marked section."""
        path = tmp_path / "new_file.txt"
        content = "managed content here"
        placeholder = "# This is a placeholder\n# More placeholder text"
        marker_tag = "MANAGED_SECTION"

        write_with_markers(path, content, marker_tag, placeholder=placeholder)

        assert path.exists()
        file_content = path.read_text(encoding="utf-8")

        # Should contain placeholder
        assert "# This is a placeholder" in file_content
        assert "# More placeholder text" in file_content

        # Should contain markers and managed content
        assert "<!-- MANAGED_SECTION:START" in file_content
        assert "managed content here" in file_content
        assert "<!-- MANAGED_SECTION:END -->" in file_content

        # Verify structure: placeholder comes before markers
        assert file_content.index("# This is a placeholder") < file_content.index(
            "<!-- MANAGED_SECTION:START"
        )

    def test_creates_file_without_placeholder(self, tmp_path: Path):
        """Case 1b: New file with NO placeholder creates file with just marked section."""
        path = tmp_path / "no_placeholder.txt"
        content = "only managed content"
        marker_tag = "MY_TAG"

        write_with_markers(path, content, marker_tag, placeholder=None)

        assert path.exists()
        file_content = path.read_text(encoding="utf-8")

        # Should start with marker (no placeholder)
        assert file_content.startswith("<!-- MY_TAG:START")
        assert "only managed content" in file_content
        assert "<!-- MY_TAG:END -->" in file_content


class TestCase2ExistingWithoutMarkers:
    """Case 2: File exists WITHOUT markers → append at bottom."""

    def test_appends_to_existing_file_without_markers(self, tmp_path: Path):
        """Case 2: Appends marked section to existing file that has no markers."""
        path = tmp_path / "existing.txt"

        # Create existing file without markers
        existing = "# Existing content\nSome existing text\nMore lines"
        path.write_text(existing, encoding="utf-8")

        content = "new managed content"
        marker_tag = "UPDATE_SECTION"

        write_with_markers(path, content, marker_tag)

        file_content = path.read_text(encoding="utf-8")

        # Should preserve existing content
        assert "# Existing content" in file_content
        assert "Some existing text" in file_content

        # Should append markers and content
        assert "<!-- UPDATE_SECTION:START" in file_content
        assert "new managed content" in file_content
        assert "<!-- UPDATE_SECTION:END -->" in file_content

        # Markers should come after existing content
        assert file_content.index("More lines") < file_content.index(
            "<!-- UPDATE_SECTION:START"
        )

    def test_appends_with_newline_if_file_missing_trailing_newline(self, tmp_path: Path):
        """Case 2: Adds newline separator when existing file lacks trailing newline."""
        path = tmp_path / "no_trailing_newline.txt"

        # Create file without trailing newline
        path.write_text("no newline at end", encoding="utf-8")

        write_with_markers(path, "managed", "TAG")

        file_content = path.read_text(encoding="utf-8")

        # Should have newline before markers
        assert "no newline at end\n<!-- TAG:START" in file_content

    def test_appends_directly_if_file_has_trailing_newline(self, tmp_path: Path):
        """Case 2: Doesn't add extra newline when file already ends with one."""
        path = tmp_path / "with_trailing_newline.txt"

        # Create file with trailing newline
        path.write_text("has newline at end\n", encoding="utf-8")

        write_with_markers(path, "managed", "TAG")

        file_content = path.read_text(encoding="utf-8")

        # Should not have double newline
        assert "has newline at end\n\n<!-- TAG:START" not in file_content
        assert "has newline at end\n<!-- TAG:START" in file_content


class TestCase3ExistingWithMarkers:
    """Case 3: File exists WITH markers → replace only managed section."""

    def test_replaces_only_managed_section(self, tmp_path: Path):
        """Case 3: Replaces only content between markers, leaves rest intact."""
        path = tmp_path / "with_markers.txt"

        # Create file with markers
        initial_content = (
            "# Header\n"
            "Header content\n"
            "<!-- SECTION:START — Auto-generated by Code Puppy. Do not edit below. -->\n"
            "old managed content\n"
            "<!-- SECTION:END -->\n"
            "# Footer\n"
            "Footer content"
        )
        path.write_text(initial_content, encoding="utf-8")

        # Update with new content
        write_with_markers(path, "new managed content", "SECTION")

        file_content = path.read_text(encoding="utf-8")

        # Header and footer should be preserved
        assert "# Header" in file_content
        assert "Header content" in file_content
        assert "# Footer" in file_content
        assert "Footer content" in file_content

        # Managed content should be updated
        assert "new managed content" in file_content
        assert "old managed content" not in file_content

    def test_replaces_multiline_managed_content(self, tmp_path: Path):
        """Case 3: Handles multiline content replacement correctly."""
        path = tmp_path / "multiline.txt"

        initial = (
            "BEFORE\n"
            "<!-- ML:START — Auto-generated by Code Puppy. Do not edit below. -->\n"
            "line1\n"
            "line2\n"
            "line3\n"
            "<!-- ML:END -->\n"
            "AFTER"
        )
        path.write_text(initial, encoding="utf-8")

        new_content = "new1\nnew2"
        write_with_markers(path, new_content, "ML")

        file_content = path.read_text(encoding="utf-8")

        assert "BEFORE" in file_content
        assert "AFTER" in file_content
        assert "new1\nnew2" in file_content
        assert "line1" not in file_content
        assert "line2" not in file_content

    def test_preserves_content_outside_multiple_sections(self, tmp_path: Path):
        """Case 3: Only replaces the section with matching marker_tag."""
        path = tmp_path / "multi_section.txt"

        initial = (
            "<!-- OTHER:START — Auto-generated by Code Puppy. Do not edit below. -->\n"
            "other section content\n"
            "<!-- OTHER:END -->\n"
            "MIDDLE\n"
            "<!-- TARGET:START — Auto-generated by Code Puppy. Do not edit below. -->\n"
            "target old content\n"
            "<!-- TARGET:END -->\n"
            "TAIL"
        )
        path.write_text(initial, encoding="utf-8")

        write_with_markers(path, "target new content", "TARGET")

        file_content = path.read_text(encoding="utf-8")

        # Other section should be untouched
        assert "other section content" in file_content
        # Middle and tail preserved
        assert "MIDDLE" in file_content
        assert "TAIL" in file_content
        # Target section updated
        assert "target new content" in file_content
        assert "target old content" not in file_content


class TestIdempotency:
    """Idempotency: calling write_with_markers twice = same as once."""

    def test_idempotent_same_content(self, tmp_path: Path):
        """Calling twice with same content produces same result as once."""
        path = tmp_path / "idempotent.txt"
        content = "stable content"
        marker_tag = "IDEM"

        # First write
        write_with_markers(path, content, marker_tag)
        first_result = path.read_text(encoding="utf-8")

        # Second write with same content
        write_with_markers(path, content, marker_tag)
        second_result = path.read_text(encoding="utf-8")

        assert first_result == second_result

    def test_idempotent_with_placeholder(self, tmp_path: Path):
        """Idempotency also works when file was created with placeholder."""
        path = tmp_path / "idem_placeholder.txt"
        placeholder = "# Placeholder text"
        content = "managed section"
        marker_tag = "IDEM_P"

        # First write
        write_with_markers(path, content, marker_tag, placeholder=placeholder)
        first_result = path.read_text(encoding="utf-8")

        # Second write (placeholder not used on second write since file exists)
        write_with_markers(path, content, marker_tag)
        second_result = path.read_text(encoding="utf-8")

        assert first_result == second_result


class TestReadManagedSection:
    """Tests for read_managed_section helper function."""

    def test_reads_content_between_markers(self, tmp_path: Path):
        """Reads back the managed content correctly."""
        path = tmp_path / "read_test.txt"

        content = "the managed content\nwith multiple lines"
        write_with_markers(path, content, "READ_TAG")

        result = read_managed_section(path, "READ_TAG")

        assert result == content

    def test_returns_none_for_nonexistent_file(self, tmp_path: Path):
        """Returns None when file doesn't exist."""
        path = tmp_path / "does_not_exist.txt"

        result = read_managed_section(path, "ANY_TAG")

        assert result is None

    def test_returns_none_when_no_markers(self, tmp_path: Path):
        """Returns None when file exists but has no matching markers."""
        path = tmp_path / "no_markers.txt"
        path.write_text("just some content", encoding="utf-8")

        result = read_managed_section(path, "MISSING_TAG")

        assert result is None

    def test_returns_none_for_wrong_marker_tag(self, tmp_path: Path):
        """Returns None when file has markers but for different tag."""
        path = tmp_path / "wrong_tag.txt"

        write_with_markers(path, "content", "CORRECT_TAG")

        result = read_managed_section(path, "WRONG_TAG")

        assert result is None

    def test_returns_empty_string_for_empty_section(self, tmp_path: Path):
        """Returns empty string when section exists but is empty."""
        path = tmp_path / "empty_section.txt"

        write_with_markers(path, "", "EMPTY")

        result = read_managed_section(path, "EMPTY")

        assert result == ""

    def test_reads_after_update(self, tmp_path: Path):
        """Read reflects updates after write_with_markers replaces content."""
        path = tmp_path / "read_after_update.txt"

        # Initial write
        write_with_markers(path, "version 1", "V")

        # Update
        write_with_markers(path, "version 2", "V")

        result = read_managed_section(path, "V")

        assert result == "version 2"


class TestMarkerTagEscaping:
    """Marker tags with special regex characters don't crash."""

    def test_tag_with_dot(self, tmp_path: Path):
        """Tag containing dots (like version numbers) works correctly."""
        path = tmp_path / "dot_tag.txt"
        tag = "v1.0.0"

        write_with_markers(path, "content", tag)
        result = read_managed_section(path, tag)

        assert result == "content"

        # Should also handle updates
        write_with_markers(path, "updated", tag)
        result = read_managed_section(path, tag)
        assert result == "updated"

    def test_tag_with_brackets(self, tmp_path: Path):
        """Tag containing brackets works correctly."""
        path = tmp_path / "bracket_tag.txt"
        tag = "section[main]"

        write_with_markers(path, "content", tag)
        result = read_managed_section(path, tag)

        assert result == "content"

    def test_tag_with_plus(self, tmp_path: Path):
        """Tag containing plus signs works correctly."""
        path = tmp_path / "plus_tag.txt"
        tag = "c++_section"

        write_with_markers(path, "content", tag)
        result = read_managed_section(path, tag)

        assert result == "content"

    def test_tag_with_star(self, tmp_path: Path):
        """Tag containing asterisks works correctly."""
        path = tmp_path / "star_tag.txt"
        tag = "section*wildcard"

        write_with_markers(path, "content", tag)
        result = read_managed_section(path, tag)

        assert result == "content"

    def test_tag_with_question_mark(self, tmp_path: Path):
        """Tag containing question marks works correctly."""
        path = tmp_path / "question_tag.txt"
        tag = "what?section"

        write_with_markers(path, "content", tag)
        result = read_managed_section(path, tag)

        assert result == "content"

    def test_tag_with_dollar_sign(self, tmp_path: Path):
        """Tag containing dollar signs works correctly."""
        path = tmp_path / "dollar_tag.txt"
        tag = "price_$99"

        write_with_markers(path, "content", tag)
        result = read_managed_section(path, tag)

        assert result == "content"

    def test_tag_with_backslash(self, tmp_path: Path):
        """Tag containing backslashes works correctly."""
        path = tmp_path / "backslash_tag.txt"
        tag = "path\\to\\section"

        write_with_markers(path, "content", tag)
        result = read_managed_section(path, tag)

        assert result == "content"

    def test_tag_with_multiple_special_chars(self, tmp_path: Path):
        """Tag with multiple regex special characters works correctly."""
        path = tmp_path / "complex_tag.txt"
        tag = "section[v1.0.0]*test+?$"

        write_with_markers(path, "content", tag)
        result = read_managed_section(path, tag)

        assert result == "content"

        # Verify idempotency with complex tag
        write_with_markers(path, "content", tag)
        result = read_managed_section(path, tag)
        assert result == "content"


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_content(self, tmp_path: Path):
        """Writing empty content works correctly."""
        path = tmp_path / "empty.txt"

        write_with_markers(path, "", "EMPTY")

        result = read_managed_section(path, "EMPTY")
        assert result == ""

        file_content = path.read_text(encoding="utf-8")
        assert "<!-- EMPTY:START" in file_content
        assert "<!-- EMPTY:END -->" in file_content

    def test_content_with_special_characters(self, tmp_path: Path):
        """Content with special characters is preserved."""
        path = tmp_path / "special.txt"

        content = "Special: <html> & \"quotes\" 'apostrophes'"
        write_with_markers(path, content, "SPECIAL")

        result = read_managed_section(path, "SPECIAL")
        assert result == content

    def test_content_looking_like_markers(self, tmp_path: Path):
        """Content that looks like markers is handled correctly."""
        path = tmp_path / "fake_markers.txt"

        content = "<!-- FAKE:START -->\nnot a real marker\n<!-- FAKE:END -->"
        write_with_markers(path, content, "REAL")

        result = read_managed_section(path, "REAL")
        assert result == content

    def test_single_line_file_append(self, tmp_path: Path):
        """Appending to single-line file without newline works."""
        path = tmp_path / "single.txt"
        path.write_text("single", encoding="utf-8")

        write_with_markers(path, "managed", "M")

        content = path.read_text(encoding="utf-8")
        assert "single\n<!-- M:START" in content

    def test_unicode_content(self, tmp_path: Path):
        """Unicode content is handled correctly."""
        path = tmp_path / "unicode.txt"

        content = "Unicode: 你好 🎉 émojis café"
        write_with_markers(path, content, "UNI")

        result = read_managed_section(path, "UNI")
        assert result == content

    def test_large_content(self, tmp_path: Path):
        """Large content doesn't cause issues."""
        path = tmp_path / "large.txt"

        content = "x" * 100000  # 100KB of content
        write_with_markers(path, content, "LARGE")

        result = read_managed_section(path, "LARGE")
        assert result == content

    def test_multiple_updates_preserve_surrounding(self, tmp_path: Path):
        """Multiple updates preserve content outside markers."""
        path = tmp_path / "multiple.txt"

        # Initial file with content outside markers
        path.write_text(
            "HEADER\n<!-- S:START — Auto-generated by Code Puppy. Do not edit below. -->\n"
            "v1\n<!-- S:END -->\nFOOTER",
            encoding="utf-8",
        )

        # Multiple updates
        for i in range(2, 6):
            write_with_markers(path, f"v{i}", "S")

        final_content = path.read_text(encoding="utf-8")

        assert "HEADER" in final_content
        assert "FOOTER" in final_content
        assert "v5" in final_content
        assert "v1" not in final_content


class TestMarkerFormat:
    """Verify exact marker format matches specification."""

    def test_exact_start_marker_format(self, tmp_path: Path):
        """Start marker uses exact expected string format."""
        path = tmp_path / "format.txt"

        write_with_markers(path, "x", "TAG")

        content = path.read_text(encoding="utf-8")

        expected_start = "<!-- TAG:START — Auto-generated by Code Puppy. Do not edit below. -->"
        assert expected_start in content

    def test_exact_end_marker_format(self, tmp_path: Path):
        """End marker uses exact expected string format."""
        path = tmp_path / "format.txt"

        write_with_markers(path, "x", "TAG")

        content = path.read_text(encoding="utf-8")

        expected_end = "<!-- TAG:END -->"
        assert expected_end in content

    def test_marker_survival_roundtrip(self, tmp_path: Path):
        """Markers survive round-trips through write/read cycles."""
        path = tmp_path / "roundtrip.txt"
        tag = "ROUNDTRIP"

        # First write
        write_with_markers(path, "original", tag)
        content1 = path.read_text(encoding="utf-8")

        # Second write (simulating a different process reading and writing)
        write_with_markers(path, "updated", tag)
        content2 = path.read_text(encoding="utf-8")

        # Markers should still be detectable
        result = read_managed_section(path, tag)
        assert result == "updated"

        # The start marker should be identical in both versions
        start_marker = "<!-- ROUNDTRIP:START — Auto-generated by Code Puppy. Do not edit below. -->"
        assert start_marker in content1
        assert start_marker in content2
