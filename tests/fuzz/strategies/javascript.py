#!/usr/bin/env python3
"""JavaScript/TypeScript code generation strategies for fuzz testing.

This module provides Hypothesis strategies to generate valid JavaScript
and TypeScript source code for property-based testing of symbol extraction.
"""

from __future__ import annotations

from hypothesis import strategies as st

from .common import js_identifiers


# =============================================================================
# JavaScript Code Generation Helpers
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


# =============================================================================
# JavaScript Component Strategies
# =============================================================================


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
    value = draw(
        st.sampled_from(
            ["null", "undefined", "'test'", "123", "true", "false", "[]", "{}"]
        )
    )
    return js_variable_decl(name, value)


@st.composite
def js_comment_component(draw: st.DrawFn) -> str:
    """Draw a JavaScript comment."""
    import string

    text = draw(
        st.text(
            st.sampled_from(string.ascii_letters + string.digits + " _-"),
            min_size=1,
            max_size=50,
        )
    )
    return js_comment(text)


# =============================================================================
# Main JavaScript/TypeScript Code Strategy
# =============================================================================


@st.composite
def javascript_source(draw: st.DrawFn) -> str:
    """Generate valid JavaScript source code.

    Note: This can also be used for TypeScript testing since TypeScript
    is a superset of JavaScript.
    """
    num_components = draw(st.integers(min_value=0, max_value=20))
    components = []
    for _ in range(num_components):
        comp = draw(
            st.one_of(
                js_function_component(),
                js_arrow_function_component(),
                js_class_component(),
                js_import_component(),
                js_variable_component(),
                js_comment_component(),
            )
        )
        components.append(comp)
    return "\n".join(components)


__all__ = [
    # Helper functions
    "js_function_def",
    "js_arrow_function",
    "js_class_def",
    "js_import_stmt",
    "js_variable_decl",
    "js_comment",
    # Component strategies
    "js_function_component",
    "js_arrow_function_component",
    "js_class_component",
    "js_import_component",
    "js_variable_component",
    "js_comment_component",
    # Main strategy
    "javascript_source",
]
