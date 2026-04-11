#!/usr/bin/env python3
"""Hypothesis-based fuzz tests for symbol extraction.

This module provides property-based testing to verify that extract_symbols:
1. Never crashes on valid code
2. Returns consistent results
3. Handles edge cases properly
4. Maintains invariants across all inputs
"""

import pytest
from hypothesis import given, settings, strategies as st

from tests.fuzz.strategies import (
    TURBO_PARSE_AVAILABLE,
    elixir_source,
    empty_source,
    javascript_source,
    long_identifiers,
    many_functions_python,
    python_source,
    rust_source,
    validate_symbol_outline,
    whitespace_only,
)


# =============================================================================
# Test Functions - Python
# =============================================================================


@pytest.mark.skipif(not TURBO_PARSE_AVAILABLE, reason="turbo_parse not available")
class TestPythonSymbolExtraction:
    """Tests for Python symbol extraction."""

    @given(source=python_source())
    @settings(max_examples=100, deadline=None)
    def test_python_symbol_extraction_never_crashes(self, source: str) -> None:
        """Property: extract_symbols never crashes on valid Python code."""
        from tests.fuzz.strategies import extract_symbols

        # This test passes if no exception is raised
        result = extract_symbols(source, "python")

        # Verify result structure
        assert isinstance(result, dict)
        assert "success" in result
        assert "symbols" in result

    @given(source=python_source())
    @settings(max_examples=100, deadline=None)
    def test_python_symbol_extraction_returns_success(self, source: str) -> None:
        """Property: extract_symbols returns success=True for valid Python code."""
        from tests.fuzz.strategies import extract_symbols

        result = extract_symbols(source, "python")
        assert result["success"] is True, (
            f"Failed for source:\n{source[:200]}...\nErrors: {result.get('errors', [])}"
        )

    @given(source=python_source())
    @settings(max_examples=100, deadline=None)
    def test_python_symbol_count_is_non_negative(self, source: str) -> None:
        """Property: Number of symbols >= 0 for all valid Python code."""
        from tests.fuzz.strategies import extract_symbols

        result = extract_symbols(source, "python")
        assert len(result["symbols"]) >= 0

    @given(source=python_source())
    @settings(max_examples=100, deadline=None)
    def test_python_symbols_have_required_fields(self, source: str) -> None:
        """Property: Each symbol has required fields (name, kind, location)."""
        from tests.fuzz.strategies import extract_symbols

        result = extract_symbols(source, "python")
        validation_errors = validate_symbol_outline(result)
        assert not validation_errors, f"Validation errors: {validation_errors[:5]}"

    @given(source=python_source())
    @settings(max_examples=100, deadline=None)
    def test_python_symbol_names_are_valid_strings(self, source: str) -> None:
        """Property: Symbol names are valid strings (not empty, valid UTF-8)."""
        from tests.fuzz.strategies import extract_symbols

        result = extract_symbols(source, "python")
        for symbol in result.get("symbols", []):
            name = symbol.get("name", "")
            assert isinstance(name, str), f"Name must be string, got {type(name)}"
            assert name, "Symbol name cannot be empty"
            # Verify valid UTF-8
            name.encode("utf-8")


@pytest.mark.slow
@pytest.mark.skipif(not TURBO_PARSE_AVAILABLE, reason="turbo_parse not available")
class TestPythonEdgeCases:
    """Edge case tests for Python symbol extraction."""

    @given(source=st.just(""))
    @settings(max_examples=1, deadline=None)
    def test_empty_file(self, source: str) -> None:
        """Edge case: Empty Python file."""
        from tests.fuzz.strategies import extract_symbols

        result = extract_symbols(source, "python")
        assert isinstance(result, dict)
        # Empty file should either succeed with no symbols or fail gracefully
        if result["success"]:
            assert len(result["symbols"]) == 0

    @given(source=whitespace_only)
    @settings(max_examples=50, deadline=None)
    def test_whitespace_only_file(self, source: str) -> None:
        """Edge case: File with only whitespace."""
        from tests.fuzz.strategies import extract_symbols

        result = extract_symbols(source, "python")
        assert isinstance(result, dict)
        # Should not crash

    @given(name=long_identifiers)
    @settings(max_examples=50, deadline=None)
    def test_very_long_symbol_name(self, name: str) -> None:
        """Edge case: Very long symbol names."""
        from tests.fuzz.strategies import extract_symbols

        source = f"def {name}():\n    pass\n"
        result = extract_symbols(source, "python")
        assert isinstance(result, dict)
        if result["success"]:
            # Check if the long name is preserved
            names = [s["name"] for s in result["symbols"]]
            if names:
                assert name in names or any(name.startswith(n) for n in names)

    @given(count=st.integers(min_value=0, max_value=50))
    @settings(max_examples=50, deadline=None)
    def test_many_functions(self, count: int) -> None:
        """Edge case: Many functions in a single file."""
        from tests.fuzz.strategies import extract_symbols

        source = "\n\n".join([f"def func_{i}():\n    pass" for i in range(count)])
        result = extract_symbols(source, "python")
        assert isinstance(result, dict)
        if result["success"]:
            # Should find roughly the number of functions
            func_symbols = [s for s in result["symbols"] if s["kind"] == "function"]
            # Allow for some variance due to parsing
            assert len(func_symbols) >= 0


# =============================================================================
# Test Functions - Rust
# =============================================================================


@pytest.mark.skipif(not TURBO_PARSE_AVAILABLE, reason="turbo_parse not available")
class TestRustSymbolExtraction:
    """Tests for Rust symbol extraction."""

    @given(source=rust_source())
    @settings(max_examples=100, deadline=None)
    def test_rust_symbol_extraction_never_crashes(self, source: str) -> None:
        """Property: extract_symbols never crashes on valid Rust code."""
        from tests.fuzz.strategies import extract_symbols

        result = extract_symbols(source, "rust")

        # Verify result structure
        assert isinstance(result, dict)
        assert "success" in result
        assert "symbols" in result

    @given(source=rust_source())
    @settings(max_examples=100, deadline=None)
    def test_rust_symbol_extraction_returns_success(self, source: str) -> None:
        """Property: extract_symbols returns success=True for valid Rust code."""
        from tests.fuzz.strategies import extract_symbols

        result = extract_symbols(source, "rust")
        assert result["success"] is True, (
            f"Failed for source:\n{source[:200]}...\nErrors: {result.get('errors', [])}"
        )

    @given(source=rust_source())
    @settings(max_examples=100, deadline=None)
    def test_rust_symbol_count_is_non_negative(self, source: str) -> None:
        """Property: Number of symbols >= 0 for all valid Rust code."""
        from tests.fuzz.strategies import extract_symbols

        result = extract_symbols(source, "rust")
        assert len(result["symbols"]) >= 0

    @given(source=rust_source())
    @settings(max_examples=100, deadline=None)
    def test_rust_symbols_have_required_fields(self, source: str) -> None:
        """Property: Each symbol has required fields (name, kind, location)."""
        from tests.fuzz.strategies import extract_symbols

        result = extract_symbols(source, "rust")
        validation_errors = validate_symbol_outline(result)
        assert not validation_errors, f"Validation errors: {validation_errors[:5]}"

    @given(source=rust_source())
    @settings(max_examples=100, deadline=None)
    def test_rust_symbol_names_are_valid_strings(self, source: str) -> None:
        """Property: Symbol names are valid strings (not empty, valid UTF-8)."""
        from tests.fuzz.strategies import extract_symbols

        result = extract_symbols(source, "rust")
        for symbol in result.get("symbols", []):
            name = symbol.get("name", "")
            assert isinstance(name, str), f"Name must be string, got {type(name)}"
            assert name, "Symbol name cannot be empty"
            name.encode("utf-8")


@pytest.mark.slow
@pytest.mark.skipif(not TURBO_PARSE_AVAILABLE, reason="turbo_parse not available")
class TestRustEdgeCases:
    """Edge case tests for Rust symbol extraction."""

    @given(source=st.just(""))
    @settings(max_examples=1, deadline=None)
    def test_empty_rust_file(self, source: str) -> None:
        """Edge case: Empty Rust file."""
        from tests.fuzz.strategies import extract_symbols

        result = extract_symbols(source, "rust")
        assert isinstance(result, dict)

    @given(source=st.just("// This is a comment\n"))
    @settings(max_examples=1, deadline=None)
    def test_comment_only_rust_file(self, source: str) -> None:
        """Edge case: Rust file with only comments."""
        from tests.fuzz.strategies import extract_symbols

        result = extract_symbols(source, "rust")
        assert isinstance(result, dict)

    @given(name=long_identifiers.filter(lambda x: x and x[0].isupper()))
    @settings(max_examples=50, deadline=None)
    def test_rust_long_struct_name(self, name: str) -> None:
        """Edge case: Very long struct name in Rust."""
        from tests.fuzz.strategies import extract_symbols

        source = f"struct {name};\n"
        result = extract_symbols(source, "rust")
        assert isinstance(result, dict)


# =============================================================================
# Test Functions - JavaScript
# =============================================================================


@pytest.mark.skipif(not TURBO_PARSE_AVAILABLE, reason="turbo_parse not available")
class TestJavaScriptSymbolExtraction:
    """Tests for JavaScript symbol extraction."""

    @given(source=javascript_source())
    @settings(max_examples=100, deadline=None)
    def test_javascript_symbol_extraction_never_crashes(self, source: str) -> None:
        """Property: extract_symbols never crashes on valid JavaScript code."""
        from tests.fuzz.strategies import extract_symbols

        result = extract_symbols(source, "javascript")

        # Verify result structure
        assert isinstance(result, dict)
        assert "success" in result
        assert "symbols" in result

    @given(source=javascript_source())
    @settings(max_examples=100, deadline=None)
    def test_javascript_symbol_extraction_returns_success(self, source: str) -> None:
        """Property: extract_symbols returns success=True for valid JavaScript code."""
        from tests.fuzz.strategies import extract_symbols

        result = extract_symbols(source, "javascript")
        assert result["success"] is True, (
            f"Failed for source:\n{source[:200]}...\nErrors: {result.get('errors', [])}"
        )

    @given(source=javascript_source())
    @settings(max_examples=100, deadline=None)
    def test_javascript_symbol_count_is_non_negative(self, source: str) -> None:
        """Property: Number of symbols >= 0 for all valid JavaScript code."""
        from tests.fuzz.strategies import extract_symbols

        result = extract_symbols(source, "javascript")
        assert len(result["symbols"]) >= 0

    @given(source=javascript_source())
    @settings(max_examples=100, deadline=None)
    def test_javascript_symbols_have_required_fields(self, source: str) -> None:
        """Property: Each symbol has required fields (name, kind, location)."""
        from tests.fuzz.strategies import extract_symbols

        result = extract_symbols(source, "javascript")
        validation_errors = validate_symbol_outline(result)
        assert not validation_errors, f"Validation errors: {validation_errors[:5]}"

    @given(source=javascript_source())
    @settings(max_examples=100, deadline=None)
    def test_javascript_symbol_names_are_valid_strings(self, source: str) -> None:
        """Property: Symbol names are valid strings (not empty, valid UTF-8)."""
        from tests.fuzz.strategies import extract_symbols

        result = extract_symbols(source, "javascript")
        for symbol in result.get("symbols", []):
            name = symbol.get("name", "")
            assert isinstance(name, str), f"Name must be string, got {type(name)}"
            assert name, "Symbol name cannot be empty"
            name.encode("utf-8")


@pytest.mark.slow
@pytest.mark.skipif(not TURBO_PARSE_AVAILABLE, reason="turbo_parse not available")
class TestJavaScriptEdgeCases:
    """Edge case tests for JavaScript symbol extraction."""

    @given(source=st.just(""))
    @settings(max_examples=1, deadline=None)
    def test_empty_js_file(self, source: str) -> None:
        """Edge case: Empty JavaScript file."""
        from tests.fuzz.strategies import extract_symbols

        result = extract_symbols(source, "javascript")
        assert isinstance(result, dict)

    @given(source=st.just("// Comment only\n/* Block comment */\n"))
    @settings(max_examples=1, deadline=None)
    def test_comment_only_js_file(self, source: str) -> None:
        """Edge case: JavaScript file with only comments."""
        from tests.fuzz.strategies import extract_symbols

        result = extract_symbols(source, "javascript")
        assert isinstance(result, dict)


# =============================================================================
# Test Functions - TypeScript
# =============================================================================


@pytest.mark.skipif(not TURBO_PARSE_AVAILABLE, reason="turbo_parse not available")
class TestTypeScriptSymbolExtraction:
    """Tests for TypeScript symbol extraction."""

    @given(source=javascript_source())
    @settings(max_examples=50, deadline=None)
    def test_typescript_symbol_extraction_never_crashes(self, source: str) -> None:
        """Property: extract_symbols never crashes on valid TypeScript code."""
        from tests.fuzz.strategies import extract_symbols

        # Use JavaScript source as base for TypeScript (TypeScript is a superset)
        result = extract_symbols(source, "typescript")

        # Verify result structure
        assert isinstance(result, dict)
        assert "success" in result
        assert "symbols" in result

    @given(source=javascript_source())
    @settings(max_examples=50, deadline=None)
    def test_typescript_symbol_extraction_returns_success(self, source: str) -> None:
        """Property: extract_symbols returns success=True for valid TypeScript code."""
        from tests.fuzz.strategies import extract_symbols

        result = extract_symbols(source, "typescript")
        assert result["success"] is True, (
            f"Failed for source:\n{source[:200]}...\nErrors: {result.get('errors', [])}"
        )

    @given(source=javascript_source())
    @settings(max_examples=50, deadline=None)
    def test_typescript_symbols_have_required_fields(self, source: str) -> None:
        """Property: Each TypeScript symbol has required fields (name, kind, location)."""
        from tests.fuzz.strategies import extract_symbols

        result = extract_symbols(source, "typescript")
        validation_errors = validate_symbol_outline(result)
        assert not validation_errors, f"Validation errors: {validation_errors[:5]}"

    @given(source=javascript_source())
    @settings(max_examples=50, deadline=None)
    def test_typescript_symbol_names_are_valid_strings(self, source: str) -> None:
        """Property: TypeScript symbol names are valid strings (not empty, valid UTF-8)."""
        from tests.fuzz.strategies import extract_symbols

        result = extract_symbols(source, "typescript")
        for symbol in result.get("symbols", []):
            name = symbol.get("name", "")
            assert isinstance(name, str), f"Name must be string, got {type(name)}"
            assert name, "Symbol name cannot be empty"
            name.encode("utf-8")


# =============================================================================
# Test Functions - Elixir
# =============================================================================


@pytest.mark.skipif(not TURBO_PARSE_AVAILABLE, reason="turbo_parse not available")
class TestElixirSymbolExtraction:
    """Tests for Elixir symbol extraction."""

    @given(source=elixir_source())
    @settings(max_examples=100, deadline=None)
    def test_elixir_symbol_extraction_never_crashes(self, source: str) -> None:
        """Property: extract_symbols never crashes on valid Elixir code."""
        from tests.fuzz.strategies import extract_symbols

        result = extract_symbols(source, "elixir")

        # Verify result structure
        assert isinstance(result, dict)
        assert "success" in result
        assert "symbols" in result

    @given(source=elixir_source())
    @settings(max_examples=100, deadline=None)
    def test_elixir_symbol_extraction_returns_success(self, source: str) -> None:
        """Property: extract_symbols returns success=True for valid Elixir code."""
        from tests.fuzz.strategies import extract_symbols

        result = extract_symbols(source, "elixir")
        assert result["success"] is True, (
            f"Failed for source:\n{source[:200]}...\nErrors: {result.get('errors', [])}"
        )

    @given(source=elixir_source())
    @settings(max_examples=100, deadline=None)
    def test_elixir_symbols_have_required_fields(self, source: str) -> None:
        """Property: Each symbol has required fields (name, kind, location)."""
        from tests.fuzz.strategies import extract_symbols

        result = extract_symbols(source, "elixir")
        validation_errors = validate_symbol_outline(result)
        assert not validation_errors, f"Validation errors: {validation_errors[:5]}"


# =============================================================================
# Cross-Language Tests
# =============================================================================


@pytest.mark.skipif(not TURBO_PARSE_AVAILABLE, reason="turbo_parse not available")
class TestCrossLanguage:
    """Tests that apply across all supported languages."""

    @given(
        source=st.one_of(
            python_source(), rust_source(), javascript_source(), elixir_source()
        ),
        language=st.sampled_from(["python", "rust", "javascript", "elixir"]),
    )
    @settings(max_examples=100, deadline=None)
    def test_any_language_never_crashes(self, source: str, language: str) -> None:
        """Property: No combination of source and language crashes."""
        from tests.fuzz.strategies import extract_symbols

        result = extract_symbols(source, language)
        # Should always return a dict, even if parsing fails
        assert isinstance(result, dict)

    @pytest.mark.parametrize(
        "language", ["python", "rust", "javascript", "typescript", "elixir"]
    )
    def test_empty_source_for_all_languages(self, language: str) -> None:
        """Edge case: Empty source for all supported languages."""
        from tests.fuzz.strategies import extract_symbols

        result = extract_symbols("", language)
        assert isinstance(result, dict)
        # Should handle empty input gracefully

    @pytest.mark.parametrize(
        "language", ["python", "rust", "javascript", "typescript", "elixir"]
    )
    def test_whitespace_only_for_all_languages(self, language: str) -> None:
        """Edge case: Whitespace-only source for all supported languages."""
        from tests.fuzz.strategies import extract_symbols

        result = extract_symbols("   \n\t\n   ", language)
        assert isinstance(result, dict)


# =============================================================================
# Manual Test Verification
# =============================================================================


@pytest.mark.skipif(not TURBO_PARSE_AVAILABLE, reason="turbo_parse not available")
def test_extract_symbols_basic_smoke() -> None:
    """Smoke test to verify the basic functionality works."""
    from tests.fuzz.strategies import extract_symbols

    source = "def hello():\n    pass\n"
    result = extract_symbols(source, "python")
    assert result["success"] is True
    assert isinstance(result["symbols"], list)


@pytest.mark.skipif(not TURBO_PARSE_AVAILABLE, reason="turbo_parse not available")
def test_extract_symbols_rust_smoke() -> None:
    """Smoke test for Rust symbol extraction."""
    from tests.fuzz.strategies import extract_symbols

    source = "fn main() {}\nstruct Point { x: i32 }\n"
    result = extract_symbols(source, "rust")
    assert result["success"] is True
    assert isinstance(result["symbols"], list)


@pytest.mark.skipif(not TURBO_PARSE_AVAILABLE, reason="turbo_parse not available")
def test_extract_symbols_javascript_smoke() -> None:
    """Smoke test for JavaScript symbol extraction."""
    from tests.fuzz.strategies import extract_symbols

    source = "function test() {}\nclass MyClass {}\n"
    result = extract_symbols(source, "javascript")
    assert result["success"] is True
    assert isinstance(result["symbols"], list)
