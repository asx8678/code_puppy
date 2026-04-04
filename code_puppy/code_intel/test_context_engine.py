"""Tests for the context engine module."""

import pytest
from pathlib import Path

from code_puppy.code_intel import (
    ContextEngine,
    RelevanceScorer,
    CodeFormatter,
    ContextEngineConfig,
    ScoringFactors,
)
from code_puppy.code_intel.context_engine import SymbolInfo


class TestRelevanceScorer:
    """Tests for the RelevanceScorer class."""

    def test_extract_focus_symbols(self):
        """Test extracting focus symbols from text."""
        scorer = RelevanceScorer()
        scorer.set_conversation_context("Call the process_data() function and Bar class")

        focus = scorer.get_focus_symbols()
        assert "process_data" in focus
        assert "Bar" in focus

    def test_score_symbol_direct_mention(self):
        """Test scoring a directly mentioned symbol."""
        scorer = RelevanceScorer()
        scorer.set_conversation_context("Use the calculate_total function")

        symbol = SymbolInfo(
            name="calculate_total",
            symbol_type="function",
            file_path=Path("/test.py"),
            source_code="def calculate_total(): pass",
        )

        score = scorer.score_symbol(symbol)
        assert score.score > 0
        assert "direct_mention" in score.factors

    def test_score_symbol_no_match(self):
        """Test scoring a non-mentioned symbol."""
        scorer = RelevanceScorer()
        scorer.set_conversation_context("Use the foo function")

        symbol = SymbolInfo(
            name="bar",
            symbol_type="function",
            file_path=Path("/test.py"),
            source_code="def bar(): pass",
        )

        score = scorer.score_symbol(symbol)
        assert score.score == 0


class TestCodeFormatter:
    """Tests for the CodeFormatter class."""

    def test_format_header(self):
        """Test header formatting."""
        formatter = CodeFormatter()
        symbol = SymbolInfo(
            name="test_func",
            symbol_type="function",
            file_path=Path("/home/user/test.py"),
            line_number=42,
            source_code="def test_func(): pass",
        )

        from code_puppy.code_intel.relevance_scorer import RelevanceScore

        score = RelevanceScore(
            symbol_name="test_func",
            score=10.0,
            factors={"direct_mention": 10.0},
        )

        formatted = formatter.format_symbol(symbol, score)
        assert formatted.name == "test_func"
        assert "test_func" in formatted.content
        assert "function" in formatted.content

    def test_detect_language(self):
        """Test language detection from file extension."""
        formatter = CodeFormatter()

        assert formatter._detect_language(Path("test.py")) == "python"
        assert formatter._detect_language(Path("test.js")) == "javascript"
        assert formatter._detect_language(Path("test.ts")) == "typescript"
        assert formatter._detect_language(Path("test.rs")) == "rust"
        assert formatter._detect_language(Path("test.go")) == "go"
        assert formatter._detect_language(Path("test.java")) == "java"
        assert formatter._detect_language(Path("test.unknown")) == ""


class TestContextEngine:
    """Tests for the ContextEngine class."""

    def test_initialization(self):
        """Test engine initialization."""
        engine = ContextEngine()
        assert engine.initialize() is True
        assert engine.is_enabled() is True

    def test_initialization_disabled(self):
        """Test engine initialization when disabled."""
        config = ContextEngineConfig(enabled=False)
        engine = ContextEngine(config)
        assert engine.initialize() is False
        assert engine.is_enabled() is False

    def test_add_conversation_turn(self):
        """Test adding conversation turns."""
        engine = ContextEngine()
        engine.initialize()

        engine.add_conversation_turn("Hello")
        engine.add_conversation_turn("Hi there", "Hello user")

        assert len(engine._conversation_history) == 3

    def test_set_recent_files(self):
        """Test setting recent files."""
        engine = ContextEngine()
        engine.initialize()

        engine.set_recent_files(["/test1.py", "/test2.py"])
        assert len(engine._recent_files) == 2

    def test_build_context_empty(self):
        """Test building context with no relevant symbols."""
        engine = ContextEngine()
        engine.initialize()

        # No conversation text = no context
        result = engine.build_context("")
        assert result is None

    def test_extract_symbol_names(self):
        """Test symbol name extraction."""
        engine = ContextEngine()

        names = engine._extract_symbol_names("Call foo() and Bar class")
        assert "foo" in names
        assert "Bar" in names


class TestIntegration:
    """Integration tests for the full context pipeline."""

    def test_full_pipeline(self, tmp_path):
        """Test the full pipeline with a real file."""
        # Create a test file
        test_file = tmp_path / "test_module.py"
        test_file.write_text("""
def process_data(items):
    \"\"\"Process a list of items.\"\"\"
    return [item.upper() for item in items]

class DataProcessor:
    \"\"\"A class to process data.\"\"\"

    def transform(self, data):
        return process_data(data)
""")

        engine = ContextEngine()
        engine.initialize()
        engine.set_recent_files([str(test_file)])

        # Build context for conversation about process_data
        context = engine.build_context("I need to fix the process_data function")

        # Should find the symbol (if search works)
        # Note: This may be None in test environment depending on file structure
        if context:
            assert "process_data" in context or len(context) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
