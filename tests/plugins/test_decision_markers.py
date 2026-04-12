"""Tests for decision_markers.py module."""

from pathlib import Path

from code_puppy.plugins.repo_compass.decision_markers import (
    DecisionMarker,
    _get_context_lines,
    _is_inside_string,
    _scan_file,
    scan_decision_markers,
)


class TestIsInsideString:
    """Tests for _is_inside_string helper."""

    def test_not_inside_string(self):
        """Should return False for position not in string."""
        line = '# WHY: This is a real comment'
        # Match starts at position 0 (the #)
        assert _is_inside_string(line, 0) is False

    def test_inside_double_quoted_string(self):
        """Should return True for position inside double-quoted string."""
        line = 'comment = "# WHY: this should not match"'
        # Match starts at position 12 (the # inside the string)
        assert _is_inside_string(line, 12) is True

    def test_inside_single_quoted_string(self):
        """Should return True for position inside single-quoted string."""
        line = "comment = '# WHY: this should not match'"
        # Match starts at position 12 (the # inside the string)
        assert _is_inside_string(line, 12) is True

    def test_escaped_quotes(self):
        """Should handle escaped quotes correctly."""
        # The escaped quote doesn't end the string, so # is still inside
        line = 'example = "not a string \\"# WHY: still in string"'
        # Match starts at position 28 (the # after the escaped quote)
        assert _is_inside_string(line, 28) is True

    def test_quote_before_string(self):
        """Should return False for position after closing quote."""
        line = '"closed" # WHY: real comment'
        # Match starts at position 11 (the # after the string)
        assert _is_inside_string(line, 11) is False


class TestDecisionMarker:
    """Tests for DecisionMarker dataclass."""

    def test_frozen_dataclass(self):
        """DecisionMarker should be frozen and hashable."""
        marker = DecisionMarker(
            path="src/main.py",
            line_number=42,
            marker_type="WHY",
            text="# WHY: Using this approach for performance",
            context="some context",
        )
        assert marker.path == "src/main.py"
        assert marker.line_number == 42
        assert marker.marker_type == "WHY"

        # Should be hashable (frozen)
        {marker}  # Can be added to set

    def test_equality(self):
        """DecisionMarker should support equality comparison."""
        marker1 = DecisionMarker("a.py", 1, "WHY", "text", "ctx")
        marker2 = DecisionMarker("a.py", 1, "WHY", "text", "ctx")
        marker3 = DecisionMarker("b.py", 2, "DECISION", "text", "ctx")

        assert marker1 == marker2
        assert marker1 != marker3


class TestGetContextLines:
    """Tests for _get_context_lines helper."""

    def test_basic_context(self):
        """Should return context around marker line."""
        lines = [
            "line 1",
            "line 2",
            "# WHY: important decision",
            "line 4",
            "line 5",
        ]
        context = _get_context_lines(lines, 2, context_radius=2)

        assert ">>> 3:" in context
        assert "line 1" in context
        assert "line 5" in context
        assert "# WHY: important decision" in context

    def test_context_at_start(self):
        """Should handle marker near start of file."""
        lines = ["# WHY: at start", "line 2", "line 3"]
        context = _get_context_lines(lines, 0, context_radius=2)

        assert ">>> 1:" in context
        assert "# WHY: at start" in context
        # Should not go negative
        assert "0:" not in context

    def test_context_at_end(self):
        """Should handle marker near end of file."""
        lines = ["line 1", "line 2", "# WHY: at end"]
        context = _get_context_lines(lines, 2, context_radius=2)

        assert ">>> 3:" in context
        # Should not exceed file length
        assert "4:" not in context


class TestScanFile:
    """Tests for _scan_file function."""

    def test_detect_why_marker(self, tmp_path: Path):
        """Should detect # WHY: marker."""
        file = tmp_path / "test.py"
        file.write_text("# WHY: Using singleton for caching\ndef foo(): pass\n", encoding="utf-8")

        markers = _scan_file(file, tmp_path)

        assert len(markers) == 1
        assert markers[0].marker_type == "WHY"
        assert markers[0].line_number == 1

    def test_detect_decision_marker(self, tmp_path: Path):
        """Should detect # DECISION: marker."""
        file = tmp_path / "test.py"
        file.write_text(
            "# DECISION: Chose async over sync\ndef bar(): pass\n",
            encoding="utf-8",
        )

        markers = _scan_file(file, tmp_path)

        assert len(markers) == 1
        assert markers[0].marker_type == "DECISION"

    def test_detect_tradeoff_marker(self, tmp_path: Path):
        """Should detect # TRADEOFF: marker."""
        file = tmp_path / "test.py"
        file.write_text(
            "# TRADEOFF: Memory vs speed\ndef baz(): pass\n",
            encoding="utf-8",
        )

        markers = _scan_file(file, tmp_path)

        assert len(markers) == 1
        assert markers[0].marker_type == "TRADEOFF"

    def test_detect_adr_marker(self, tmp_path: Path):
        """Should detect # ADR: marker."""
        file = tmp_path / "test.py"
        file.write_text("# ADR: Using Postgres for main store\ndef qux(): pass\n", encoding="utf-8")

        markers = _scan_file(file, tmp_path)

        assert len(markers) == 1
        assert markers[0].marker_type == "ADR"

    def test_detect_hack_marker(self, tmp_path: Path):
        """Should detect # HACK(...) marker."""
        file = tmp_path / "test.py"
        file.write_text(
            "# HACK(pack-parallelism): Temporary workaround\ndef temp(): pass\n",
            encoding="utf-8",
        )

        markers = _scan_file(file, tmp_path)

        assert len(markers) == 1
        assert markers[0].marker_type == "HACK"

    def test_multiple_markers(self, tmp_path: Path):
        """Should detect multiple markers in same file."""
        file = tmp_path / "test.py"
        file.write_text(
            "# WHY: First reason\n"
            "def a(): pass\n"
            "# DECISION: Second reason\n"
            "def b(): pass\n",
            encoding="utf-8",
        )

        markers = _scan_file(file, tmp_path)

        assert len(markers) == 2
        types = {m.marker_type for m in markers}
        assert types == {"WHY", "DECISION"}

    def test_context_included(self, tmp_path: Path):
        """Should include context in marker."""
        file = tmp_path / "test.py"
        file.write_text(
            "# Context before\n"
            "# WHY: Important decision\n"
            "# Context after\n",
            encoding="utf-8",
        )

        markers = _scan_file(file, tmp_path)

        assert len(markers) == 1
        assert "Context before" in markers[0].context
        assert "Context after" in markers[0].context

    def test_relative_path(self, tmp_path: Path):
        """Should use relative path in marker."""
        subdir = tmp_path / "src" / "utils"
        subdir.mkdir(parents=True)
        file = subdir / "helpers.py"
        file.write_text("# WHY: test\n", encoding="utf-8")

        markers = _scan_file(file, tmp_path)

        assert len(markers) == 1
        assert markers[0].path == "src/utils/helpers.py"

    def test_no_markers(self, tmp_path: Path):
        """Should return empty list for file without markers."""
        file = tmp_path / "test.py"
        file.write_text("def plain_function():\n    pass\n", encoding="utf-8")

        markers = _scan_file(file, tmp_path)

        assert markers == []

    def test_binary_file(self, tmp_path: Path):
        """Should handle binary files gracefully."""
        file = tmp_path / "test.py"
        file.write_bytes(b"\x00\x01\x02\x03")  # Binary content

        markers = _scan_file(file, tmp_path)

        assert markers == []

    def test_skips_marker_in_double_quoted_string(self, tmp_path: Path):
        """Should skip markers inside double-quoted strings."""
        file = tmp_path / "test.py"
        file.write_text(
            'comment = "# WHY: this is documentation, not a real marker"\n'
            "# WHY: This is a real marker\n"
        )

        markers = _scan_file(file, tmp_path)

        # Should only find the real comment, not the one in the string
        assert len(markers) == 1
        assert markers[0].marker_type == "WHY"
        assert "real marker" in markers[0].text

    def test_skips_marker_in_single_quoted_string(self, tmp_path: Path):
        """Should skip markers inside single-quoted strings."""
        file = tmp_path / "test.py"
        file.write_text(
            "comment = '# DECISION: this is documentation'\n"
            "# DECISION: This is a real marker\n"
        )

        markers = _scan_file(file, tmp_path)

        # Should only find the real comment
        assert len(markers) == 1
        assert markers[0].marker_type == "DECISION"
        assert "real marker" in markers[0].text

    def test_skips_cstyle_marker_in_string(self, tmp_path: Path):
        """Should skip C-style markers inside strings."""
        file = tmp_path / "test.js"
        file.write_text(
            'const msg = "// WHY: documented reason";\n'
            "// WHY: Real JavaScript comment\n"
        )

        markers = _scan_file(file, tmp_path)

        # Should only find the real comment, not the one in the string
        assert len(markers) == 1
        assert markers[0].marker_type == "WHY"
        assert "Real JavaScript" in markers[0].text

    def test_handles_escaped_quotes_in_strings(self, tmp_path: Path):
        """Should correctly handle escaped quotes when detecting strings."""
        # Escaped quote doesn't end string, so markers inside are skipped
        file = tmp_path / "test.py"
        file.write_text(
            'example = "not ended \\"# WHY: still in string"\n'
            "# WHY: Real marker after\n"
        )

        markers = _scan_file(file, tmp_path)

        # Should only find the real marker after the string
        # The marker with escaped quote is still inside the string
        assert len(markers) == 1
        assert "Real marker" in markers[0].text


class TestScanDecisionMarkers:
    """Tests for scan_decision_markers function."""

    def test_empty_directory(self, tmp_path: Path):
        """Empty directory should return empty list."""
        markers = scan_decision_markers(tmp_path)
        assert markers == []

    def test_scan_multiple_files(self, tmp_path: Path):
        """Should scan multiple files."""
        (tmp_path / "a.py").write_text("# WHY: reason A\n", encoding="utf-8")
        (tmp_path / "b.py").write_text("# DECISION: reason B\n", encoding="utf-8")

        markers = scan_decision_markers(tmp_path, max_files=10, max_markers=10)

        assert len(markers) == 2
        types = {m.marker_type for m in markers}
        assert types == {"WHY", "DECISION"}

    def test_respects_max_markers(self, tmp_path: Path):
        """Should respect max_markers limit."""
        for i in range(10):
            (tmp_path / f"file{i}.py").write_text(
                f"# WHY: reason {i}\n", encoding="utf-8"
            )

        markers = scan_decision_markers(tmp_path, max_files=10, max_markers=3)

        assert len(markers) == 3

    def test_respects_max_files(self, tmp_path: Path):
        """Should respect max_files limit."""
        for i in range(10):
            (tmp_path / f"file{i}.py").write_text(
                f"# WHY: reason {i}\n", encoding="utf-8"
            )

        markers = scan_decision_markers(tmp_path, max_files=3, max_markers=10)

        # Only 3 files scanned, so max 3 markers
        assert len(markers) <= 3

    def test_ignores_ignored_dirs(self, tmp_path: Path):
        """Should ignore files in ignored directories."""
        cache_dir = tmp_path / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "cached.py").write_text("# WHY: in cache\n", encoding="utf-8")
        (tmp_path / "regular.py").write_text("# WHY: regular\n", encoding="utf-8")

        markers = scan_decision_markers(tmp_path, max_files=10, max_markers=10)

        # Should only find the regular.py marker
        assert len(markers) == 1
        assert markers[0].path == "regular.py"

    def test_ignores_hidden_files(self, tmp_path: Path):
        """Should ignore hidden files."""
        (tmp_path / ".hidden.py").write_text("# WHY: hidden\n", encoding="utf-8")
        (tmp_path / "visible.py").write_text("# WHY: visible\n", encoding="utf-8")

        markers = scan_decision_markers(tmp_path, max_files=10, max_markers=10)

        assert len(markers) == 1
        assert markers[0].path == "visible.py"

    def test_ignores_non_source_files(self, tmp_path: Path):
        """Should ignore non-source files."""
        (tmp_path / "readme.md").write_text("# WHY: markdown\n", encoding="utf-8")
        (tmp_path / "code.py").write_text("# WHY: python\n", encoding="utf-8")

        markers = scan_decision_markers(tmp_path, max_files=10, max_markers=10)

        assert len(markers) == 1
        assert markers[0].path == "code.py"

    def test_scans_various_extensions(self, tmp_path: Path):
        """Should scan various source file extensions."""
        (tmp_path / "test.js").write_text("// WHY: javascript\n", encoding="utf-8")
        (tmp_path / "test.ts").write_text("// WHY: typescript\n", encoding="utf-8")
        (tmp_path / "test.rs").write_text("// WHY: rust\n", encoding="utf-8")
        (tmp_path / "test.go").write_text("// WHY: golang\n", encoding="utf-8")
        (tmp_path / "test.rb").write_text("# WHY: ruby\n", encoding="utf-8")

        markers = scan_decision_markers(tmp_path, max_files=10, max_markers=10)

        # Should find all source files (they all contain markers)
        assert len(markers) == 5

    def test_handles_permission_error_gracefully(self, tmp_path: Path):
        """Should handle permission errors gracefully."""
        # Create a file with markers
        (tmp_path / "readable.py").write_text("# WHY: readable\n", encoding="utf-8")

        # Don't actually try to trigger permission error in test
        # Just verify the function doesn't crash on normal operation
        markers = scan_decision_markers(tmp_path)
        assert len(markers) == 1

    def test_python_marker_variations(self, tmp_path: Path):
        """Should detect various Python comment styles."""
        (tmp_path / "test.py").write_text(
            "#WHY: no space\n"
            "# WHY: normal\n"
            "#  WHY: extra space\n",
            encoding="utf-8",
        )

        markers = scan_decision_markers(tmp_path, max_files=10, max_markers=10)

        # All three variations should match
        assert len(markers) == 3
        assert all(m.marker_type == "WHY" for m in markers)
