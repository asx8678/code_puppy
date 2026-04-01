"""Pytest configuration for the evals directory.

Registers the `eval` marker and auto-skips all eval tests unless
the RUN_EVALS=1 environment variable is set.

Usage:
    pytest evals/           # All eval tests SKIPPED (default)
    RUN_EVALS=1 pytest evals/  # All eval tests RUN
"""

import os

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Register the eval marker to avoid PytestUnknownMarkWarning."""
    config.addinivalue_line(
        "markers",
        "eval: LLM evaluation test (skipped unless RUN_EVALS=1 is set)",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip all tests marked with @pytest.mark.eval unless RUN_EVALS=1."""
    if os.environ.get("RUN_EVALS") == "1":
        return  # Don't skip — run everything

    skip_marker = pytest.mark.skip(
        reason="Eval tests are skipped by default. Set RUN_EVALS=1 to run."
    )
    for item in items:
        if item.get_closest_marker("eval"):
            item.add_marker(skip_marker)
