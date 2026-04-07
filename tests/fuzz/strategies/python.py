#!/usr/bin/env python3
"""Python code generation strategies for fuzz testing.

This module provides Hypothesis strategies to generate valid Python
source code for property-based testing of symbol extraction.
"""

from __future__ import annotations

from hypothesis import strategies as st

from .common import python_identifiers


# =============================================================================
# Python Code Generation Helpers
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


# =============================================================================
# Python Component Strategies
# =============================================================================


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
    import string

    text = draw(
        st.text(
            st.sampled_from(string.ascii_letters + string.digits + " _-"),
            min_size=1,
            max_size=50,
        )
    )
    return python_comment(text)


# =============================================================================
# Main Python Code Strategy
# =============================================================================


@st.composite
def python_source(draw: st.DrawFn) -> str:
    """Generate valid Python source code."""
    num_components = draw(st.integers(min_value=0, max_value=20))
    components = []
    for _ in range(num_components):
        comp = draw(
            st.one_of(
                python_function_component(),
                python_class_component(),
                python_import_component(),
                python_comment_component(),
            )
        )
        components.append(comp)
    return "\n".join(components)


__all__ = [
    # Helper functions
    "python_function_def",
    "python_class_def",
    "python_import_stmt",
    "python_comment",
    "python_docstring",
    # Component strategies
    "python_function_component",
    "python_class_component",
    "python_import_component",
    "python_comment_component",
    # Main strategy
    "python_source",
]
