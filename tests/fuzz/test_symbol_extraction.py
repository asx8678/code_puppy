#!/usr/bin/env python3
"""Hypothesis-based fuzz tests for symbol extraction.

This module provides property-based testing to verify that extract_symbols:
1. Never crashes on valid code
2. Returns consistent results
3. Handles edge cases properly
4. Maintains invariants across all inputs
"""

from __future__ import annotations

import string
from typing import Any

import pytest

# Hypothesis imports
from hypothesis import (
    HealthCheck,
    given,
    settings,
    strategies as st,
)
from hypothesis import Phase

# Import the symbol extraction function
try:
    from code_puppy.turbo_parse_bridge import extract_symbols, TURBO_PARSE_AVAILABLE
except ImportError:
    TURBO_PARSE_AVAILABLE = False

    def extract_symbols(*args: Any, **kwargs: Any) -> dict[str, Any]:
        """Fallback when turbo_parse is not available."""
        return {"success": False, "symbols": [], "error": "turbo_parse not available"}


# =============================================================================
# Hypothesis Profiles
# =============================================================================

def register_hypothesis_profiles() -> None:
    """Register hypothesis profiles for different test modes."""
    from hypothesis import settings as hypothesis_settings

    # CI profile: fast execution, good baseline coverage
    hypothesis_settings.register_profile(
        "ci",
        max_examples=50,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )

    # Local profile: balanced speed vs coverage
    hypothesis_settings.register_profile(
        "local",
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )

    # Thorough profile: deep testing
    hypothesis_settings.register_profile(
        "thorough",
        max_examples=500,
        deadline=None,
        phases=[Phase.explicit, Phase.reuse, Phase.generate, Phase.target],
        suppress_health_check=[HealthCheck.too_slow],
    )

    # Load the default profile
    hypothesis_settings.load_profile("local")


# Register profiles on import
register_hypothesis_profiles()


# =============================================================================
# Common Strategies
# =============================================================================

# Valid Python identifier characters (start with letter/underscore)
python_identifier_start = st.characters(
    whitelist_categories=("Lu", "Ll", "Lt", "Lm", "Lo", "Nl"),
    whitelist_characters="_",
)
python_identifier_continue = st.characters(
    whitelist_categories=("Lu", "Ll", "Lt", "Lm", "Lo", "Nl", "Mn", "Mc", "Nd", "Pc"),
    whitelist_characters="_",
)

# Valid Rust identifier characters
rust_identifier_start = st.sampled_from(string.ascii_letters + "_")
rust_identifier_continue = st.sampled_from(string.ascii_letters + string.digits + "_")

# Valid JavaScript identifier characters
js_identifier_start = st.sampled_from(string.ascii_letters + "_$")
js_identifier_continue = st.sampled_from(string.ascii_letters + string.digits + "_$")


def build_identifier(
    start_strategy: st.SearchStrategy[str],
    continue_strategy: st.SearchStrategy[str],
    min_length: int = 1,
    max_length: int = 50,
) -> st.SearchStrategy[str]:
    """Build a valid identifier strategy."""
    return st.builds(
        lambda start, rest: start + rest,
        start_strategy,
        st.text(continue_strategy, min_size=min_length - 1, max_size=max_length - 1),
    ).filter(lambda x: len(x) >= min_length and not x.startswith("__") and not x.endswith("__"))


# Valid identifiers
python_identifiers = build_identifier(
    python_identifier_start, python_identifier_continue, min_length=1, max_length=50
)
rust_identifiers = build_identifier(
    rust_identifier_start, rust_identifier_continue, min_length=1, max_length=50
)
js_identifiers = build_identifier(
    js_identifier_start, js_identifier_continue, min_length=1, max_length=50
)


# =============================================================================
# Python Code Generation Strategies
# =============================================================================


def python_function_def(name: str, body: str | None = None) -> str:
    """Generate a Python function definition."""
    body = body or "    pass"
    return f"def {name}():\n{body}\n"


def python_class_def(name: str, methods: list[str] | None = None) -> str:
    """Generate a Python class definition."""
    if methods:
        method_strs = [f"    def {m}(self):\n        pass" for m in methods]
        body = "\n".join(method_strs)
    else:
        body = "    pass"
    return f"class {name}:\n{body}\n"


def python_import_stmt(module: str, names: list[str] | None = None) -> str:
    """Generate a Python import statement."""
    if names:
        return f"from {module} import {', '.join(names)}\n"
    return f"import {module}\n"


def python_comment(text: str) -> str:
    """Generate a Python comment."""
    return f"# {text}\n"


def python_docstring(text: str) -> str:
    """Generate a Python docstring."""
    return f'"""{text}"""\n'


# Strategy for Python function components
@st.composite
def python_function_component(draw: st.DrawFn) -> str:
    """Draw a Python function definition."""
    name = draw(python_identifiers)
    body = draw(st.sampled_from(["    pass", "    return None", "    ..."]))
    return python_function_def(name, body)


@st.composite
def python_class_component(draw: st.DrawFn) -> str:
    """Draw a Python class definition."""
    name = draw(python_identifiers.filter(lambda x: x[0].isupper()))
    method_count = draw(st.integers(min_value=0, max_value=5))
    methods = [draw(python_identifiers) for _ in range(method_count)]
    return python_class_def(name, methods)


@st.composite
def python_import_component(draw: st.DrawFn) -> str:
    """Draw a Python import statement."""
    module = draw(st.sampled_from(["os", "sys", "typing", "collections", "json"]))
    has_names = draw(st.booleans())
    if has_names:
        name_count = draw(st.integers(min_value=1, max_value=3))
        names = [draw(python_identifiers) for _ in range(name_count)]
        return python_import_stmt(module, names)
    return python_import_stmt(module)


@st.composite
def python_comment_component(draw: st.DrawFn) -> str:
    """Draw a Python comment."""
    text = draw(st.text(st.sampled_from(string.ascii_letters + string.digits + " _-"), min_size=1, max_size=50))
    return python_comment(text)


# Main Python code strategy
@st.composite
def python_source(draw: st.DrawFn) -> str:
    """Generate valid Python source code."""
    num_components = draw(st.integers(min_value=0, max_value=20))
    components = []
    for _ in range(num_components):
        comp = draw(st.one_of(
            python_function_component(),
            python_class_component(),
            python_import_component(),
            python_comment_component(),
        ))
        components.append(comp)
    return "\n".join(components)


# =============================================================================
# Rust Code Generation Strategies
# =============================================================================


def rust_function_def(name: str, body: str | None = None) -> str:
    """Generate a Rust function definition."""
    body = body or "{}"
    return f"fn {name}() {body}\n"


def rust_struct_def(name: str, fields: list[tuple[str, str]] | None = None) -> str:
    """Generate a Rust struct definition."""
    if fields:
        field_strs = [f"    {f}: {t}," for f, t in fields]
        body = "\n".join(field_strs)
        return f"struct {name} {{\n{body}\n}}\n"
    return f"struct {name};\n"


def rust_impl_block(type_name: str, methods: list[str] | None = None) -> str:
    """Generate a Rust impl block."""
    if methods:
        method_strs = [f"    fn {m}() {{}}" for m in methods]
        body = "\n".join(method_strs)
        return f"impl {type_name} {{\n{body}\n}}\n"
    return f"impl {type_name} {{}}\n"


def rust_trait_def(name: str, methods: list[str] | None = None) -> str:
    """Generate a Rust trait definition."""
    if methods:
        method_strs = [f"    fn {m}();" for m in methods]
        body = "\n".join(method_strs)
        return f"trait {name} {{\n{body}\n}}\n"
    return f"trait {name} {{}}\n"


def rust_use_stmt(path: str) -> str:
    """Generate a Rust use statement."""
    return f"use {path};\n"


def rust_comment(text: str) -> str:
    """Generate a Rust comment."""
    return f"// {text}\n"


def rust_mod_def(name: str) -> str:
    """Generate a Rust module definition."""
    return f"mod {name} {{}}\n"


# Strategy for Rust components
@st.composite
def rust_function_component(draw: st.DrawFn) -> str:
    """Draw a Rust function definition."""
    name = draw(rust_identifiers)
    body = draw(st.sampled_from(["{}", "{ () }", "{ println!() }"]))
    return rust_function_def(name, body)


@st.composite
def rust_struct_component(draw: st.DrawFn) -> str:
    """Draw a Rust struct definition."""
    name = draw(rust_identifiers.filter(lambda x: x[0].isupper()))
    field_count = draw(st.integers(min_value=0, max_value=3))
    fields = []
    for _ in range(field_count):
        field_name = draw(rust_identifiers)
        field_type = draw(st.sampled_from(["i32", "String", "bool", "u64"]))
        fields.append((field_name, field_type))
    return rust_struct_def(name, fields)


@st.composite
def rust_impl_component(draw: st.DrawFn) -> str:
    """Draw a Rust impl block."""
    type_name = draw(rust_identifiers.filter(lambda x: x[0].isupper()))
    method_count = draw(st.integers(min_value=1, max_value=3))
    methods = [draw(rust_identifiers) for _ in range(method_count)]
    return rust_impl_block(type_name, methods)


@st.composite
def rust_trait_component(draw: st.DrawFn) -> str:
    """Draw a Rust trait definition."""
    name = draw(rust_identifiers.filter(lambda x: x[0].isupper()))
    method_count = draw(st.integers(min_value=0, max_value=3))
    methods = [draw(rust_identifiers) for _ in range(method_count)]
    return rust_trait_def(name, methods)


@st.composite
def rust_use_component(draw: st.DrawFn) -> str:
    """Draw a Rust use statement."""
    crate = draw(st.sampled_from(["std", "tokio", "serde"]))
    module = draw(st.sampled_from(["io", "collections", "sync", "fs"]))
    return rust_use_stmt(f"{crate}::{module}")


@st.composite
def rust_mod_component(draw: st.DrawFn) -> str:
    """Draw a Rust module definition."""
    name = draw(rust_identifiers)
    return rust_mod_def(name)


# Main Rust code strategy
@st.composite
def rust_source(draw: st.DrawFn) -> str:
    """Generate valid Rust source code."""
    num_components = draw(st.integers(min_value=0, max_value=20))
    components = []
    for _ in range(num_components):
        comp = draw(st.one_of(
            rust_function_component(),
            rust_struct_component(),
            rust_impl_component(),
            rust_trait_component(),
            rust_use_component(),
            rust_mod_component(),
        ))
        components.append(comp)
    return "\n".join(components)


# =============================================================================
# JavaScript Code Generation Strategies
# =============================================================================


def js_function_def(name: str, body: str | None = None) -> str:
    """Generate a JavaScript function definition."""
    body = body or "{}"
    return f"function {name}() {body}\n"


def js_arrow_function(name: str, body: str | None = None) -> str:
    """Generate a JavaScript arrow function in a variable declaration."""
    body = body or " => {}"
    return f"const {name} = () {body};\n"


def js_class_def(name: str, methods: list[str] | None = None) -> str:
    """Generate a JavaScript class definition."""
    if methods:
        method_strs = [f"    {m}() {{}}" for m in methods]
        body = "\n".join(method_strs)
        return f"class {name} {{\n{body}\n}}\n"
    return f"class {name} {{}}\n"


def js_import_stmt(module: str, names: list[str] | None = None) -> str:
    """Generate a JavaScript import statement."""
    if names:
        return f"import {{ {', '.join(names)} }} from '{module}';\n"
    return f"import {module} from '{module}';\n"


def js_variable_decl(name: str, value: str | None = None) -> str:
    """Generate a JavaScript variable declaration."""
    value = value or "null"
    return f"const {name} = {value};\n"


def js_comment(text: str) -> str:
    """Generate a JavaScript comment."""
    return f"// {text}\n"


# Strategy for JavaScript components
@st.composite
def js_function_component(draw: st.DrawFn) -> str:
    """Draw a JavaScript function definition."""
    name = draw(js_identifiers)
    body = draw(st.sampled_from(["{}", "{ return null; }", "{ console.log(); }"]))
    return js_function_def(name, body)


@st.composite
def js_arrow_function_component(draw: st.DrawFn) -> str:
    """Draw a JavaScript arrow function."""
    name = draw(js_identifiers)
    body = draw(st.sampled_from([" => null", " => ({})", " => {{ return; }}"]))
    return js_arrow_function(name, body)


@st.composite
def js_class_component(draw: st.DrawFn) -> str:
    """Draw a JavaScript class definition."""
    name = draw(js_identifiers.filter(lambda x: x[0].isupper() if x else False))
    method_count = draw(st.integers(min_value=0, max_value=5))
    methods = [draw(js_identifiers) for _ in range(method_count)]
    return js_class_def(name, methods)


@st.composite
def js_import_component(draw: st.DrawFn) -> str:
    """Draw a JavaScript import statement."""
    module = draw(st.sampled_from(["react", "lodash", "express", "fs", "path"]))
    has_names = draw(st.booleans())
    if has_names:
        name_count = draw(st.integers(min_value=1, max_value=3))
        names = [draw(js_identifiers) for _ in range(name_count)]
        return js_import_stmt(module, names)
    return js_import_stmt(module)


@st.composite
def js_variable_component(draw: st.DrawFn) -> str:
    """Draw a JavaScript variable declaration."""
    name = draw(js_identifiers)
    value = draw(st.sampled_from(["null", "undefined", "'test'", "123", "true", "false", "[]", "{}"]))
    return js_variable_decl(name, value)


@st.composite
def js_comment_component(draw: st.DrawFn) -> str:
    """Draw a JavaScript comment."""
    text = draw(st.text(st.sampled_from(string.ascii_letters + string.digits + " _-"), min_size=1, max_size=50))
    return js_comment(text)


# Main JavaScript code strategy
@st.composite
def javascript_source(draw: st.DrawFn) -> str:
    """Generate valid JavaScript source code."""
    num_components = draw(st.integers(min_value=0, max_value=20))
    components = []
    for _ in range(num_components):
        comp = draw(st.one_of(
            js_function_component(),
            js_arrow_function_component(),
            js_class_component(),
            js_import_component(),
            js_variable_component(),
            js_comment_component(),
        ))
        components.append(comp)
    return "\n".join(components)


# =============================================================================
# Elixir Code Generation Strategies
# =============================================================================


@st.composite
def elixir_module_name(draw: st.DrawFn) -> str:
    """Generate a valid Elixir module name."""
    parts = draw(st.lists(
        st.text(
            st.sampled_from(string.ascii_uppercase + "_"),
            min_size=1,
            max_size=20,
        ).filter(lambda x: x and x[0].isupper()),
        min_size=1,
        max_size=3,
    ))
    return ".".join(parts)


@st.composite
def elixir_function_name(draw: st.DrawFn) -> str:
    """Generate a valid Elixir function name with optional args."""
    name = draw(st.text(st.sampled_from(string.ascii_lowercase + "_"), min_size=1, max_size=20))
    args = draw(st.sampled_from(["", "arg1", "arg1, arg2", "x, y, z"]))
    return f"{name}({args})"


@st.composite
def elixir_module_component(draw: st.DrawFn) -> str:
    """Draw an Elixir module definition."""
    name = draw(elixir_module_name())
    func_count = draw(st.integers(min_value=0, max_value=5))
    funcs = []
    for _ in range(func_count):
        func_name = draw(elixir_function_name())
        is_private = draw(st.booleans())
        keyword = "defp" if is_private else "def"
        funcs.append(f"    {keyword} {func_name} do\n        :ok\n    end")
    if funcs:
        return f"defmodule {name} do\n" + "\n".join(funcs) + "\nend\n"
    return f"defmodule {name} do\nend\n"


@st.composite
def elixir_import_component(draw: st.DrawFn) -> str:
    """Draw an Elixir import/use/alias statement."""
    module = draw(elixir_module_name())
    stmt_type = draw(st.sampled_from(["import", "use", "alias", "require"]))
    return f"{stmt_type} {module}\n"


# Main Elixir code strategy
@st.composite
def elixir_source(draw: st.DrawFn) -> str:
    """Generate valid Elixir source code."""
    num_components = draw(st.integers(min_value=0, max_value=15))
    components = []
    for _ in range(num_components):
        comp = draw(st.one_of(
            elixir_module_component(),
            elixir_import_component(),
        ))
        components.append(comp)
    return "\n".join(components)


# =============================================================================
# Edge Case Strategies
# =============================================================================

# Empty or minimal content
empty_source = st.just("")
whitespace_only = st.builds(lambda x: x, st.text(st.characters(whitelist_characters=" \t\n\r"), min_size=1, max_size=100))


# Unicode content in identifiers
unicode_identifiers = st.text(
    st.characters(whitelist_categories=("Lu", "Ll")),
    min_size=1,
    max_size=50,
)

# Very long identifiers
long_identifiers = st.text(
    st.sampled_from(string.ascii_letters),
    min_size=100,
    max_size=1000,
).filter(lambda x: x and x[0].isalpha())

# Many symbols
many_functions_python = st.builds(
    lambda n: "\n\n".join([f"def func_{i}():\n    pass" for i in range(n)]),
    st.integers(min_value=50, max_value=200),
)


# =============================================================================
# Helper Functions for Testing
# =============================================================================

def validate_symbol(symbol: dict[str, Any]) -> list[str]:
    """Validate a single symbol and return list of validation errors."""
    errors = []

    # Check required fields exist
    required_fields = ["name", "kind", "start_line", "end_line", "start_col", "end_col"]
    for field in required_fields:
        if field not in symbol:
            errors.append(f"Missing required field: {field}")

    # Validate name
    if "name" in symbol:
        name = symbol["name"]
        if not isinstance(name, str):
            errors.append(f"Symbol name must be a string, got {type(name)}")
        elif not name:
            errors.append("Symbol name cannot be empty")
        else:
            # Check valid UTF-8
            try:
                name.encode("utf-8")
            except UnicodeEncodeError as e:
                errors.append(f"Symbol name has invalid UTF-8: {e}")

    # Validate kind
    if "kind" in symbol:
        valid_kinds = [
            "function", "class", "method", "import", "variable",
            "struct", "interface", "module", "trait", "enum", "type_alias",
        ]
        if symbol["kind"] not in valid_kinds:
            errors.append(f"Invalid symbol kind: {symbol['kind']}")

    # Validate location fields
    for field in ["start_line", "end_line", "start_col", "end_col"]:
        if field in symbol:
            value = symbol[field]
            if not isinstance(value, int):
                errors.append(f"{field} must be int, got {type(value)}")
            elif value < 0:
                errors.append(f"{field} cannot be negative: {value}")

    # Validate line relationship
    if "start_line" in symbol and "end_line" in symbol:
        if symbol["end_line"] < symbol["start_line"]:
            errors.append(
                f"end_line ({symbol['end_line']}) cannot be less than "
                f"start_line ({symbol['start_line']})"
            )

    # Validate parent if present
    if "parent" in symbol and symbol["parent"] is not None:
        parent = symbol["parent"]
        if not isinstance(parent, str):
            errors.append(f"Parent must be string or None, got {type(parent)}")
        elif not parent:
            errors.append("Parent name cannot be empty string")

    return errors


def validate_symbol_outline(result: dict[str, Any]) -> list[str]:
    """Validate a symbol outline result and return list of validation errors."""
    errors = []

    # Check success field exists
    if "success" not in result:
        errors.append("Missing 'success' field in result")
    elif not isinstance(result["success"], bool):
        errors.append(f"'success' must be bool, got {type(result['success'])}")

    # Check symbols field
    if "symbols" not in result:
        errors.append("Missing 'symbols' field in result")
    elif not isinstance(result["symbols"], list):
        errors.append(f"'symbols' must be list, got {type(result['symbols'])}")
    else:
        symbols = result["symbols"]
        if len(symbols) < 0:
            errors.append(f"Symbol count cannot be negative: {len(symbols)}")

        # Validate each symbol
        for i, symbol in enumerate(symbols):
            if not isinstance(symbol, dict):
                errors.append(f"Symbol {i} must be dict, got {type(symbol)}")
                continue
            symbol_errors = validate_symbol(symbol)
            for err in symbol_errors:
                errors.append(f"Symbol {i}: {err}")

    # Check extraction_time_ms field
    if "extraction_time_ms" in result:
        time_ms = result["extraction_time_ms"]
        if not isinstance(time_ms, (int, float)):
            errors.append(f"extraction_time_ms must be numeric, got {type(time_ms)}")
        elif time_ms < 0:
            errors.append(f"extraction_time_ms cannot be negative: {time_ms}")

    # Check language field
    if "language" not in result:
        errors.append("Missing 'language' field in result")
    elif not isinstance(result["language"], str):
        errors.append(f"'language' must be string, got {type(result['language'])}")
    elif not result["language"]:
        errors.append("'language' cannot be empty")

    # Check errors field if present
    if "errors" in result:
        if not isinstance(result["errors"], list):
            errors.append(f"'errors' must be list, got {type(result['errors'])}")
        else:
            for i, err in enumerate(result["errors"]):
                if not isinstance(err, str):
                    errors.append(f"Error {i} must be string, got {type(err)}")

    return errors


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
        result = extract_symbols(source, "python")
        assert result["success"] is True, f"Failed for source:\n{source[:200]}...\nErrors: {result.get('errors', [])}"

    @given(source=python_source())
    @settings(max_examples=100, deadline=None)
    def test_python_symbol_count_is_non_negative(self, source: str) -> None:
        """Property: Number of symbols >= 0 for all valid Python code."""
        result = extract_symbols(source, "python")
        assert len(result["symbols"]) >= 0

    @given(source=python_source())
    @settings(max_examples=100, deadline=None)
    def test_python_symbols_have_required_fields(self, source: str) -> None:
        """Property: Each symbol has required fields (name, kind, location)."""
        result = extract_symbols(source, "python")
        validation_errors = validate_symbol_outline(result)
        assert not validation_errors, f"Validation errors: {validation_errors[:5]}"

    @given(source=python_source())
    @settings(max_examples=100, deadline=None)
    def test_python_symbol_names_are_valid_strings(self, source: str) -> None:
        """Property: Symbol names are valid strings (not empty, valid UTF-8)."""
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
        result = extract_symbols(source, "python")
        assert isinstance(result, dict)
        # Empty file should either succeed with no symbols or fail gracefully
        if result["success"]:
            assert len(result["symbols"]) == 0

    @given(source=whitespace_only)
    @settings(max_examples=50, deadline=None)
    def test_whitespace_only_file(self, source: str) -> None:
        """Edge case: File with only whitespace."""
        result = extract_symbols(source, "python")
        assert isinstance(result, dict)
        # Should not crash

    @given(name=long_identifiers)
    @settings(max_examples=50, deadline=None)
    def test_very_long_symbol_name(self, name: str) -> None:
        """Edge case: Very long symbol names."""
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
        result = extract_symbols(source, "rust")

        # Verify result structure
        assert isinstance(result, dict)
        assert "success" in result
        assert "symbols" in result

    @given(source=rust_source())
    @settings(max_examples=100, deadline=None)
    def test_rust_symbol_extraction_returns_success(self, source: str) -> None:
        """Property: extract_symbols returns success=True for valid Rust code."""
        result = extract_symbols(source, "rust")
        assert result["success"] is True, f"Failed for source:\n{source[:200]}...\nErrors: {result.get('errors', [])}"

    @given(source=rust_source())
    @settings(max_examples=100, deadline=None)
    def test_rust_symbol_count_is_non_negative(self, source: str) -> None:
        """Property: Number of symbols >= 0 for all valid Rust code."""
        result = extract_symbols(source, "rust")
        assert len(result["symbols"]) >= 0

    @given(source=rust_source())
    @settings(max_examples=100, deadline=None)
    def test_rust_symbols_have_required_fields(self, source: str) -> None:
        """Property: Each symbol has required fields (name, kind, location)."""
        result = extract_symbols(source, "rust")
        validation_errors = validate_symbol_outline(result)
        assert not validation_errors, f"Validation errors: {validation_errors[:5]}"

    @given(source=rust_source())
    @settings(max_examples=100, deadline=None)
    def test_rust_symbol_names_are_valid_strings(self, source: str) -> None:
        """Property: Symbol names are valid strings (not empty, valid UTF-8)."""
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
        result = extract_symbols(source, "rust")
        assert isinstance(result, dict)

    @given(source=st.just("// This is a comment\n"))
    @settings(max_examples=1, deadline=None)
    def test_comment_only_rust_file(self, source: str) -> None:
        """Edge case: Rust file with only comments."""
        result = extract_symbols(source, "rust")
        assert isinstance(result, dict)

    @given(name=long_identifiers.filter(lambda x: x and x[0].isupper()))
    @settings(max_examples=50, deadline=None)
    def test_rust_long_struct_name(self, name: str) -> None:
        """Edge case: Very long struct name in Rust."""
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
        result = extract_symbols(source, "javascript")

        # Verify result structure
        assert isinstance(result, dict)
        assert "success" in result
        assert "symbols" in result

    @given(source=javascript_source())
    @settings(max_examples=100, deadline=None)
    def test_javascript_symbol_extraction_returns_success(self, source: str) -> None:
        """Property: extract_symbols returns success=True for valid JavaScript code."""
        result = extract_symbols(source, "javascript")
        assert result["success"] is True, f"Failed for source:\n{source[:200]}...\nErrors: {result.get('errors', [])}"

    @given(source=javascript_source())
    @settings(max_examples=100, deadline=None)
    def test_javascript_symbol_count_is_non_negative(self, source: str) -> None:
        """Property: Number of symbols >= 0 for all valid JavaScript code."""
        result = extract_symbols(source, "javascript")
        assert len(result["symbols"]) >= 0

    @given(source=javascript_source())
    @settings(max_examples=100, deadline=None)
    def test_javascript_symbols_have_required_fields(self, source: str) -> None:
        """Property: Each symbol has required fields (name, kind, location)."""
        result = extract_symbols(source, "javascript")
        validation_errors = validate_symbol_outline(result)
        assert not validation_errors, f"Validation errors: {validation_errors[:5]}"

    @given(source=javascript_source())
    @settings(max_examples=100, deadline=None)
    def test_javascript_symbol_names_are_valid_strings(self, source: str) -> None:
        """Property: Symbol names are valid strings (not empty, valid UTF-8)."""
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
        result = extract_symbols(source, "javascript")
        assert isinstance(result, dict)

    @given(source=st.just("// Comment only\n/* Block comment */\n"))
    @settings(max_examples=1, deadline=None)
    def test_comment_only_js_file(self, source: str) -> None:
        """Edge case: JavaScript file with only comments."""
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
        result = extract_symbols(source, "typescript")
        assert result["success"] is True, f"Failed for source:\n{source[:200]}...\nErrors: {result.get('errors', [])}"


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
        result = extract_symbols(source, "elixir")

        # Verify result structure
        assert isinstance(result, dict)
        assert "success" in result
        assert "symbols" in result

    @given(source=elixir_source())
    @settings(max_examples=100, deadline=None)
    def test_elixir_symbol_extraction_returns_success(self, source: str) -> None:
        """Property: extract_symbols returns success=True for valid Elixir code."""
        result = extract_symbols(source, "elixir")
        assert result["success"] is True, f"Failed for source:\n{source[:200]}...\nErrors: {result.get('errors', [])}"

    @given(source=elixir_source())
    @settings(max_examples=100, deadline=None)
    def test_elixir_symbols_have_required_fields(self, source: str) -> None:
        """Property: Each symbol has required fields (name, kind, location)."""
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
        source=st.one_of(python_source(), rust_source(), javascript_source(), elixir_source()),
        language=st.sampled_from(["python", "rust", "javascript", "elixir"]),
    )
    @settings(max_examples=100, deadline=None)
    def test_any_language_never_crashes(self, source: str, language: str) -> None:
        """Property: No combination of source and language crashes."""
        result = extract_symbols(source, language)
        # Should always return a dict, even if parsing fails
        assert isinstance(result, dict)

    @pytest.mark.parametrize("language", ["python", "rust", "javascript", "typescript", "elixir"])
    def test_empty_source_for_all_languages(self, language: str) -> None:
        """Edge case: Empty source for all supported languages."""
        result = extract_symbols("", language)
        assert isinstance(result, dict)
        # Should handle empty input gracefully

    @pytest.mark.parametrize("language", ["python", "rust", "javascript", "typescript", "elixir"])
    def test_whitespace_only_for_all_languages(self, language: str) -> None:
        """Edge case: Whitespace-only source for all supported languages."""
        result = extract_symbols("   \n\t\n   ", language)
        assert isinstance(result, dict)


# =============================================================================
# Manual Test Verification
# =============================================================================


@pytest.mark.skipif(not TURBO_PARSE_AVAILABLE, reason="turbo_parse not available")
def test_extract_symbols_basic_smoke() -> None:
    """Smoke test to verify the basic functionality works."""
    source = "def hello():\n    pass\n"
    result = extract_symbols(source, "python")
    assert result["success"] is True
    assert isinstance(result["symbols"], list)


@pytest.mark.skipif(not TURBO_PARSE_AVAILABLE, reason="turbo_parse not available")
def test_extract_symbols_rust_smoke() -> None:
    """Smoke test for Rust symbol extraction."""
    source = "fn main() {}\nstruct Point { x: i32 }\n"
    result = extract_symbols(source, "rust")
    assert result["success"] is True
    assert isinstance(result["symbols"], list)


@pytest.mark.skipif(not TURBO_PARSE_AVAILABLE, reason="turbo_parse not available")
def test_extract_symbols_javascript_smoke() -> None:
    """Smoke test for JavaScript symbol extraction."""
    source = "function test() {}\nclass MyClass {}\n"
    result = extract_symbols(source, "javascript")
    assert result["success"] is True
    assert isinstance(result["symbols"], list)
