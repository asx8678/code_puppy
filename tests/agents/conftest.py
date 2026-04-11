"""Test fixtures and configuration for agents tests."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def mock_summarization_config():
    """Auto-mock new summarization config functions for all tests."""
    patches = [
        patch(
            "code_puppy.config.get_summarization_pretruncate_enabled",
            return_value=False,
        ),
        patch(
            "code_puppy.config.get_summarization_arg_max_length",
            return_value=500,
        ),
        patch(
            "code_puppy.config.get_summarization_history_offload_enabled",
            return_value=False,
        ),
        patch(
            "code_puppy.compaction.compute_summarization_thresholds",
            return_value=MagicMock(
                trigger_tokens=170000,
                keep_tokens=50,  # Small value so tests actually summarize
                source="test_fallback",
            ),
        ),
    ]
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()
