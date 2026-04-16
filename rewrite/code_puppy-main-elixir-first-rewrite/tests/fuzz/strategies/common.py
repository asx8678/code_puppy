#!/usr/bin/env python3
"""Common helpers and edge case strategies for fuzz testing.

This module provides:
1. Identifier generation utilities
2. Validation helpers for symbol extraction results
3. Edge case strategies (empty content, unicode, long identifiers, etc.)
"""

import string
from typing import Any

from hypothesis import strategies as st


# =============================================================================
# Identifier Character Sets
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


# =============================================================================
# Identifier Builders
# =============================================================================


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
    ).filter(
        lambda x: (
            len(x) >= min_length and not x.startswith("__") and not x.endswith("__")
        )
    )


# Pre-built identifier strategies
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
# Validation Helpers
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
            "function",
            "class",
            "method",
            "import",
            "variable",
            "struct",
            "interface",
            "module",
            "trait",
            "enum",
            "type_alias",
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
# Edge Case Strategies
# =============================================================================

# Empty or minimal content
empty_source = st.just("")
whitespace_only = st.builds(
    lambda x: x,
    st.text(st.characters(whitelist_characters=" \t\n\r"), min_size=1, max_size=100),
)

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


__all__ = [
    # Identifier character sets
    "python_identifier_start",
    "python_identifier_continue",
    "rust_identifier_start",
    "rust_identifier_continue",
    "js_identifier_start",
    "js_identifier_continue",
    # Identifier builders
    "build_identifier",
    "python_identifiers",
    "rust_identifiers",
    "js_identifiers",
    # Validation helpers
    "validate_symbol",
    "validate_symbol_outline",
    # Edge case strategies
    "empty_source",
    "whitespace_only",
    "unicode_identifiers",
    "long_identifiers",
    "many_functions_python",
]
