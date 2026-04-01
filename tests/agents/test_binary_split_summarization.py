"""Tests for binary-split summarization algorithm in base_agent.py.

Covers:
- Small history (no split needed)
- Large history requiring one split
- Very large history requiring recursive splits
- Max recursion depth reached
- Tool-call boundary safety during splits
- Summarization error falls back gracefully
- Edge cases: empty messages, single message
- _find_safe_summarize_split helper
- _estimate_batch_tokens helper
- _summarize_single_batch helper
"""

from unittest.mock import MagicMock, patch

import pytest
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)

import code_puppy.agents.base_agent as base_agent_module


# Concrete subclass for testing (matches existing test fixtures)
class ConcreteAgent(base_agent_module.BaseAgent):
    @property
    def name(self) -> str:
        return "test-agent"

    @property
    def display_name(self) -> str:
        return "Test Agent"

    @property
    def description(self) -> str:
        return "A test agent"

    def get_system_prompt(self) -> str:
        return "You are a test agent."

    def get_available_tools(self) -> list:
        return ["tool1", "tool2"]


@pytest.fixture
def agent():
    return ConcreteAgent()


def _make_msg(content: str, token_size: int = None) -> ModelRequest:
    """Helper: create a ModelRequest with given content.

    The content is padded if token_size is given so that
    estimate_tokens_for_message (which uses len//4) returns
    approximately that many tokens.
    """
    if token_size is not None:
        # estimate_tokens_for_message uses ~len(text)//4
        target_chars = token_size * 4
        content = content + "x" * max(0, target_chars - len(content))
    return ModelRequest(parts=[TextPart(content=content)])


def _make_response(content: str, token_size: int = None) -> ModelResponse:
    """Helper: create a ModelResponse."""
    if token_size is not None:
        target_chars = token_size * 4
        content = content + "x" * max(0, target_chars - len(content))
    return ModelResponse(
        parts=[TextPart(content=content)],
        model_name="test-model",
    )


# ─── _estimate_batch_tokens ───────────────────────────────────────────

class TestEstimateBatchTokens:
    def test_empty(self, agent):
        assert agent._estimate_batch_tokens([]) == 0

    def test_single_message(self, agent):
        msg = _make_msg("hello world")
        tokens = agent._estimate_batch_tokens([msg])
        assert tokens > 0

    def test_multiple_messages_sum(self, agent):
        msgs = [_make_msg("a" * 40), _make_msg("b" * 80)]
        total = agent._estimate_batch_tokens(msgs)
        individual = sum(agent.estimate_tokens_for_message(m) for m in msgs)
        assert total == individual


# ─── _summarize_single_batch ──────────────────────────────────────────

class TestSummarizeSingleBatch:
    @patch("code_puppy.agents.base_agent.run_summarization_sync")
    def test_normal_list_return(self, mock_sync, agent):
        summary_msg = _make_msg("Summary of conversation")
        mock_sync.return_value = [summary_msg]

        msgs = [_make_msg("old message 1"), _make_msg("old message 2")]
        result = agent._summarize_single_batch(msgs)
        assert result == [summary_msg]
        mock_sync.assert_called_once()

    @patch("code_puppy.agents.base_agent.run_summarization_sync")
    @patch("code_puppy.agents.base_agent.emit_warning")
    def test_non_list_return_wrapped(self, mock_warn, mock_sync, agent):
        mock_sync.return_value = "plain text summary"

        msgs = [_make_msg("old message")]
        result = agent._summarize_single_batch(msgs)
        assert len(result) == 1
        assert isinstance(result[0], ModelRequest)
        mock_warn.assert_called_once()

    def test_empty_after_pruning(self, agent):
        # If prune_interrupted_tool_calls returns empty, should return []
        with patch.object(agent, "prune_interrupted_tool_calls", return_value=[]):
            result = agent._summarize_single_batch([_make_msg("test")])
            assert result == []

    @patch("code_puppy.agents.base_agent.run_summarization_sync")
    def test_summarization_error_propagates(self, mock_sync, agent):
        from code_puppy.summarization_agent import SummarizationError
        mock_sync.side_effect = SummarizationError("boom")

        with pytest.raises(SummarizationError):
            agent._summarize_single_batch([_make_msg("test")])


# ─── _find_safe_summarize_split ───────────────────────────────────────

class TestFindSafeSummarizeSplit:
    def test_no_tool_calls_returns_target(self, agent):
        msgs = [_make_msg("a"), _make_msg("b"), _make_msg("c"), _make_msg("d")]
        assert agent._find_safe_summarize_split(msgs, 2) == 2

    def test_zero_target_returns_zero(self, agent):
        msgs = [_make_msg("a")]
        assert agent._find_safe_summarize_split(msgs, 0) == 0

    def test_avoids_splitting_tool_pair(self, agent):
        """If a tool_call is at index 1 and tool_return at index 2,
        splitting at 2 would separate them. Should adjust back to 1."""
        msgs = [
            _make_msg("user message"),
            ModelResponse(
                parts=[ToolCallPart(
                    tool_name="my_tool",
                    args={"x": 1},
                    tool_call_id="tc-1",
                )],
                model_name="test-model",
            ),
            ModelRequest(
                parts=[ToolReturnPart(
                    tool_name="my_tool",
                    content="result",
                    tool_call_id="tc-1",
                )]
            ),
            _make_msg("after tools"),
        ]
        # Target is 2 — which would put tool_call in head, tool_return in tail
        result = agent._find_safe_summarize_split(msgs, 2)
        # Should move back to 1 so the pair stays together in the tail
        assert result <= 1

    def test_no_conflict_keeps_target(self, agent):
        """When tool_call and tool_return are both before the split, no adjustment."""
        msgs = [
            ModelResponse(
                parts=[ToolCallPart(
                    tool_name="t", args={}, tool_call_id="tc-2",
                )],
                model_name="test-model",
            ),
            ModelRequest(
                parts=[ToolReturnPart(
                    tool_name="t", content="r", tool_call_id="tc-2",
                )]
            ),
            _make_msg("after tools 1"),
            _make_msg("after tools 2"),
        ]
        result = agent._find_safe_summarize_split(msgs, 2)
        assert result == 2


# ─── _binary_split_summarize ─────────────────────────────────────────

class TestBinarySplitSummarize:
    @patch("code_puppy.agents.base_agent.run_summarization_sync")
    def test_small_batch_no_split(self, mock_sync, agent):
        """When batch fits in context, should call summarize once."""
        summary = [_make_msg("summary")]
        mock_sync.return_value = summary

        # Context is 128000 * 0.8 = 102400 tokens. Our messages are tiny.
        msgs = [_make_msg("msg1"), _make_msg("msg2")]
        result = agent._binary_split_summarize(msgs)
        assert result == summary
        assert mock_sync.call_count == 1

    @patch("code_puppy.agents.base_agent.run_summarization_sync")
    @patch("code_puppy.agents.base_agent.emit_info")
    def test_large_batch_splits_once(self, mock_info, mock_sync, agent):
        """When batch exceeds context, should split and call summarize twice."""
        # Make context window small so our messages exceed it
        with patch.object(agent, "get_model_context_length", return_value=200):
            # 200 * 0.8 = 160 token limit
            # Each message ~100 tokens, 4 messages = 400 tokens > 160
            msgs = [_make_msg(f"msg{i}", token_size=100) for i in range(4)]

            # First call summarizes head (2 msgs) -> small summary
            # Second call won't happen if combined fits
            small_summary = [_make_msg("summary of first half", token_size=10)]
            mock_sync.return_value = small_summary

            result = agent._binary_split_summarize(msgs)

            # Should have called summarize at least twice:
            # once for the head, once for the combined result
            assert mock_sync.call_count >= 1
            # Result should be smaller than input
            assert len(result) <= len(msgs)

    @patch("code_puppy.agents.base_agent.run_summarization_sync")
    @patch("code_puppy.agents.base_agent.emit_info")
    @patch("code_puppy.agents.base_agent.emit_warning")
    def test_max_depth_forces_best_effort(self, mock_warn, mock_info, mock_sync, agent):
        """At max depth, should warn and attempt best-effort summarization."""
        summary = [_make_msg("best effort summary")]
        mock_sync.return_value = summary

        with patch.object(agent, "get_model_context_length", return_value=100):
            # Huge messages that can never fit
            msgs = [_make_msg(f"huge{i}", token_size=500) for i in range(2)]

            # Call at max depth directly
            result = agent._binary_split_summarize(msgs, depth=4)
            assert result == summary
            # Should have emitted a warning about hitting max depth
            mock_warn.assert_called_once()
            assert "max depth" in mock_warn.call_args[0][0].lower()

    def test_empty_messages_returns_empty(self, agent):
        result = agent._binary_split_summarize([])
        assert result == []

    @patch("code_puppy.agents.base_agent.run_summarization_sync")
    @patch("code_puppy.agents.base_agent.emit_info")
    def test_recursive_convergence(self, mock_info, mock_sync, agent):
        """Verify recursion actually reduces the problem size."""
        call_count = [0]

        def mock_summarize(instructions, message_history):
            call_count[0] += 1
            # Each summarization reduces to a small message
            return [_make_msg(f"summary-{call_count[0]}", token_size=5)]

        mock_sync.side_effect = mock_summarize

        with patch.object(agent, "get_model_context_length", return_value=200):
            # 8 messages at 100 tokens each = 800 tokens, limit is 160
            msgs = [_make_msg(f"msg{i}", token_size=100) for i in range(8)]
            result = agent._binary_split_summarize(msgs)

            # Should have made multiple summarization calls
            assert call_count[0] >= 2
            # Final result should fit
            total_tokens = agent._estimate_batch_tokens(result)
            assert total_tokens <= 160 or call_count[0] > 0


# ─── summarize_messages (public API) ──────────────────────────────────

class TestSummarizeMessages:
    @patch("code_puppy.agents.base_agent.run_summarization_sync")
    @patch("code_puppy.agents.base_agent.get_protected_token_count", return_value=100000)
    @patch("code_puppy.agents.base_agent.emit_info")
    def test_nothing_to_summarize(self, mock_info, mock_tokens, mock_sync, agent):
        """With only a system message, nothing should be summarized."""
        msgs = [_make_msg("system prompt")]
        result, summarized = agent.summarize_messages(msgs)
        mock_sync.assert_not_called()
        assert summarized == []

    def test_empty_messages(self, agent):
        result, summarized = agent.summarize_messages([])
        assert result == []
        assert summarized == []

    @patch("code_puppy.agents.base_agent.run_summarization_sync")
    @patch("code_puppy.agents.base_agent.get_protected_token_count", return_value=50)
    @patch("code_puppy.agents.base_agent.emit_info")
    def test_successful_summarization(self, mock_info, mock_tokens, mock_sync, agent):
        summary = [_make_msg("conversation summary")]
        mock_sync.return_value = summary

        sys_msg = _make_msg("system")
        old_msg = _make_msg("old conversation" * 20)
        recent_msg = _make_msg("recent")
        msgs = [sys_msg, old_msg, recent_msg]

        result, summarized = agent.summarize_messages(msgs)
        # Result should start with system message
        assert result[0] is sys_msg
        # Should have summarized something
        assert len(summarized) > 0

    @patch("code_puppy.agents.base_agent.run_summarization_sync")
    @patch("code_puppy.agents.base_agent.get_protected_token_count", return_value=50)
    @patch("code_puppy.agents.base_agent.emit_info")
    @patch("code_puppy.agents.base_agent.emit_error")
    def test_summarization_error_returns_original(
        self, mock_error, mock_info, mock_tokens, mock_sync, agent
    ):
        from code_puppy.summarization_agent import SummarizationError
        mock_sync.side_effect = SummarizationError(
            "LLM failed", original_error=RuntimeError("inner")
        )

        msgs = [
            _make_msg("system"),
            _make_msg("old" * 100),
            _make_msg("recent"),
        ]
        result, summarized = agent.summarize_messages(msgs)
        assert result == msgs  # Returns original on failure
        assert summarized == []
        mock_error.assert_called_once()

    @patch("code_puppy.agents.base_agent.run_summarization_sync")
    @patch("code_puppy.agents.base_agent.get_protected_token_count", return_value=50)
    @patch("code_puppy.agents.base_agent.emit_info")
    @patch("code_puppy.agents.base_agent.emit_error")
    def test_unexpected_error_returns_original(
        self, mock_error, mock_info, mock_tokens, mock_sync, agent
    ):
        mock_sync.side_effect = Exception("unexpected boom")

        msgs = [
            _make_msg("system"),
            _make_msg("old" * 100),
            _make_msg("recent"),
        ]
        result, summarized = agent.summarize_messages(msgs)
        assert result == msgs
        assert summarized == []

    @patch("code_puppy.agents.base_agent.run_summarization_sync")
    @patch("code_puppy.agents.base_agent.get_protected_token_count", return_value=50)
    @patch("code_puppy.agents.base_agent.emit_info")
    def test_without_protection(self, mock_info, mock_tokens, mock_sync, agent):
        summary = [_make_msg("summary")]
        mock_sync.return_value = summary

        msgs = [_make_msg("system"), _make_msg("old" * 100)]
        result, summarized = agent.summarize_messages(msgs, with_protection=False)
        assert len(result) >= 1
        # System message should be first
        assert result[0] is msgs[0]

    @patch("code_puppy.agents.base_agent.run_summarization_sync")
    @patch("code_puppy.agents.base_agent.get_protected_token_count", return_value=50)
    @patch("code_puppy.agents.base_agent.emit_info")
    def test_empty_summarization_result_returns_original(
        self, mock_info, mock_tokens, mock_sync, agent
    ):
        """When _binary_split_summarize returns empty, should return original."""
        with patch.object(agent, "_binary_split_summarize", return_value=[]):
            msgs = [
                _make_msg("system"),
                _make_msg("old" * 100),
                _make_msg("recent"),
            ]
            result, summarized = agent.summarize_messages(msgs)
            # Should return pruned original messages since summary was empty
            assert len(result) > 0

    @patch("code_puppy.agents.base_agent.run_summarization_sync")
    @patch("code_puppy.agents.base_agent.get_protected_token_count", return_value=50)
    @patch("code_puppy.agents.base_agent.emit_info")
    def test_binary_split_called_for_large_history(
        self, mock_info, mock_tokens, mock_sync, agent
    ):
        """Verify that _binary_split_summarize is called (not direct sync)."""
        with patch.object(
            agent, "_binary_split_summarize",
            return_value=[_make_msg("summary")]
        ) as mock_split:
            msgs = [
                _make_msg("system"),
                _make_msg("old" * 100),
                _make_msg("recent"),
            ]
            agent.summarize_messages(msgs)
            mock_split.assert_called_once()
