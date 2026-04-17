"""Elixir language test fixtures.

This package contains Elixir source code fixtures for testing Elixir language support.

Fixture categories:
- Basic fixtures: simple_module.ex, complex_module.ex
- Import/mechanism fixtures: with_imports.ex, with_macros.ex
- Framework fixtures: phoenix_controller.ex, ecto_schema.ex
- Known-gap fixtures: heex_template.heex, with_sigils.ex,
  string_interpolation.ex, binary_pattern_matching.ex, protocols.ex

Known parsing gaps:
- HEEx templates (.heex files, HEEx sigils ~H)
- Complex sigils with custom delimiters and modifiers
- Deeply nested string interpolations
- Complex binary pattern matching with bitstring modifiers
"""

import os

FIXTURES_DIR = os.path.dirname(os.path.abspath(__file__))

# List of all standard fixture files
ELIXIR_FIXTURES = [
    "simple_module.ex",
    "complex_module.ex",
    "with_imports.ex",
    "with_macros.ex",
    "phoenix_controller.ex",
    "ecto_schema.ex",
]

# List of known-gap fixtures that may not fully parse
KNOWN_GAP_FIXTURES = [
    "heex_template.heex",
    "with_sigils.ex",
    "string_interpolation.ex",
    "binary_pattern_matching.ex",
    "protocols.ex",
]


def get_fixture_path(filename: str) -> str:
    """Get the full path to an Elixir fixture file."""
    return os.path.join(FIXTURES_DIR, filename)


def get_all_fixture_paths() -> list[str]:
    """Get paths to all standard Elixir fixtures."""
    return [get_fixture_path(f) for f in ELIXIR_FIXTURES]


def get_known_gap_fixture_paths() -> list[str]:
    """Get paths to known-gap fixtures."""
    return [get_fixture_path(f) for f in KNOWN_GAP_FIXTURES]
