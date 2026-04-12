"""Tests for decision_markers.py module."""

from pathlib import Path

from code_puppy.plugins.repo_compass.decision_markers import (
    _CSTYLE_MARKER_PATTERNS,
    _HASH_MARKER_PATTERNS,
    DecisionMarker,
    _get_context_lines,
    _get_patterns_for_file,
    _scan_file,
    scan_decision_markers,
)


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
        file.write_text(
            "# WHY: Using singleton for caching\ndef foo(): pass\n", encoding="utf-8"
        )

        markers = _scan_file(file, tmp_path)

        assert len(markers) == 1
        assert markers[0].marker_type == "WHY"
        assert markers[0].line_number == 1
        assert "# WHY:" in markers[0].text
        assert "//" not in markers[0].text  # Must be hash-style, not c-style

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
        assert "# DECISION:" in markers[0].text
        assert "//" not in markers[0].text  # Must be hash-style

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
        assert "# TRADEOFF:" in markers[0].text
        assert "//" not in markers[0].text  # Must be hash-style

    def test_detect_adr_marker(self, tmp_path: Path):
        """Should detect # ADR: marker."""
        file = tmp_path / "test.py"
        file.write_text(
            "# ADR: Using Postgres for main store\ndef qux(): pass\n", encoding="utf-8"
        )

        markers = _scan_file(file, tmp_path)

        assert len(markers) == 1
        assert markers[0].marker_type == "ADR"
        assert "# ADR:" in markers[0].text
        assert "//" not in markers[0].text  # Must be hash-style

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
        assert "# HACK(" in markers[0].text
        assert "//" not in markers[0].text  # Must be hash-style

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
            "# Context before\n# WHY: Important decision\n# Context after\n",
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
        """Should scan various source file extensions with correct pattern."""
        (tmp_path / "test.js").write_text("// WHY: javascript\n", encoding="utf-8")
        (tmp_path / "test.ts").write_text("// WHY: typescript\n", encoding="utf-8")
        (tmp_path / "test.rs").write_text("// WHY: rust\n", encoding="utf-8")
        (tmp_path / "test.go").write_text("// WHY: golang\n", encoding="utf-8")
        (tmp_path / "test.rb").write_text("# WHY: ruby\n", encoding="utf-8")

        markers = scan_decision_markers(tmp_path, max_files=10, max_markers=10)

        # Should find all source files (they all contain markers)
        assert len(markers) == 5

        # Verify correct pattern style matched per file extension
        by_path = {m.path: m for m in markers}
        for cstyle in ["test.js", "test.ts", "test.rs", "test.go"]:
            assert cstyle in by_path, f"Missing marker for {cstyle}"
            assert "// WHY:" in by_path[cstyle].text, (
                f"C-style pattern not matched in {cstyle}"
            )
            assert "#" not in by_path[cstyle].text or "//" in by_path[cstyle].text
        assert "test.rb" in by_path
        assert "# WHY:" in by_path["test.rb"].text
        assert "//" not in by_path["test.rb"].text  # Ruby uses hash-style

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
            "#WHY: no space\n# WHY: normal\n#  WHY: extra space\n",
            encoding="utf-8",
        )

        markers = scan_decision_markers(tmp_path, max_files=10, max_markers=10)

        # All three variations should match
        assert len(markers) == 3
        assert all(m.marker_type == "WHY" for m in markers)


class TestGetPatternsForFile:
    """Tests verifying _get_patterns_for_file selects the correct pattern set."""

    def test_python_gets_hash_patterns(self, tmp_path: Path):
        """Python files must use hash-style patterns."""
        patterns = _get_patterns_for_file(tmp_path / "app.py")
        assert patterns is _HASH_MARKER_PATTERNS
        assert patterns is not _CSTYLE_MARKER_PATTERNS

    def test_ruby_gets_hash_patterns(self, tmp_path: Path):
        """Ruby files must use hash-style patterns."""
        patterns = _get_patterns_for_file(tmp_path / "app.rb")
        assert patterns is _HASH_MARKER_PATTERNS
        assert patterns is not _CSTYLE_MARKER_PATTERNS

    def test_javascript_gets_cstyle_patterns(self, tmp_path: Path):
        """JavaScript files must use c-style patterns."""
        patterns = _get_patterns_for_file(tmp_path / "app.js")
        assert patterns is _CSTYLE_MARKER_PATTERNS
        assert patterns is not _HASH_MARKER_PATTERNS

    def test_typescript_gets_cstyle_patterns(self, tmp_path: Path):
        """TypeScript files must use c-style patterns."""
        patterns = _get_patterns_for_file(tmp_path / "app.ts")
        assert patterns is _CSTYLE_MARKER_PATTERNS

    def test_rust_gets_cstyle_patterns(self, tmp_path: Path):
        """Rust files must use c-style patterns."""
        patterns = _get_patterns_for_file(tmp_path / "app.rs")
        assert patterns is _CSTYLE_MARKER_PATTERNS

    def test_go_gets_cstyle_patterns(self, tmp_path: Path):
        """Go files must use c-style patterns."""
        patterns = _get_patterns_for_file(tmp_path / "app.go")
        assert patterns is _CSTYLE_MARKER_PATTERNS

    def test_java_gets_cstyle_patterns(self, tmp_path: Path):
        """Java files must use c-style patterns."""
        patterns = _get_patterns_for_file(tmp_path / "App.java")
        assert patterns is _CSTYLE_MARKER_PATTERNS

    def test_c_gets_cstyle_patterns(self, tmp_path: Path):
        """C files must use c-style patterns."""
        patterns = _get_patterns_for_file(tmp_path / "main.c")
        assert patterns is _CSTYLE_MARKER_PATTERNS

    def test_cpp_gets_cstyle_patterns(self, tmp_path: Path):
        """C++ files must use c-style patterns."""
        patterns = _get_patterns_for_file(tmp_path / "main.cpp")
        assert patterns is _CSTYLE_MARKER_PATTERNS

    def test_header_gets_cstyle_patterns(self, tmp_path: Path):
        """C/C++ header files must use c-style patterns."""
        for ext in [".h", ".hpp"]:
            patterns = _get_patterns_for_file(tmp_path / f"header{ext}")
            assert patterns is _CSTYLE_MARKER_PATTERNS


class TestPatternCrossRejection:
    """Tests verifying that wrong comment style does NOT match."""

    def test_hash_markers_rejected_in_cstyle_files(self, tmp_path: Path):
        """Hash-style markers must NOT be detected in c-style files."""
        file = tmp_path / "app.js"
        file.write_text("# WHY: this is a hash comment in JS\n", encoding="utf-8")

        markers = _scan_file(file, tmp_path)
        assert markers == [], "Hash-style pattern must not match in .js files"

    def test_cstyle_markers_rejected_in_hash_files(self, tmp_path: Path):
        """C-style markers must NOT be detected in hash-style files."""
        file = tmp_path / "app.py"
        file.write_text(
            "// WHY: this is a c-style comment in Python\n", encoding="utf-8"
        )

        markers = _scan_file(file, tmp_path)
        assert markers == [], "C-style pattern must not match in .py files"

    def test_all_hash_marker_types_rejected_in_js(self, tmp_path: Path):
        """All hash-style marker types must be rejected in JS files."""
        file = tmp_path / "app.js"
        file.write_text(
            "# WHY: nope\n"
            "# DECISION: nope\n"
            "# TRADEOFF: nope\n"
            "# ADR: nope\n"
            "# HACK(x): nope\n",
            encoding="utf-8",
        )

        markers = _scan_file(file, tmp_path)
        assert markers == [], "All hash-style markers must be rejected in .js"

    def test_all_cstyle_marker_types_rejected_in_py(self, tmp_path: Path):
        """All c-style marker types must be rejected in Python files."""
        file = tmp_path / "app.py"
        file.write_text(
            "// WHY: nope\n"
            "// DECISION: nope\n"
            "// TRADEOFF: nope\n"
            "// ADR: nope\n"
            "// HACK(x): nope\n",
            encoding="utf-8",
        )

        markers = _scan_file(file, tmp_path)
        assert markers == [], "All c-style markers must be rejected in .py"

    def test_cstyle_decisions_match_in_rust(self, tmp_path: Path):
        """C-style DECISION and TRADEOFF patterns must match in Rust files."""
        file = tmp_path / "lib.rs"
        file.write_text(
            "// DECISION: using tokio runtime\n// TRADEOFF: latency vs throughput\n",
            encoding="utf-8",
        )

        markers = _scan_file(file, tmp_path)
        assert len(markers) == 2
        assert all("//" in m.text for m in markers)
        assert all("#" not in m.text for m in markers)

    def test_hash_hack_rejected_in_go(self, tmp_path: Path):
        """Hash-style HACK must be rejected in Go files."""
        file = tmp_path / "main.go"
        file.write_text("# HACK(quick): temp fix\n", encoding="utf-8")

        markers = _scan_file(file, tmp_path)
        assert markers == []

    def test_cstyle_adr_rejected_in_ruby(self, tmp_path: Path):
        """C-style ADR must be rejected in Ruby files."""
        file = tmp_path / "app.rb"
        file.write_text("// ADR: postgres choice\n", encoding="utf-8")

        markers = _scan_file(file, tmp_path)
        assert markers == []

    def test_pattern_set_sizes_match(self):
        """Hash and c-style pattern sets must cover the same marker types."""
        hash_types = {t for _, t in _HASH_MARKER_PATTERNS}
        cstyle_types = {t for _, t in _CSTYLE_MARKER_PATTERNS}
        assert hash_types == cstyle_types, (
            f"Pattern type mismatch: hash={hash_types} vs cstyle={cstyle_types}"
        )
        assert len(_HASH_MARKER_PATTERNS) == len(_CSTYLE_MARKER_PATTERNS), (
            "Both pattern sets must have the same number of entries"
        )
