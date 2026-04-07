#!/usr/bin/env python3
"""Elixir code generation strategies for fuzz testing.

This module provides Hypothesis strategies to generate valid Elixir
source code for property-based testing of symbol extraction.
"""

from __future__ import annotations

import string

from hypothesis import strategies as st


# =============================================================================
# Elixir Component Strategies
# =============================================================================


@st.composite
def elixir_module_name(draw: st.DrawFn) -> str:
    """Generate a valid Elixir module name."""
    parts = draw(
        st.lists(
            st.text(
                st.sampled_from(string.ascii_uppercase + "_"),
                min_size=1,
                max_size=20,
            ).filter(lambda x: x and x[0].isupper()),
            min_size=1,
            max_size=3,
        )
    )
    return ".".join(parts)


@st.composite
def elixir_function_name(draw: st.DrawFn) -> str:
    """Generate a valid Elixir function name with optional args."""
    name = draw(
        st.text(st.sampled_from(string.ascii_lowercase + "_"), min_size=1, max_size=20)
    )
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


# =============================================================================
# Main Elixir Code Strategy
# =============================================================================


@st.composite
def elixir_source(draw: st.DrawFn) -> str:
    """Generate valid Elixir source code."""
    num_components = draw(st.integers(min_value=0, max_value=15))
    components = []
    for _ in range(num_components):
        comp = draw(
            st.one_of(
                elixir_module_component(),
                elixir_import_component(),
            )
        )
        components.append(comp)
    return "\n".join(components)


__all__ = [
    # Component strategies
    "elixir_module_name",
    "elixir_function_name",
    "elixir_module_component",
    "elixir_import_component",
    # Main strategy
    "elixir_source",
]
