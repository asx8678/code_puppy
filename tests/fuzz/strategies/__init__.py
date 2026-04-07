#!/usr/bin/env python3
"""Hypothesis strategies for fuzz testing symbol extraction.

This package provides property-based testing strategies to generate
valid source code for various languages, used to verify that
extract_symbols:
1. Never crashes on valid code
2. Returns consistent results
3. Handles edge cases properly
4. Maintains invariants across all inputs
"""

from __future__ import annotations

from typing import Any

import pytest

# Hypothesis imports
from hypothesis import (
    HealthCheck,
    settings as hypothesis_settings,
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


# Import all strategies for easy access
from .common import (
    build_identifier,
    empty_source,
    long_identifiers,
    many_functions_python,
    unicode_identifiers,
    validate_symbol,
    validate_symbol_outline,
    whitespace_only,
)
from .elixir import elixir_import_component, elixir_module_component, elixir_source
from .javascript import javascript_source
from .python import python_source
from .rust import rust_source


def register_hypothesis_profiles() -> None:
    """Register hypothesis profiles for different test modes."""
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


__all__ = [
    # Availability flag
    "TURBO_PARSE_AVAILABLE",
    "extract_symbols",
    # Common helpers
    "build_identifier",
    "validate_symbol",
    "validate_symbol_outline",
    # Edge case strategies
    "empty_source",
    "whitespace_only",
    "unicode_identifiers",
    "long_identifiers",
    "many_functions_python",
    # Language-specific strategies
    "python_source",
    "rust_source",
    "javascript_source",
    "elixir_source",
    # Component strategies (for advanced use)
    "elixir_import_component",
    "elixir_module_component",
]
