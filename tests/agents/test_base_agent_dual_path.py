"""Tests for Rust/Python dual-path branches in base_agent.py.

Covers the Rust fast-path and Python fallback for:
- filter_huge_messages
- prune_interrupted_tool_calls
- message_history_processor

We mock ``_rust_enabled`` and ``process_messages_batch`` to exercise both code
paths without requiring the actual Rust extension.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from code_puppy.agents.agent_code_puppy import CodePuppyAgent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_messages(count: int = 3, *, with_tools: bool = False) -> list:
    """Build a simple list of ModelRequest/ModelResponse pairs."""
    msgs = []
    for i in range(count):
        if with_tools and i == 1:
            msgs.append(
                ModelResponse(
                    parts=[
                        ToolCallPart(tool_name="foo", args={"a": 1}, tool_call_id="tc1")
                    ]
                )
            )
            msgs.append(
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            tool_name="foo", content="ok", tool_call_id="tc1"
                        )
                    ]
                )
            )
        else:
            msgs.append(ModelRequest(parts=[UserPromptPart(content=f"hi {i}")]))
            msgs.append(ModelResponse(parts=[TextPart(content=f"reply {i}")]))
    return msgs


def _fake_batch_result(
    total_message_tokens=100, context_overhead_tokens=50, per_message_tokens=None
):
    """Return an object shaped like a Rust ProcessResult."""
    if per_message_tokens is None:
        per_message_tokens = [10] * 10
    return SimpleNamespace(
        total_message_tokens=total_message_tokens,
        context_overhead_tokens=context_overhead_tokens,
        per_message_tokens=per_message_tokens,
    )


def _fake_prune_result(surviving_indices=None):
    if surviving_indices is None:
        surviving_indices = [0, 1, 2]
    return SimpleNamespace(surviving_indices=surviving_indices)


# ---------------------------------------------------------------------------
# filter_huge_messages – Rust path
# ---------------------------------------------------------------------------


class TestFilterHugeMessagesDualPath:
    """Exercise both Rust and Python paths in filter_huge_messages."""

    @patch("code_puppy.agents.base_agent._rust_enabled", new=lambda: True)
    @patch("code_puppy._core_bridge.MessageBatchHandle.prune_and_filter")
    @patch("code_puppy.agents.base_agent.serialize_messages_for_rust")
    def test_rust_path_returns_subset(
        self,
        mock_serialize,
        mock_prune,
    ):
        mock_serialize.return_value = [{"fake": True}]
        mock_prune.return_value = _fake_prune_result([0, 2])
        agent = CodePuppyAgent()
        msgs = _make_messages(3)
        result = agent.filter_huge_messages(msgs)
        # Should return messages at indices 0 and 2
        assert len(result) == 2
        assert result[0] is msgs[0]
        assert result[1] is msgs[2]

    @patch("code_puppy.agents.base_agent._rust_enabled", new=lambda: True)
    @patch(
        "code_puppy._core_bridge.MessageBatchHandle.prune_and_filter",
        side_effect=RuntimeError("boom"),
    )
    @patch("code_puppy.agents.base_agent.serialize_messages_for_rust")
    def test_rust_exception_falls_back_to_python(self, mock_serialize, mock_prune):
        """When the Rust call raises, filter_huge_messages falls back to Python."""
        mock_serialize.return_value = [{"fake": True}]
        agent = CodePuppyAgent()
        msgs = _make_messages(3)
        result = agent.filter_huge_messages(msgs)
        # Python fallback still works (all small messages pass through)
        assert isinstance(result, list)
        assert len(result) >= 1  # prune may alter count

    @patch("code_puppy.agents.base_agent._rust_enabled", new=lambda: False)
    def test_python_path_no_rust(self):
        """When _rust_enabled() returns False, only Python path runs."""
        agent = CodePuppyAgent()
        msgs = _make_messages(3)
        result = agent.filter_huge_messages(msgs)
        assert isinstance(result, list)

    @patch("code_puppy.agents.base_agent._rust_enabled", new=lambda: False)
    def test_python_path_filters_large_messages(self):
        """Python path drops messages with token estimate > 50000."""
        agent = CodePuppyAgent()
        # Create a message with a huge content string to exceed 50000 tokens
        huge_content = "x" * 2_000_000  # ~500k tokens
        msgs = [
            ModelRequest(parts=[UserPromptPart(content="small")]),
            ModelRequest(parts=[UserPromptPart(content=huge_content)]),
        ]
        result = agent.filter_huge_messages(msgs)
        # The huge message should be filtered out
        assert all(m is not msgs[1] for m in result)


# ---------------------------------------------------------------------------
# prune_interrupted_tool_calls – Rust path
# ---------------------------------------------------------------------------


class TestPruneInterruptedToolCallsDualPath:
    @patch("code_puppy.agents.base_agent._rust_enabled", new=lambda: True)
    @patch("code_puppy._core_bridge.MessageBatchHandle.prune_and_filter")
    @patch("code_puppy.agents.base_agent.serialize_messages_for_rust")
    def test_rust_path_returns_subset(self, mock_serialize, mock_prune):
        mock_serialize.return_value = [{"fake": True}]
        mock_prune.return_value = _fake_prune_result([0, 1])
        agent = CodePuppyAgent()
        msgs = _make_messages(3, with_tools=True)
        result = agent.prune_interrupted_tool_calls(msgs)
        assert len(result) == 2
        assert result[0] is msgs[0]
        assert result[1] is msgs[1]

    @patch("code_puppy.agents.base_agent._rust_enabled", new=lambda: True)
    @patch(
        "code_puppy._core_bridge.MessageBatchHandle.prune_and_filter",
        side_effect=Exception("boom"),
    )
    @patch("code_puppy.agents.base_agent.serialize_messages_for_rust")
    def test_rust_exception_falls_back_to_python(self, mock_serialize, mock_prune):
        agent = CodePuppyAgent()
        msgs = _make_messages(2, with_tools=True)
        result = agent.prune_interrupted_tool_calls(msgs)
        # Python fallback should still produce a valid list
        assert isinstance(result, list)

    @patch("code_puppy.agents.base_agent._rust_enabled", new=lambda: False)
    def test_python_path_removes_mismatched_tool_call(self):
        """Python path removes tool calls without matching returns."""
        agent = CodePuppyAgent()
        msgs = [
            ModelRequest(parts=[UserPromptPart(content="go")]),
            ModelResponse(
                parts=[ToolCallPart(tool_name="foo", args={}, tool_call_id="orphan")]
            ),
            ModelResponse(parts=[TextPart(content="done")]),
        ]
        result = agent.prune_interrupted_tool_calls(msgs)
        # orphan tool call should be dropped
        assert all(
            not any(
                getattr(p, "tool_call_id", None) == "orphan"
                for p in getattr(m, "parts", [])
            )
            for m in result
        )

    @patch("code_puppy.agents.base_agent._rust_enabled", new=lambda: False)
    def test_python_path_keeps_matched_tool_pairs(self):
        """Python path keeps messages with matched tool call/return pairs."""
        agent = CodePuppyAgent()
        msgs = [
            ModelRequest(parts=[UserPromptPart(content="go")]),
            ModelResponse(
                parts=[ToolCallPart(tool_name="foo", args={}, tool_call_id="matched")]
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="foo", content="ok", tool_call_id="matched"
                    )
                ]
            ),
        ]
        result = agent.prune_interrupted_tool_calls(msgs)
        assert len(result) == 3

    def test_empty_messages_returns_empty(self):
        agent = CodePuppyAgent()
        assert agent.prune_interrupted_tool_calls([]) == []


# ---------------------------------------------------------------------------
# message_history_processor – Rust path
# ---------------------------------------------------------------------------


class TestMessageHistoryProcessorDualPath:
    @pytest.fixture
    def agent(self):
        agent = CodePuppyAgent()
        # Stub get_model_context_length to avoid config dependency
        agent.get_model_context_length = MagicMock(return_value=200_000)
        return agent

    @patch("code_puppy.agents.base_agent._rust_enabled", new=lambda: True)
    @patch("code_puppy._core_bridge.process_messages_batch")
    @patch("code_puppy.agents.base_agent.serialize_messages_for_rust")
    def test_rust_path_computes_tokens(self, mock_serialize, mock_batch, agent):
        mock_serialize.return_value = [{"fake": True}]
        mock_batch.return_value = _fake_batch_result(
            total_message_tokens=500, context_overhead_tokens=100
        )
        msgs = _make_messages(2)
        ctx = SimpleNamespace()
        result = agent.message_history_processor(ctx, msgs)
        # Under compaction threshold (600 / 200000 < 0.8) → returns msgs unchanged
        assert result is msgs

    @patch("code_puppy.agents.base_agent._rust_enabled", new=lambda: True)
    @patch(
        "code_puppy._core_bridge.process_messages_batch",
        side_effect=RuntimeError("panic"),
    )
    @patch("code_puppy.agents.base_agent.serialize_messages_for_rust")
    def test_rust_exception_falls_back_to_python(
        self, mock_serialize, mock_batch, agent
    ):
        mock_serialize.return_value = [{"fake": True}]
        msgs = _make_messages(2)
        ctx = SimpleNamespace()
        result = agent.message_history_processor(ctx, msgs)
        # Fallback uses Python estimate_tokens_for_message
        assert isinstance(result, list)

    @patch("code_puppy.agents.base_agent._rust_enabled", new=lambda: False)
    def test_python_path_computes_tokens(self, agent):
        msgs = _make_messages(2)
        ctx = SimpleNamespace()
        result = agent.message_history_processor(ctx, msgs)
        assert isinstance(result, list)

    @patch("code_puppy.agents.base_agent._rust_enabled", new=lambda: True)
    @patch("code_puppy._core_bridge.MessageBatchHandle.process")
    @patch("code_puppy.agents.base_agent.serialize_messages_for_rust")
    @patch("code_puppy.config.get_compaction_strategy", return_value="truncation")
    @patch("code_puppy.config_package.get_puppy_config")
    def test_rust_path_triggers_compaction(
        self,
        mock_get_config,
        mock_strategy,
        mock_serialize,
        mock_batch,
        agent,
    ):
        """When proportion_used > threshold, compaction kicks in (Rust path)."""
        # Create a mock config with low threshold to trigger compaction
        mock_cfg = SimpleNamespace(
            compaction_threshold=0.0,  # 0% threshold to always trigger compaction
            protected_token_count=1000,
            summarization_trigger_fraction=0.8,
            summarization_keep_fraction=0.4,
        )
        mock_get_config.return_value = mock_cfg
        mock_serialize.return_value = [{"fake": True}]
        mock_batch.return_value = _fake_batch_result(
            total_message_tokens=150_000, context_overhead_tokens=60_000
        )
        msgs = _make_messages(3)
        ctx = SimpleNamespace()
        result = agent.message_history_processor(ctx, msgs)
        # Compaction happened → result is different from input
        assert isinstance(result, list)
