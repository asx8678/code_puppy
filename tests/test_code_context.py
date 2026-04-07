"""Tests for the code_context module.

Tests the CodeContext, CodeExplorer, and related functionality.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from code_puppy.code_context import (
    CodeContext,
    CodeExplorer,
    FileOutline,
    SymbolInfo,
    enhance_read_file_result,
    explore_directory,
    format_outline,
    get_code_context,
    get_file_outline,
)
from code_puppy.turbo_parse_bridge import TURBO_PARSE_AVAILABLE


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def sample_python_file():
    """Create a sample Python file for testing."""
    content = '''
"""Sample module for testing."""
import os
from typing import List

class MyClass:
    """A sample class."""

    def __init__(self):
        self.value = 0

    def method1(self) -> int:
        """First method."""
        return self.value

    def method2(self, x: int) -> int:
        """Second method."""
        return x + self.value

def standalone_function():
    """A standalone function."""
    return 42

CONSTANT = "test"
'''
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(content)
        path = f.name

    yield path

    # Cleanup
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def sample_directory(tmp_path):
    """Create a sample directory structure for testing."""
    # Create Python files
    (tmp_path / "main.py").write_text('''
def main():
    print("Hello")

class App:
    def run(self):
        main()
''')

    (tmp_path / "utils.py").write_text('''
def helper():
    return "helper"
''')

    # Create subdirectory
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    (subdir / "module.py").write_text('''
class SubModule:
    pass
''')

    # Create unsupported file
    (tmp_path / "readme.txt").write_text("Hello")

    yield str(tmp_path)


@pytest.fixture
def explorer():
    """Create a fresh CodeExplorer instance."""
    return CodeExplorer(enable_cache=False)


# -----------------------------------------------------------------------------
# SymbolInfo Tests
# -----------------------------------------------------------------------------


class TestSymbolInfo:
    """Tests for the SymbolInfo class."""

    def test_symbol_info_creation(self):
        """Test creating a SymbolInfo."""
        symbol = SymbolInfo(
            name="test_func",
            kind="function",
            start_line=10,
            end_line=20,
        )

        assert symbol.name == "test_func"
        assert symbol.kind == "function"
        assert symbol.start_line == 10
        assert symbol.end_line == 20
        assert symbol.is_top_level
        assert symbol.size_lines == 11

    def test_symbol_info_from_dict(self):
        """Test creating SymbolInfo from dictionary."""
        data = {
            "name": "MyClass",
            "kind": "class",
            "start_line": 5,
            "end_line": 15,
            "start_col": 0,
            "end_col": 10,
            "parent": None,
            "docstring": "A class",
        }

        symbol = SymbolInfo.from_dict(data)
        assert symbol.name == "MyClass"
        assert symbol.kind == "class"
        assert symbol.docstring == "A class"

    def test_symbol_info_to_dict(self):
        """Test converting SymbolInfo to dictionary."""
        symbol = SymbolInfo(
            name="method1",
            kind="method",
            start_line=10,
            end_line=15,
            parent="MyClass",
        )

        result = symbol.to_dict()
        assert result["name"] == "method1"
        assert result["kind"] == "method"
        assert result["parent"] == "MyClass"
        assert result["children"] == []

    def test_symbol_with_children(self):
        """Test symbol hierarchy with children."""
        child = SymbolInfo(name="child", kind="method", start_line=5, end_line=10)
        parent = SymbolInfo(
            name="parent",
            kind="class",
            start_line=1,
            end_line=20,
            children=[child],
        )

        assert len(parent.children) == 1
        assert parent.children[0].name == "child"


# -----------------------------------------------------------------------------
# FileOutline Tests
# -----------------------------------------------------------------------------


class TestFileOutline:
    """Tests for the FileOutline class."""

    def test_file_outline_creation(self):
        """Test creating a FileOutline."""
        symbols = [
            SymbolInfo(name="Class1", kind="class", start_line=1, end_line=10),
            SymbolInfo(name="func1", kind="function", start_line=15, end_line=20),
        ]

        outline = FileOutline(
            language="python",
            symbols=symbols,
            success=True,
        )

        assert outline.language == "python"
        assert len(outline.symbols) == 2
        assert outline.success

    def test_outline_filtering(self):
        """Test outline property filters."""
        symbols = [
            SymbolInfo(name="MyClass", kind="class", start_line=1, end_line=10),
            SymbolInfo(name="method1", kind="method", start_line=5, end_line=8, parent="MyClass"),
            SymbolInfo(name="func1", kind="function", start_line=15, end_line=20),
            SymbolInfo(name="os", kind="import", start_line=1, end_line=1),
        ]

        outline = FileOutline(language="python", symbols=symbols, success=True)

        assert len(outline.classes) == 1
        assert outline.classes[0].name == "MyClass"

        assert len(outline.functions) == 2  # method + function
        assert len(outline.imports) == 1

        # Top-level symbols (no parent)
        assert len(outline.top_level_symbols) == 3

    def test_get_symbol_by_name(self):
        """Test finding symbol by name."""
        symbols = [
            SymbolInfo(name="Class1", kind="class", start_line=1, end_line=10),
            SymbolInfo(name="func1", kind="function", start_line=15, end_line=20),
        ]

        outline = FileOutline(language="python", symbols=symbols, success=True)

        found = outline.get_symbol_by_name("func1")
        assert found is not None
        assert found.name == "func1"

        not_found = outline.get_symbol_by_name("nonexistent")
        assert not_found is None

    def test_to_dict(self):
        """Test outline serialization."""
        symbol = SymbolInfo(name="test", kind="function", start_line=1, end_line=5)
        outline = FileOutline(
            language="python",
            symbols=[symbol],
            success=True,
            extraction_time_ms=0.5,
        )

        result = outline.to_dict()
        assert result["language"] == "python"
        assert result["success"] is True
        assert len(result["symbols"]) == 1


# -----------------------------------------------------------------------------
# CodeContext Tests
# -----------------------------------------------------------------------------


class TestCodeContext:
    """Tests for the CodeContext class."""

    def test_code_context_creation(self):
        """Test creating a CodeContext."""
        context = CodeContext(
            file_path="/test/file.py",
            language="python",
            num_lines=100,
            num_tokens=500,
        )

        assert context.file_path == "/test/file.py"
        assert context.language == "python"
        assert context.is_parsed is False  # No outline
        assert context.symbol_count == 0

    def test_code_context_with_outline(self):
        """Test CodeContext with outline."""
        outline = FileOutline(
            language="python",
            symbols=[
                SymbolInfo(name="func1", kind="function", start_line=1, end_line=5),
            ],
            success=True,
        )

        context = CodeContext(
            file_path="/test/file.py",
            outline=outline,
        )

        assert context.is_parsed is True
        assert context.symbol_count == 1

    def test_get_summary(self):
        """Test summary generation."""
        outline = FileOutline(
            language="python",
            symbols=[
                SymbolInfo(name="Class1", kind="class", start_line=1, end_line=10),
                SymbolInfo(name="func1", kind="function", start_line=15, end_line=20),
            ],
            success=True,
        )

        context = CodeContext(
            file_path="/test/file.py",
            language="python",
            num_lines=25,
            num_tokens=100,
            outline=outline,
        )

        summary = context.get_summary()
        assert "/test/file.py" in summary
        assert "python" in summary
        assert "Lines: 25" in summary
        assert "Symbols: 2" in summary

    def test_to_dict(self):
        """Test CodeContext serialization."""
        context = CodeContext(
            file_path="/test/file.py",
            language="python",
            num_lines=10,
        )

        result = context.to_dict()
        assert result["file_path"] == "/test/file.py"
        assert result["language"] == "python"


# -----------------------------------------------------------------------------
# CodeExplorer Tests
# -----------------------------------------------------------------------------


class TestCodeExplorer:
    """Tests for the CodeExplorer class."""

    def test_explorer_creation(self):
        """Test creating a CodeExplorer."""
        explorer = CodeExplorer(enable_cache=True)
        assert explorer.enable_cache is True
        assert explorer._parse_count == 0

    def test_detect_language(self, explorer):
        """Test language detection from file extension."""
        assert explorer._detect_language("test.py") == "python"
        assert explorer._detect_language("test.rs") == "rust"
        assert explorer._detect_language("test.js") == "javascript"
        assert explorer._detect_language("test.ts") == "typescript"
        assert explorer._detect_language("test.tsx") == "typescript"
        assert explorer._detect_language("test.ex") == "elixir"
        assert explorer._detect_language("test.unknown") is None

    def test_is_supported_file(self, explorer):
        """Test supported file detection."""
        # _is_supported_file simply checks if _detect_language returns a value
        assert explorer._is_supported_file("test.py") is True
        assert explorer._is_supported_file("test.rs") is True
        assert explorer._is_supported_file("test.txt") is False
        assert explorer._is_supported_file("test.unknown") is False

    def test_explore_file_not_found(self, explorer):
        """Test exploring a non-existent file."""
        context = explorer.explore_file("/nonexistent/file.py")
        assert context.has_errors is True
        assert context.error_message is not None

    def test_explore_file_success(self, explorer, sample_python_file):
        """Test successfully exploring a file."""
        context = explorer.explore_file(sample_python_file, include_content=False)

        assert context.file_path == str(Path(sample_python_file).resolve())
        assert context.language == "python"
        assert context.num_lines > 0

        # Outline may or may not be available depending on turbo_parse
        if context.outline:
            assert isinstance(context.outline, FileOutline)

    def test_explore_file_with_content(self, explorer, sample_python_file):
        """Test exploring a file with content included."""
        context = explorer.explore_file(sample_python_file, include_content=True)

        if context.content:
            assert "class MyClass" in context.content
            assert "def standalone_function" in context.content

    def test_cache_functionality(self, sample_python_file):
        """Test that caching works correctly."""
        explorer = CodeExplorer(enable_cache=True)

        # First call should parse
        ctx1 = explorer.explore_file(sample_python_file, include_content=False)

        # Second call should use cache
        ctx2 = explorer.explore_file(sample_python_file, include_content=False)

        # Should get same result
        assert ctx1.file_path == ctx2.file_path

        # Cache stats should show activity
        stats = explorer.get_cache_stats()
        assert stats["cache_size"] >= 1

    def test_invalidate_cache(self, sample_python_file):
        """Test cache invalidation."""
        # Create explorer with caching enabled
        explorer = CodeExplorer(enable_cache=True)

        # Explore a file to populate cache (use include_content=True for caching)
        context = explorer.explore_file(sample_python_file, include_content=True)
        cached_path = context.file_path  # Get the actual cached path

        # Check cache has entry (by resolved path)
        assert cached_path in explorer._cache

        # Invalidate specific file
        explorer.invalidate_cache(sample_python_file)

        # Cache should be cleared for this file
        assert cached_path not in explorer._cache

    def test_explore_directory(self, explorer, sample_directory):
        """Test exploring a directory."""
        contexts = explorer.explore_directory(
            sample_directory,
            pattern="*.py",
            recursive=True,
            max_files=50,
        )

        # Should find Python files
        assert len(contexts) >= 2

        # All should have python language
        for ctx in contexts:
            assert ctx.language == "python"

    def test_get_outline(self, explorer, sample_python_file):
        """Test getting file outline."""
        outline = explorer.get_outline(sample_python_file)

        assert isinstance(outline, FileOutline)
        assert outline.language == "python"

    def test_get_outline_with_depth(self, explorer, sample_python_file):
        """Test getting outline with depth limit."""
        outline = explorer.get_outline(sample_python_file, max_depth=1)

        assert isinstance(outline, FileOutline)

    def test_find_symbol_definitions(self, explorer, sample_directory):
        """Test finding symbol definitions across directory."""
        results = explorer.find_symbol_definitions(sample_directory, "main")

        # When turbo_parse is not available, symbols won't be extracted
        # When available, should find 'main' function
        if TURBO_PARSE_AVAILABLE:
            assert len(results) >= 1
            for file_path, symbol in results:
                assert symbol.name == "main"
        else:
            # Without turbo_parse, no symbols are found
            assert len(results) == 0


# -----------------------------------------------------------------------------
# Module Function Tests
# -----------------------------------------------------------------------------


class TestModuleFunctions:
    """Tests for module-level convenience functions."""

    def test_get_code_context_without_symbols(self, sample_python_file):
        """Test get_code_context without symbols."""
        context = get_code_context(
            sample_python_file,
            include_content=False,
            with_symbols=False,
        )

        # Check that path matches (handle /private/var vs /var on macOS)
        expected_path = str(Path(sample_python_file).resolve())
        actual_path = context.file_path
        assert Path(actual_path).resolve() == Path(expected_path).resolve()
        assert context.outline is None
        assert context.num_lines > 0

    def test_get_code_context_with_symbols(self, sample_python_file):
        """Test get_code_context with symbols."""
        context = get_code_context(
            sample_python_file,
            include_content=False,
            with_symbols=True,
        )

        assert context.file_path == str(Path(sample_python_file).resolve())
        # Outline may or may not be available depending on turbo_parse

    def test_get_file_outline(self, sample_python_file):
        """Test get_file_outline function."""
        outline = get_file_outline(sample_python_file)

        assert isinstance(outline, FileOutline)
        assert outline.language == "python"

    def test_explore_directory_function(self, sample_directory):
        """Test explore_directory function."""
        contexts = explore_directory(
            sample_directory,
            pattern="*.py",
            recursive=True,
        )

        assert isinstance(contexts, list)
        assert len(contexts) >= 2

    def test_format_outline(self):
        """Test format_outline function."""
        symbols = [
            SymbolInfo(name="MyClass", kind="class", start_line=1, end_line=10),
            SymbolInfo(name="func1", kind="function", start_line=15, end_line=20),
        ]
        outline = FileOutline(language="python", symbols=symbols, success=True)

        formatted = format_outline(outline)

        assert "MyClass" in formatted
        assert "func1" in formatted
        assert "L1" in formatted  # Line number

    def test_enhance_read_file_result(self, sample_python_file):
        """Test enhance_read_file_result function."""
        content = "def test(): pass"
        result = enhance_read_file_result(
            sample_python_file,
            content,
            num_tokens=10,
            with_symbols=False,
        )

        assert result["content"] == content
        assert result["num_tokens"] == 10
        assert "outline" not in result


# -----------------------------------------------------------------------------
# Integration Tests
# -----------------------------------------------------------------------------


@pytest.mark.skipif(not TURBO_PARSE_AVAILABLE, reason="turbo_parse not available")
class TestTurboParseIntegration:
    """Integration tests requiring turbo_parse."""

    def test_symbol_extraction_with_turbo_parse(self, sample_python_file):
        """Test that symbols are extracted when turbo_parse is available."""
        explorer = CodeExplorer(enable_cache=False)
        context = explorer.explore_file(sample_python_file, include_content=False)

        assert context.outline is not None
        assert context.outline.success is True
        assert len(context.outline.symbols) > 0

        # Check for expected symbols
        symbol_names = [s.name for s in context.outline.symbols]
        assert "MyClass" in symbol_names or "standalone_function" in symbol_names

    def test_hierarchy_building(self, sample_python_file):
        """Test that symbol hierarchy is built correctly."""
        explorer = CodeExplorer(enable_cache=False)
        context = explorer.explore_file(sample_python_file, include_content=False)

        if context.outline and context.outline.symbols:
            # Check that any class has its methods as children
            for symbol in context.outline.symbols:
                if symbol.kind == "class" and symbol.children:
                    # Verify children are contained in parent
                    for child in symbol.children:
                        assert child.start_line >= symbol.start_line
                        assert child.end_line <= symbol.end_line


# -----------------------------------------------------------------------------
# Error Handling Tests
# -----------------------------------------------------------------------------


class TestErrorHandling:
    """Tests for error handling."""

    def test_explore_unsupported_file(self, explorer, tmp_path):
        """Test exploring a file with unsupported extension."""
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("Hello")

        context = explorer.explore_file(str(txt_file))
        assert context.language is None or context.outline is None

    def test_explore_binary_file(self, explorer, tmp_path):
        """Test attempting to explore a binary file."""
        bin_file = tmp_path / "test.bin"
        bin_file.write_bytes(b"\x00\x01\x02\x03")

        context = explorer.explore_file(str(bin_file))

        # Binary files will have content read but no language detected
        assert context.language is None
        assert context.outline is None or context.outline.language == "unknown"

    def test_explore_directory_not_found(self, explorer):
        """Test exploring a non-existent directory."""
        contexts = explorer.explore_directory("/nonexistent/directory")
        assert contexts == []
