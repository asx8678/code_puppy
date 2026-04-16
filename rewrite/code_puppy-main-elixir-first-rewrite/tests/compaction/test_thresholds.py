"""Tests for compaction.thresholds module."""

from unittest.mock import patch

import pytest

from code_puppy.compaction.thresholds import (
    DEFAULT_ABSOLUTE_PROTECTED,
    DEFAULT_ABSOLUTE_TRIGGER,
    SummarizationThresholds,
    compute_summarization_thresholds,
    get_model_context_window,
)


class TestGetModelContextWindow:
    """Tests for get_model_context_window function."""

    def test_known_model_returns_context(self):
        """Known model should return its context length."""
        with patch("code_puppy.model_factory.ModelFactory.load_config") as mock_load:
            mock_load.return_value = {
                "claude-sonnet": {"context_length": 200000},
            }
            result = get_model_context_window("claude-sonnet")
            assert result == 200000

    def test_unknown_model_returns_none(self):
        """Unknown model should return None."""
        with patch("code_puppy.model_factory.ModelFactory.load_config") as mock_load:
            mock_load.return_value = {}
            result = get_model_context_window("unknown-model")
            assert result is None

    def test_model_without_context_length_returns_none(self):
        """Model without context_length field returns None."""
        with patch("code_puppy.model_factory.ModelFactory.load_config") as mock_load:
            mock_load.return_value = {
                "model-without-context": {"type": "openai"},
            }
            result = get_model_context_window("model-without-context")
            assert result is None

    def test_load_config_exception_returns_none(self):
        """Exception during config load returns None."""
        with patch("code_puppy.model_factory.ModelFactory.load_config") as mock_load:
            mock_load.side_effect = Exception("config error")
            result = get_model_context_window("any-model")
            assert result is None


class TestComputeSummarizationThresholds:
    """Tests for compute_summarization_thresholds function."""

    def test_known_model_uses_fractions(self):
        """Known model with context uses fraction-based thresholds."""
        with patch("code_puppy.compaction.thresholds.get_model_context_window") as mock_get:
            mock_get.return_value = 100000  # 100k context
            result = compute_summarization_thresholds("known-model")

            assert result.source == "model_aware_fraction"
            # 100k * 0.85 = 85k trigger
            assert result.trigger_tokens == 85000
            # 100k * 0.10 = 10k keep
            assert result.keep_tokens == 10000

    def test_unknown_model_uses_absolute_fallback(self):
        """Unknown model falls back to absolute values."""
        with patch("code_puppy.compaction.thresholds.get_model_context_window") as mock_get:
            mock_get.return_value = None
            result = compute_summarization_thresholds("unknown-model")

            assert result.source == "absolute_fallback"
            assert result.trigger_tokens == DEFAULT_ABSOLUTE_TRIGGER
            assert result.keep_tokens == DEFAULT_ABSOLUTE_PROTECTED

    def test_custom_fractions(self):
        """Custom fractions are applied correctly."""
        with patch("code_puppy.compaction.thresholds.get_model_context_window") as mock_get:
            mock_get.return_value = 100000
            result = compute_summarization_thresholds(
                "known-model",
                trigger_fraction=0.90,
                keep_fraction=0.15,
            )

            assert result.trigger_tokens == 90000  # 100k * 0.90
            assert result.keep_tokens == 15000  # 100k * 0.15

    def test_custom_absolute_values(self):
        """Custom absolute values are used in fallback."""
        with patch("code_puppy.compaction.thresholds.get_model_context_window") as mock_get:
            mock_get.return_value = None
            result = compute_summarization_thresholds(
                "unknown-model",
                absolute_trigger=50000,
                absolute_protected=10000,
            )

            assert result.trigger_tokens == 50000
            assert result.keep_tokens == 10000

    def test_trigger_fraction_clamped_to_1(self):
        """Trigger fraction > 1.0 is clamped to 1.0."""
        with patch("code_puppy.compaction.thresholds.get_model_context_window") as mock_get:
            mock_get.return_value = 100000
            result = compute_summarization_thresholds(
                "known-model",
                trigger_fraction=1.5,  # > 1.0
            )

            assert result.trigger_tokens == 100000  # clamped to 100%

    def test_trigger_fraction_clamped_to_0(self):
        """Trigger fraction < 0 is clamped to 0."""
        with patch("code_puppy.compaction.thresholds.get_model_context_window") as mock_get:
            mock_get.return_value = 100000
            result = compute_summarization_thresholds(
                "known-model",
                trigger_fraction=-0.5,  # < 0
            )

            assert result.trigger_tokens == 1000  # minimum floor

    def test_keep_exceeds_trigger_is_adjusted(self):
        """When keep would exceed trigger, it's adjusted down."""
        with patch("code_puppy.compaction.thresholds.get_model_context_window") as mock_get:
            mock_get.return_value = 1000  # Small context
            result = compute_summarization_thresholds(
                "small-model",
                trigger_fraction=0.5,  # 500 tokens
                keep_fraction=0.6,  # Would be 600 tokens - exceeds trigger!
            )

            # keep_tokens should be adjusted to less than trigger_tokens
            assert result.keep_tokens < result.trigger_tokens

    def test_small_context_enforces_minimums(self):
        """Very small contexts enforce minimum token thresholds."""
        with patch("code_puppy.compaction.thresholds.get_model_context_window") as mock_get:
            mock_get.return_value = 100  # Very small
            result = compute_summarization_thresholds("tiny-model")

            # Should have minimum floor values
            assert result.trigger_tokens >= 1000
            assert result.keep_tokens >= 100

    def test_result_is_frozen_dataclass(self):
        """Result is a frozen dataclass that can't be modified."""
        with patch("code_puppy.compaction.thresholds.get_model_context_window") as mock_get:
            mock_get.return_value = 100000
            result = compute_summarization_thresholds("known-model")

            with pytest.raises(Exception):  # FrozenInstanceError
                result.trigger_tokens = 99999

    def test_returns_summarization_thresholds_type(self):
        """Function returns correct type."""
        with patch("code_puppy.compaction.thresholds.get_model_context_window") as mock_get:
            mock_get.return_value = 100000
            result = compute_summarization_thresholds("known-model")

            assert isinstance(result, SummarizationThresholds)
