"""Tests for enhanced sub-agent completion summary with metrics.

Tests the enhanced completion message that includes:
- Model name
- Duration (seconds)
- Tool call count
- Token count
- Cost (dollar amount)
"""

import pytest
from unittest.mock import MagicMock, patch
import time

from code_puppy.tools.agent_tools import (
    _format_subagent_completion_message,
)
from code_puppy.messaging.subagent_console import AgentState


class TestFormatSubagentCompletionMessage:
    """Test the _format_subagent_completion_message helper function."""

    def test_format_with_all_metrics(self):
        """Test formatting with all metrics available."""
        agent_state = MagicMock()
        agent_state.model_name = "claude-sonnet-4"
        agent_state.tool_call_count = 8
        agent_state.token_count = 12430
        agent_state.elapsed_seconds.return_value = 14.2

        with patch(
            "code_puppy.plugins.cost_tracker.register_callbacks.get_cost_summary",
            return_value={"session_cost_usd": 0.31},
        ):
            result = _format_subagent_completion_message("code-puppy", agent_state)

        assert "✓ code-puppy completed" in result
        assert "claude-sonnet-4" in result
        assert "14.2s" in result
        assert "8 tools" in result
        assert "12.4k tok" in result
        assert "$0.31" in result

    def test_format_fallback_without_agent_state(self):
        """Test fallback message when AgentState is None."""
        result = _format_subagent_completion_message("test-agent", None)
        assert result == "✓ test-agent completed successfully"

    def test_format_without_cost_tracker(self):
        """Test formatting when cost tracker is unavailable."""
        agent_state = MagicMock()
        agent_state.model_name = "gpt-4o"
        agent_state.tool_call_count = 3
        agent_state.token_count = 500
        agent_state.elapsed_seconds.return_value = 5.5

        with patch(
            "code_puppy.plugins.cost_tracker.register_callbacks.get_cost_summary",
            side_effect=ImportError("No module named cost_tracker"),
        ):
            result = _format_subagent_completion_message("test-agent", agent_state)

        assert "✓ test-agent completed" in result
        assert "gpt-4o" in result
        assert "5.5s" in result
        assert "3 tools" in result
        assert "500 tok" in result
        assert "$" not in result  # No cost should be in message

    def test_format_with_zero_cost(self):
        """Test that zero cost is not shown."""
        agent_state = MagicMock()
        agent_state.model_name = "gpt-4o-mini"
        agent_state.tool_call_count = 2
        agent_state.token_count = 850
        agent_state.elapsed_seconds.return_value = 3.2

        with patch(
            "code_puppy.plugins.cost_tracker.register_callbacks.get_cost_summary",
            return_value={"session_cost_usd": 0.0},
        ):
            result = _format_subagent_completion_message("test-agent", agent_state)

        assert "850 tok" in result
        assert "$" not in result  # Zero cost should not be shown

    def test_small_token_count_formatting(self):
        """Test that small token counts are displayed without 'k' suffix."""
        agent_state = MagicMock()
        agent_state.model_name = "gpt-4o-mini"
        agent_state.tool_call_count = 2
        agent_state.token_count = 850  # Less than 1000
        agent_state.elapsed_seconds.return_value = 3.2

        with patch(
            "code_puppy.plugins.cost_tracker.register_callbacks.get_cost_summary",
            side_effect=ImportError("No module named cost_tracker"),
        ):
            result = _format_subagent_completion_message("test-agent", agent_state)

        assert "850 tok" in result
        assert "k tok" not in result  # Should not have 'k' suffix

    def test_large_token_count_formatting(self):
        """Test that large token counts are formatted with 'k' suffix."""
        agent_state = MagicMock()
        agent_state.model_name = "gpt-4o"
        agent_state.tool_call_count = 10
        agent_state.token_count = 1500000  # 1.5M tokens
        agent_state.elapsed_seconds.return_value = 120.5

        with patch(
            "code_puppy.plugins.cost_tracker.register_callbacks.get_cost_summary",
            side_effect=ImportError("No module named cost_tracker"),
        ):
            result = _format_subagent_completion_message("test-agent", agent_state)

        assert "1500.0k tok" in result

    def test_duration_formatting(self):
        """Test that duration is formatted with one decimal place."""
        agent_state = MagicMock()
        agent_state.model_name = "gpt-4o"
        agent_state.tool_call_count = 1
        agent_state.token_count = 100
        agent_state.elapsed_seconds.return_value = 1.0

        with patch(
            "code_puppy.plugins.cost_tracker.register_callbacks.get_cost_summary",
            side_effect=ImportError("No module named cost_tracker"),
        ):
            result = _format_subagent_completion_message("test-agent", agent_state)

        assert "1.0s" in result

    def test_message_structure_with_cost(self):
        """Test the complete message structure when cost is available."""
        agent_state = MagicMock()
        agent_state.model_name = "claude-3-opus"
        agent_state.tool_call_count = 5
        agent_state.token_count = 2500
        agent_state.elapsed_seconds.return_value = 8.5

        with patch(
            "code_puppy.plugins.cost_tracker.register_callbacks.get_cost_summary",
            return_value={"session_cost_usd": 0.05},
        ):
            result = _format_subagent_completion_message("retriever", agent_state)

        # Expected format: "✓ retriever completed · claude-3-opus · 8.5s · 5 tools · 2.5k tok · $0.05"
        parts = result.split(" · ")
        assert len(parts) == 6
        assert parts[0] == "✓ retriever completed"
        assert parts[1] == "claude-3-opus"
        assert parts[2] == "8.5s"
        assert parts[3] == "5 tools"
        assert parts[4] == "2.5k tok"
        assert parts[5] == "$0.05"

    def test_message_structure_without_cost(self):
        """Test the complete message structure when cost is not available."""
        agent_state = MagicMock()
        agent_state.model_name = "gpt-4o"
        agent_state.tool_call_count = 3
        agent_state.token_count = 750
        agent_state.elapsed_seconds.return_value = 4.2

        with patch(
            "code_puppy.plugins.cost_tracker.register_callbacks.get_cost_summary",
            side_effect=Exception("Cost tracker error"),
        ):
            result = _format_subagent_completion_message("husky", agent_state)

        # Expected format: "✓ husky completed · gpt-4o · 4.2s · 3 tools · 750 tok"
        parts = result.split(" · ")
        assert len(parts) == 5
        assert parts[0] == "✓ husky completed"
        assert parts[1] == "gpt-4o"
        assert parts[2] == "4.2s"
        assert parts[3] == "3 tools"
        assert parts[4] == "750 tok"


class TestAgentStateBasics:
    """Test AgentState functionality used in completion summary."""

    def test_agent_state_creation(self):
        """Test creating an AgentState with required fields."""
        state = AgentState(
            session_id="test-session-123",
            agent_name="test-agent",
            model_name="gpt-4o",
        )
        assert state.session_id == "test-session-123"
        assert state.agent_name == "test-agent"
        assert state.model_name == "gpt-4o"
        assert state.status == "starting"
        assert state.tool_call_count == 0
        assert state.token_count == 0

    def test_elapsed_seconds_returns_positive(self):
        """Test that elapsed_seconds returns a positive float."""
        state = AgentState(
            session_id="test",
            agent_name="test",
            model_name="gpt-4o",
        )

        elapsed = state.elapsed_seconds()
        assert 0 <= elapsed < 0.1  # Should be near zero immediately after creation

    def test_elapsed_seconds_with_simulated_time(self):
        """Test elapsed_seconds calculation by manipulating start_time."""
        state = AgentState(
            session_id="test",
            agent_name="test",
            model_name="gpt-4o",
        )

        # Simulate time passing by setting start_time to 5 seconds ago
        state.start_time = time.time() - 5.0
        elapsed = state.elapsed_seconds()

        assert 4.9 <= elapsed <= 5.1  # Should be approximately 5 seconds

    def test_elapsed_formatted_short_duration(self):
        """Test formatted elapsed time for short durations (< 60s)."""
        state = AgentState(
            session_id="test",
            agent_name="test",
            model_name="gpt-4o",
        )

        state.start_time = time.time() - 14.2
        formatted = state.elapsed_formatted()

        assert formatted == "14.2s"

    def test_elapsed_formatted_long_duration(self):
        """Test formatted elapsed time for longer durations (>= 60s)."""
        state = AgentState(
            session_id="test",
            agent_name="test",
            model_name="gpt-4o",
        )

        state.start_time = time.time() - 125.5  # 2 minutes 5.5 seconds
        formatted = state.elapsed_formatted()

        assert formatted.startswith("2m ")
        assert "5.5s" in formatted


class TestTokenCountFormatting:
    """Test token count formatting for various values."""

    def test_token_formatting_cases(self):
        """Test various token count formatting scenarios."""
        test_cases = [
            (0, "0 tok"),
            (500, "500 tok"),
            (999, "999 tok"),
            (1000, "1.0k tok"),
            (12430, "12.4k tok"),
            (1500000, "1500.0k tok"),
        ]

        for token_count, expected in test_cases:
            agent_state = MagicMock()
            agent_state.model_name = "gpt-4o"
            agent_state.tool_call_count = 1
            agent_state.token_count = token_count
            agent_state.elapsed_seconds.return_value = 1.0

            with patch(
                "code_puppy.plugins.cost_tracker.register_callbacks.get_cost_summary",
                side_effect=ImportError("No module named cost_tracker"),
            ):
                result = _format_subagent_completion_message("test-agent", agent_state)

            assert expected in result, f"Failed for token_count={token_count}: expected '{expected}' in '{result}'"


class TestDurationFormatting:
    """Test duration formatting shows one decimal place."""

    def test_duration_formatting_cases(self):
        """Test duration formatting for various values."""
        test_cases = [
            (1.0, "1.0s"),
            (14.2, "14.2s"),
            (0.5, "0.5s"),
            (123.456, "123.5s"),
        ]

        for seconds, expected in test_cases:
            agent_state = MagicMock()
            agent_state.model_name = "gpt-4o"
            agent_state.tool_call_count = 1
            agent_state.token_count = 100
            agent_state.elapsed_seconds.return_value = seconds

            with patch(
                "code_puppy.plugins.cost_tracker.register_callbacks.get_cost_summary",
                side_effect=ImportError("No module named cost_tracker"),
            ):
                result = _format_subagent_completion_message("test-agent", agent_state)

            assert expected in result, f"Failed for seconds={seconds}: expected '{expected}' in '{result}'"
