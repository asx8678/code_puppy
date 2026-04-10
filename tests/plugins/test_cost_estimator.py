"""Tests for cost_estimator plugin (ADOPT from Agentless)."""

import pytest

from code_puppy.plugins.cost_estimator.estimator import (
    TokenEstimate,
    _count_tokens_heuristic,
    _lookup_pricing,
    count_tokens,
    estimate_cost,
    get_session_summary,
    reset_session,
    track_session_tokens,
)


class TestCountTokensHeuristic:
    """Test character-based heuristic token counting."""

    def test_empty_string(self):
        """Empty string → 1 token minimum."""
        assert _count_tokens_heuristic("") == 1

    def test_short_text(self):
        """Short text → roughly len/4."""
        result = _count_tokens_heuristic("Hello, world!")
        assert result == max(1, len("Hello, world!") // 4)

    def test_long_text(self):
        """Longer text → proportional estimate."""
        text = "a" * 1000
        result = _count_tokens_heuristic(text)
        assert result == 250


class TestLookupPricing:
    """Test model pricing lookup."""

    def test_known_model(self):
        """Known model returns correct pricing."""
        pricing = _lookup_pricing("gpt-4o")
        assert pricing == (2.50, 10.00)

    def test_partial_match(self):
        """Partial model name match works."""
        pricing = _lookup_pricing("gpt-4o-2024-08-06")
        assert pricing == (2.50, 10.00)

    def test_unknown_model_default(self):
        """Unknown model returns conservative default."""
        pricing = _lookup_pricing("totally-unknown-model-xyz")
        assert pricing == (5.00, 15.00)


class TestCountTokens:
    """Test the main count_tokens function."""

    def test_returns_positive_integer(self):
        """Always returns a positive integer."""
        result = count_tokens("Hello, world!")
        assert isinstance(result, int)
        assert result > 0

    def test_longer_text_more_tokens(self):
        """Longer text → more tokens."""
        short = count_tokens("Hi")
        long = count_tokens("This is a much longer piece of text with many words")
        assert long > short


class TestEstimateCost:
    """Test cost estimation."""

    def test_string_prompt(self):
        """String prompt → valid estimate."""
        est = estimate_cost("Hello, world!", model="gpt-4o")
        assert isinstance(est, TokenEstimate)
        assert est.input_tokens > 0
        assert est.estimated_cost_usd > 0
        assert est.model == "gpt-4o"
        assert est.method in ("tiktoken", "heuristic")

    def test_message_list_prompt(self):
        """List of message dicts → valid estimate."""
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello!"},
        ]
        est = estimate_cost(messages, model="gpt-4o")
        assert est.input_tokens > 0

    def test_output_tokens_included(self):
        """Expected output tokens affect cost."""
        est_small = estimate_cost("Hi", expected_output_tokens=100)
        est_large = estimate_cost("Hi", expected_output_tokens=10000)
        assert est_large.estimated_cost_usd > est_small.estimated_cost_usd

    def test_different_models_different_costs(self):
        """Different models have different pricing."""
        est_4o = estimate_cost("Test prompt", model="gpt-4o")
        est_mini = estimate_cost("Test prompt", model="gpt-4o-mini")
        assert est_4o.estimated_cost_usd > est_mini.estimated_cost_usd

    def test_token_estimate_str(self):
        """TokenEstimate.__str__ produces readable output."""
        est = TokenEstimate(
            input_tokens=1000,
            output_tokens=500,
            model="gpt-4o",
            estimated_cost_usd=0.0075,
            method="tiktoken",
        )
        s = str(est)
        assert "1,000" in s
        assert "500" in s
        assert "$0.0075" in s


class TestSessionTracking:
    """Test session-level token accumulation."""

    def setup_method(self):
        """Reset session before each test."""
        reset_session()

    def test_track_and_summarize(self):
        """Track tokens → summary includes them."""
        track_session_tokens("gpt-4o", 1000)
        track_session_tokens("gpt-4o", 500)
        track_session_tokens("gpt-4o-mini", 2000)

        summary = get_session_summary()
        assert len(summary["models"]) == 2
        assert summary["total_estimated_cost_usd"] > 0

        gpt4o = next(m for m in summary["models"] if m["model"] == "gpt-4o")
        assert gpt4o["total_tokens"] == 1500

    def test_empty_session(self):
        """Empty session → no models, zero cost."""
        summary = get_session_summary()
        assert summary["models"] == []
        assert summary["total_estimated_cost_usd"] == 0.0

    def test_reset_clears(self):
        """Reset clears accumulated tokens."""
        track_session_tokens("gpt-4o", 1000)
        reset_session()
        summary = get_session_summary()
        assert summary["models"] == []
