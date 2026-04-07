#!/usr/bin/env python3
"""Pytest configuration for fuzz tests.

This module provides custom pytest hooks and fixtures for the fuzz test suite.
"""

import os

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m not slow')"
    )
    config.addinivalue_line(
        "markers",
        "fuzz: marks tests as fuzz tests using hypothesis property-based testing",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Modify test collection to handle markers."""
    # Add 'fuzz' marker to all tests in this directory that use hypothesis
    for item in items:
        # Mark all hypothesis-based tests with the 'fuzz' marker
        if hasattr(item, "obj") and hasattr(item.obj, "hypothesis"):
            item.add_marker(pytest.mark.fuzz)


# Load hypothesis profiles from environment variable
def pytest_load_initial_conftests(
    args: list[str], early_config: pytest.Config, parser: pytest.Parser
) -> None:
    """Load initial conftests and set up hypothesis profile."""
    # Load the appropriate hypothesis profile based on environment
    profile = os.environ.get("HYPOTHESIS_PROFILE", "local")
    try:
        from hypothesis import settings

        settings.load_profile(profile)
    except Exception:
        # If hypothesis is not installed or profile doesn't exist, ignore
        pass
