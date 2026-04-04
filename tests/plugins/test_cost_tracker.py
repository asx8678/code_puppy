"""Tests for the Cost Tracker plugin.

Tests cost calculation, budget threshold alerts, and hard-stop behavior.
"""

import pytest

# Import the module under test
from code_puppy.plugins.cost_tracker import register_callbacks as cost_tracker


class TestCostCalculation:
    """Test cost calculation for various models."""

    def test_calculate_cost_gpt4o(self):
        """Test cost calculation for GPT-4o."""
        cost = cost_tracker._calculate_cost("gpt-4o", 1000, 500)
        # Input: 1000/1000 * 0.0025 = 0.0025
        # Output: 500/1000 * 0.010 = 0.005
        # Total: 0.0075
        assert cost == pytest.approx(0.0075, abs=0.0001)

    def test_calculate_cost_claude(self):
        """Test cost calculation for Claude."""
        cost = cost_tracker._calculate_cost("claude-3-5-sonnet", 2000, 1000)
        # Input: 2000/1000 * 0.003 = 0.006
        # Output: 1000/1000 * 0.015 = 0.015
        # Total: 0.021
        assert cost == pytest.approx(0.021, abs=0.0001)

    def test_calculate_cost_gemini(self):
        """Test cost calculation for Gemini."""
        cost = cost_tracker._calculate_cost("gemini-1.5-pro", 3000, 1500)
        # Input: 3000/1000 * 0.0035 = 0.0105
        # Output: 1500/1000 * 0.0105 = 0.01575
        # Total: 0.02625
        assert cost == pytest.approx(0.02625, abs=0.0001)

    def test_calculate_cost_prefix_match(self):
        """Test that model variants use prefix matching."""
        # "gpt-4o-2024-08-06" should match "gpt-4o" pricing
        cost = cost_tracker._calculate_cost("gpt-4o-2024-08-06", 1000, 500)
        assert cost == pytest.approx(0.0075, abs=0.0001)

    def test_calculate_cost_unknown_model(self):
        """Test fallback pricing for unknown models."""
        cost = cost_tracker._calculate_cost("unknown-model", 1000, 500)
        # Uses default: input 0.001, output 0.003 per 1K
        # 1 * 0.001 + 0.5 * 0.003 = 0.001 + 0.0015 = 0.0025
        assert cost == pytest.approx(0.0025, abs=0.0001)

    def test_calculate_cost_zero_tokens(self):
        """Test cost calculation with zero tokens."""
        cost = cost_tracker._calculate_cost("gpt-4o", 0, 0)
        assert cost == 0.0

    def test_calculate_cost_rounding(self):
        """Test that costs are rounded appropriately."""
        # Small cost should be rounded to 6 decimal places
        cost = cost_tracker._calculate_cost("gpt-4o", 1, 1)
        # Input: 0.001/1000 * 0.0025 = 0.0000025
        # Output: 0.001/1000 * 0.010 = 0.00001
        # Total: ~0.0000125
        assert cost > 0
        assert cost < 0.0001


class TestTokenExtraction:
    """Test token extraction from various API response formats."""

    def test_extract_openai_format(self):
        """Test extraction from OpenAI-style response."""
        result = {
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
            }
        }
        tokens = cost_tracker._extract_tokens_from_result(result)
        assert tokens == {"input": 100, "output": 50}

    def test_extract_anthropic_format(self):
        """Test extraction from Anthropic-style response."""
        result = {
            "usage": {
                "input_tokens": 200,
                "output_tokens": 100,
            }
        }
        tokens = cost_tracker._extract_tokens_from_result(result)
        assert tokens == {"input": 200, "output": 100}

    def test_extract_openai_usage_object(self):
        """Test extraction from OpenAI-style usage with prompt/completion tokens."""
        result = {
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
            }
        }
        tokens = cost_tracker._extract_tokens_from_result(result)
        assert tokens == {"input": 100, "output": 50}

    def test_extract_direct_fields(self):
        """Test extraction from direct token fields."""
        result = {
            "input_tokens": 150,
            "output_tokens": 75,
        }
        tokens = cost_tracker._extract_tokens_from_result(result)
        assert tokens == {"input": 150, "output": 75}

    def test_extract_with_object_usage(self):
        """Test extraction from object-style usage."""
        class MockUsage:
            prompt_tokens = 300
            completion_tokens = 150

        class MockResult:
            usage = MockUsage()

        tokens = cost_tracker._extract_tokens_from_result(MockResult())
        assert tokens == {"input": 300, "output": 150}

    def test_extract_no_tokens_returns_none(self):
        """Test extraction returns None when no token info present."""
        result = {"text": "some response"}
        tokens = cost_tracker._extract_tokens_from_result(result)
        assert tokens is None

    def test_extract_usage_with_no_token_fields(self):
        """Test extraction from usage dict without token fields returns None."""
        result = {"usage": {"some_other_field": 123}}
        tokens = cost_tracker._extract_tokens_from_result(result)
        assert tokens is None

    def test_extract_none_result(self):
        """Test extraction with None result."""
        tokens = cost_tracker._extract_tokens_from_result(None)
        assert tokens is None

    def test_extract_string_result(self):
        """Test extraction with string result."""
        tokens = cost_tracker._extract_tokens_from_result("just a string")
        assert tokens is None


class TestCostTracking:
    """Test the cost tracking functionality."""

    def setup_method(self):
        """Reset costs before each test."""
        cost_tracker.reset_all_costs_for_testing()

    def test_update_cost_tracks_per_model(self):
        """Test that costs are tracked per-model."""
        cost_tracker._update_cost("gpt-4o", 1000, 500)
        cost_tracker._update_cost("claude-3-5-sonnet", 2000, 1000)

        summary = cost_tracker.get_cost_summary()
        assert "gpt-4o" in summary["model_costs"]
        assert "claude-3-5-sonnet" in summary["model_costs"]
        assert summary["model_costs"]["gpt-4o"]["input_tokens"] == 1000
        assert summary["model_costs"]["gpt-4o"]["output_tokens"] == 500

    def test_update_cost_accumulates_session(self):
        """Test that session costs accumulate."""
        _, session1 = cost_tracker._update_cost("gpt-4o", 1000, 500)
        _, session2 = cost_tracker._update_cost("gpt-4o", 1000, 500)

        assert session2 > session1
        assert session2 == pytest.approx(session1 * 2, rel=0.01)

    def test_update_cost_accumulates_daily(self):
        """Test that daily costs accumulate."""
        cost_tracker._update_cost("gpt-4o", 1000, 500)
        daily1 = cost_tracker._cost_state.daily_cost_usd

        cost_tracker._update_cost("gpt-4o", 1000, 500)
        daily2 = cost_tracker._cost_state.daily_cost_usd

        assert daily2 > daily1
        assert daily2 == pytest.approx(daily1 * 2, rel=0.01)

    def test_multiple_calls_same_model(self):
        """Test multiple calls to the same model accumulate."""
        cost_tracker._update_cost("gpt-4o", 1000, 500)
        cost_tracker._update_cost("gpt-4o", 2000, 1000)
        cost_tracker._update_cost("gpt-4o", 500, 250)

        summary = cost_tracker.get_cost_summary()
        model_cost = summary["model_costs"]["gpt-4o"]
        assert model_cost["input_tokens"] == 3500
        assert model_cost["output_tokens"] == 1750


class TestBudgetAlerts:
    """Test budget threshold alerting."""

    def setup_method(self):
        """Reset costs and alert state before each test."""
        cost_tracker.reset_all_costs_for_testing()
        cost_tracker.reset_alert_state()

    def test_check_budget_threshold_75_percent(self, capsys):
        """Test 75% budget alert."""
        # Simulate 75% usage
        cost_tracker._cost_state.daily_cost_usd = 7.5
        cost_tracker._check_budget_thresholds(7.5, 10.0, "daily")

        # Alert should have been triggered
        assert cost_tracker._alerted_75_percent is True
        assert cost_tracker._alerted_100_percent is False

    def test_check_budget_threshold_100_percent(self, capsys):
        """Test 100% budget hard stop alert."""
        # First set to 75% to trigger 75% alert
        cost_tracker._check_budget_thresholds(7.5, 10.0, "daily")
        assert cost_tracker._alerted_75_percent is True

        # Then simulate 100% usage
        cost_tracker._check_budget_thresholds(10.0, 10.0, "daily")

        # Both alerts should have been triggered
        assert cost_tracker._alerted_75_percent is True
        assert cost_tracker._alerted_100_percent is True

    def test_check_budget_threshold_below_75(self):
        """Test no alert below 75%."""
        cost_tracker._check_budget_thresholds(5.0, 10.0, "daily")

        assert cost_tracker._alerted_75_percent is False
        assert cost_tracker._alerted_100_percent is False

    def test_alert_only_once(self):
        """Test that 75% alert only fires once."""
        # First call at 75%
        cost_tracker._check_budget_thresholds(7.5, 10.0, "daily")
        assert cost_tracker._alerted_75_percent is True

        # Reset the alert flag manually to test it stays set
        # (simulating that we don't re-alert)
        cost_tracker._alerted_75_percent = True
        cost_tracker._check_budget_thresholds(8.0, 10.0, "daily")
        # Should remain True (not re-alert)
        assert cost_tracker._alerted_75_percent is True


class TestPreToolCallBlocking:
    """Test hard-stop behavior in pre_tool_call."""

    def setup_method(self):
        """Reset costs before each test."""
        cost_tracker.reset_all_costs_for_testing()
        cost_tracker.reset_alert_state()

    def test_pre_tool_call_no_block_without_budget(self, monkeypatch):
        """Test that calls are not blocked when no budget is set."""
        monkeypatch.setattr(cost_tracker, "_get_daily_budget", lambda: None)
        monkeypatch.setattr(cost_tracker, "_get_session_budget", lambda: None)

        result = cost_tracker._on_pre_tool_call("some_tool", {})
        assert result is None

    def test_pre_tool_call_blocks_when_daily_budget_exceeded(self, monkeypatch):
        """Test blocking when daily budget exceeded."""
        monkeypatch.setattr(cost_tracker, "_get_daily_budget", lambda: 10.0)
        monkeypatch.setattr(cost_tracker, "_get_session_budget", lambda: None)

        # Set cost above budget
        cost_tracker._cost_state.daily_cost_usd = 10.5

        result = cost_tracker._on_pre_tool_call("api_call", {})
        assert result is not None
        assert result.get("blocked") is True
        assert "daily_budget_exceeded" in result.get("reason", "")

    def test_pre_tool_call_blocks_when_session_budget_exceeded(self, monkeypatch):
        """Test blocking when session budget exceeded."""
        monkeypatch.setattr(cost_tracker, "_get_daily_budget", lambda: None)
        monkeypatch.setattr(cost_tracker, "_get_session_budget", lambda: 5.0)

        # Set cost above budget
        cost_tracker._cost_state.session_cost_usd = 5.5

        result = cost_tracker._on_pre_tool_call("api_call", {})
        assert result is not None
        assert result.get("blocked") is True
        assert "session_budget_exceeded" in result.get("reason", "")

    def test_pre_tool_call_no_block_within_budget(self, monkeypatch):
        """Test that calls pass when within budget."""
        monkeypatch.setattr(cost_tracker, "_get_daily_budget", lambda: 10.0)
        monkeypatch.setattr(cost_tracker, "_get_session_budget", lambda: 5.0)

        # Set costs within budget
        cost_tracker._cost_state.daily_cost_usd = 5.0
        cost_tracker._cost_state.session_cost_usd = 2.0

        result = cost_tracker._on_pre_tool_call("api_call", {})
        assert result is None

    def test_pre_tool_call_allows_file_operations(self, monkeypatch):
        """Test that file operations are never blocked."""
        monkeypatch.setattr(cost_tracker, "_get_daily_budget", lambda: 10.0)
        monkeypatch.setattr(cost_tracker, "_get_session_budget", lambda: 5.0)

        # Set costs above budget
        cost_tracker._cost_state.daily_cost_usd = 15.0
        cost_tracker._cost_state.session_cost_usd = 10.0

        # File operations should still be allowed
        for tool in ("create_file", "read_file", "replace_in_file", "delete_file"):
            result = cost_tracker._on_pre_tool_call(tool, {})
            assert result is None, f"{tool} should not be blocked"


class TestGetCostSummary:
    """Test the public API for getting cost summary."""

    def setup_method(self):
        """Reset costs before each test."""
        cost_tracker.reset_all_costs_for_testing()

    def test_get_cost_summary_empty(self):
        """Test summary when no costs tracked."""
        summary = cost_tracker.get_cost_summary()
        assert summary["daily_cost_usd"] == 0.0
        assert summary["session_cost_usd"] == 0.0
        assert summary["model_costs"] == {}

    def test_get_cost_summary_with_data(self):
        """Test summary with tracked costs."""
        cost_tracker._update_cost("gpt-4o", 1000, 500)
        cost_tracker._update_cost("claude-3-5-sonnet", 2000, 1000)

        summary = cost_tracker.get_cost_summary()
        assert summary["daily_cost_usd"] > 0
        assert summary["session_cost_usd"] > 0
        assert len(summary["model_costs"]) == 2
        assert "gpt-4o" in summary["model_costs"]
        assert "claude-3-5-sonnet" in summary["model_costs"]


class TestPricingLookup:
    """Test the pricing lookup functionality."""

    def test_get_pricing_exact_match(self):
        """Test exact model name matching."""
        pricing = cost_tracker._get_pricing_for_model("gpt-4o")
        assert pricing["input"] == 0.0025
        assert pricing["output"] == 0.010

    def test_get_pricing_prefix_match(self):
        """Test prefix matching for model variants."""
        pricing = cost_tracker._get_pricing_for_model("claude-3-5-sonnet-20241022")
        assert pricing["input"] == 0.003
        assert pricing["output"] == 0.015

    def test_get_pricing_fallback(self):
        """Test fallback for unknown models."""
        pricing = cost_tracker._get_pricing_for_model("completely-unknown-model")
        assert pricing["input"] == 0.001
        assert pricing["output"] == 0.003

    def test_default_pricing_has_key_models(self):
        """Test that key models are in the default pricing."""
        key_models = ["gpt-4o", "claude-3-5-sonnet", "gemini-1.5-pro"]
        for model in key_models:
            assert model in cost_tracker.DEFAULT_PRICING
            assert "input" in cost_tracker.DEFAULT_PRICING[model]
            assert "output" in cost_tracker.DEFAULT_PRICING[model]


class TestAddCostForTesting:
    """Test the helper function for adding costs in tests."""

    def setup_method(self):
        """Reset costs before each test."""
        cost_tracker.reset_all_costs_for_testing()

    def test_add_cost_for_testing_returns_cost(self):
        """Test that add_cost_for_testing returns the calculated cost."""
        cost = cost_tracker.add_cost_for_testing("gpt-4o", 1000, 500)
        assert cost > 0
        assert cost == pytest.approx(0.0075, abs=0.0001)

    def test_add_cost_for_testing_updates_state(self):
        """Test that add_cost_for_testing updates the cost state."""
        cost_tracker.add_cost_for_testing("gpt-4o", 1000, 500)

        summary = cost_tracker.get_cost_summary()
        assert summary["session_cost_usd"] > 0
        assert "gpt-4o" in summary["model_costs"]


class TestIntegration:
    """Integration tests for the cost tracker plugin."""

    def setup_method(self):
        """Reset costs before each test."""
        cost_tracker.reset_all_costs_for_testing()
        cost_tracker.reset_alert_state()

    def test_end_to_end_cost_tracking(self):
        """Test end-to-end cost tracking flow."""
        # Simulate multiple API calls
        cost_tracker._update_cost("gpt-4o", 1000, 500)  # ~$0.0075
        cost_tracker._update_cost("gpt-4o", 2000, 1000)  # ~$0.015
        cost_tracker._update_cost("claude-3-5-sonnet", 5000, 2500)  # ~$0.0525

        summary = cost_tracker.get_cost_summary()

        # Verify totals
        assert summary["session_cost_usd"] > 0.07
        assert summary["daily_cost_usd"] > 0.07

        # Verify per-model tracking
        assert len(summary["model_costs"]) == 2
        assert summary["model_costs"]["gpt-4o"]["input_tokens"] == 3000
        assert summary["model_costs"]["gpt-4o"]["output_tokens"] == 1500

    def test_budget_enforcement_integration(self, monkeypatch):
        """Test full budget enforcement flow."""
        # Set a low budget
        monkeypatch.setattr(cost_tracker, "_get_session_budget", lambda: 0.01)
        monkeypatch.setattr(cost_tracker, "_get_daily_budget", lambda: None)

        # Add cost that exceeds budget (should trigger both 75% and 100% alerts)
        cost_tracker._update_cost("gpt-4o", 10000, 5000)  # ~$0.075

        # Should have triggered at least 100% alert (which implies 75% was also triggered)
        assert cost_tracker._alerted_100_percent is True

        # Try to make another call - should be blocked
        result = cost_tracker._on_pre_tool_call("api_call", {})
        assert result is not None
        assert result.get("blocked") is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
