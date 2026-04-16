#!/usr/bin/env python3
"""Rust code generation strategies for fuzz testing.

This module provides Hypothesis strategies to generate valid Rust
source code for property-based testing of symbol extraction.
"""

from hypothesis import strategies as st

from .common import rust_identifiers


# =============================================================================
# Rust Code Generation Helpers
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


# =============================================================================
# Rust Component Strategies
# =============================================================================


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


# =============================================================================
# Main Rust Code Strategy
# =============================================================================


@st.composite
def rust_source(draw: st.DrawFn) -> str:
    """Generate valid Rust source code."""
    num_components = draw(st.integers(min_value=0, max_value=20))
    components = []
    for _ in range(num_components):
        comp = draw(
            st.one_of(
                rust_function_component(),
                rust_struct_component(),
                rust_impl_component(),
                rust_trait_component(),
                rust_use_component(),
                rust_mod_component(),
            )
        )
        components.append(comp)
    return "\n".join(components)


__all__ = [
    # Helper functions
    "rust_function_def",
    "rust_struct_def",
    "rust_impl_block",
    "rust_trait_def",
    "rust_use_stmt",
    "rust_comment",
    "rust_mod_def",
    # Component strategies
    "rust_function_component",
    "rust_struct_component",
    "rust_impl_component",
    "rust_trait_component",
    "rust_use_component",
    "rust_mod_component",
    # Main strategy
    "rust_source",
]
