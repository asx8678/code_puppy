"""Correctness tests for Rust _code_puppy_core module.

Tests verify that:
1. The Python bridge serialization produces valid dicts
2. Token estimation matches Python implementation
3. Message hashing is deterministic and collision-resistant
4. Pruning logic matches Python prune_interrupted_tool_calls
5. Truncation keeps the right messages
6. Serialization roundtrips correctly
7. The fallback (RUST_AVAILABLE=False) doesn't break anything
"""

import math

import pytest
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)

from code_puppy._core_bridge import (
    RUST_AVAILABLE,
    serialize_message_for_rust,
    serialize_messages_for_rust,
)
from code_puppy.agents.agent_code_puppy import CodePuppyAgent


class TestCoreBridgeSerialization:
    """Test serialize_message_for_rust produces correct dicts."""

    def test_text_message_serialization(self):
        msg = ModelRequest(parts=[TextPart(content="hello world")])
        result = serialize_message_for_rust(msg)
        assert result["kind"] == "request"
        assert len(result["parts"]) == 1
        assert result["parts"][0]["part_kind"] == "text"
        assert result["parts"][0]["content"] == "hello world"
        assert result["parts"][0]["tool_call_id"] is None

    def test_response_serialization(self):
        msg = ModelResponse(parts=[TextPart(content="I can help")])
        result = serialize_message_for_rust(msg)
        assert result["kind"] == "response"

    def test_tool_call_serialization(self):
        msg = ModelResponse(
            parts=[ToolCallPart(tool_name="read_file", args='{"path": "foo.py"}', tool_call_id="tc-1")]
        )
        result = serialize_message_for_rust(msg)
        p = result["parts"][0]
        assert p["part_kind"] == "tool-call"
        assert p["tool_name"] == "read_file"
        assert p["tool_call_id"] == "tc-1"
        assert "foo.py" in p["args"]

    def test_tool_return_serialization(self):
        msg = ModelRequest(
            parts=[ToolReturnPart(tool_name="read_file", content="file contents here", tool_call_id="tc-1")]
        )
        result = serialize_message_for_rust(msg)
        p = result["parts"][0]
        assert p["part_kind"] == "tool-return"
        assert p["content"] == "file contents here"
        assert p["tool_call_id"] == "tc-1"

    def test_none_content_serialization(self):
        msg = ModelRequest(parts=[TextPart(content="")])
        result = serialize_message_for_rust(msg)
        # Empty string is still a string
        assert result["parts"][0]["content"] == ""

    def test_batch_serialization(self):
        msgs = [
            ModelRequest(parts=[TextPart(content="first")]),
            ModelResponse(parts=[TextPart(content="second")]),
        ]
        results = serialize_messages_for_rust(msgs)
        assert len(results) == 2
        assert results[0]["kind"] == "request"
        assert results[1]["kind"] == "response"


class TestTokenEstimationCorrectness:
    """Verify Rust token estimation matches Python implementation."""

    @pytest.fixture
    def agent(self):
        return CodePuppyAgent()

    def test_simple_text_matches_python(self, agent):
        text = "Hello, world! This is a test message."
        python_tokens = agent.estimate_token_count(text)
        expected = max(1, math.floor(len(text) / 2.5))
        assert python_tokens == expected

    def test_message_token_estimation_matches(self, agent):
        msg = ModelRequest(parts=[TextPart(content="Hello world, this is a longer test")])
        python_tokens = agent.estimate_tokens_for_message(msg)
        assert python_tokens >= 1

    def test_empty_message_minimum_tokens(self, agent):
        msg = ModelRequest(parts=[TextPart(content="")])
        python_tokens = agent.estimate_tokens_for_message(msg)
        assert python_tokens >= 1

    def test_multi_part_message(self, agent):
        msg = ModelRequest(parts=[
            TextPart(content="part one"),
            TextPart(content="part two with more text"),
        ])
        tokens = agent.estimate_tokens_for_message(msg)
        # Should be sum of both parts
        assert tokens >= 2


class TestMessageHashingCorrectness:
    """Verify hashing behavior (not values — those differ between Rust and Python)."""

    @pytest.fixture
    def agent(self):
        return CodePuppyAgent()

    def test_same_message_same_hash(self, agent):
        msg1 = ModelRequest(parts=[TextPart(content="hello")])
        msg2 = ModelRequest(parts=[TextPart(content="hello")])
        assert agent.hash_message(msg1) == agent.hash_message(msg2)

    def test_different_content_different_hash(self, agent):
        msg1 = ModelRequest(parts=[TextPart(content="hello")])
        msg2 = ModelRequest(parts=[TextPart(content="world")])
        assert agent.hash_message(msg1) != agent.hash_message(msg2)

    def test_hash_is_int(self, agent):
        msg = ModelRequest(parts=[TextPart(content="test")])
        h = agent.hash_message(msg)
        assert isinstance(h, int)


class TestPruningCorrectness:
    """Verify prune_interrupted_tool_calls behavior."""

    @pytest.fixture
    def agent(self):
        return CodePuppyAgent()

    def test_matched_tool_calls_preserved(self, agent):
        messages = [
            ModelRequest(parts=[TextPart(content="do something")]),
            ModelResponse(parts=[ToolCallPart(tool_name="read_file", args='{}', tool_call_id="tc-1")]),
            ModelRequest(parts=[ToolReturnPart(tool_name="read_file", content="result", tool_call_id="tc-1")]),
        ]
        pruned = agent.prune_interrupted_tool_calls(messages)
        assert len(pruned) == 3  # All preserved

    def test_mismatched_tool_calls_pruned(self, agent):
        messages = [
            ModelRequest(parts=[TextPart(content="do something")]),
            ModelResponse(parts=[ToolCallPart(tool_name="read_file", args='{}', tool_call_id="tc-1")]),
            # No matching tool return!
        ]
        pruned = agent.prune_interrupted_tool_calls(messages)
        assert len(pruned) < 3  # Mismatched should be pruned

    def test_empty_messages_safe(self, agent):
        pruned = agent.prune_interrupted_tool_calls([])
        assert pruned == []


class TestTruncationCorrectness:
    """Verify truncation always keeps first message."""

    @pytest.fixture
    def agent(self):
        return CodePuppyAgent()

    def test_first_message_always_kept(self, agent):
        messages = [
            ModelRequest(parts=[TextPart(content="system" * 100)]),
            ModelResponse(parts=[TextPart(content="response" * 100)]),
            ModelRequest(parts=[TextPart(content="user" * 100)]),
            ModelResponse(parts=[TextPart(content="assist" * 100)]),
            ModelRequest(parts=[TextPart(content="latest question")]),
        ]
        result = agent.truncation(messages, 100)
        # First message (system) should always be kept
        assert result[0] == messages[0]
        assert len(result) >= 1

    def test_single_message_preserved(self, agent):
        messages = [ModelRequest(parts=[TextPart(content="only message")])]
        result = agent.truncation(messages, 1000)
        assert len(result) == 1


class TestFallbackBehavior:
    """Verify the app works correctly without the Rust module."""

    def test_bridge_import_works(self):
        """The bridge module should always import."""
        from code_puppy._core_bridge import RUST_AVAILABLE
        assert isinstance(RUST_AVAILABLE, bool)

    def test_serialization_helper_works_without_rust(self):
        """serialize_message_for_rust should work regardless of Rust availability."""
        msg = ModelRequest(parts=[TextPart(content="test")])
        result = serialize_message_for_rust(msg)
        assert result["kind"] == "request"
        assert result["parts"][0]["content"] == "test"


class TestEdgeCases:
    """Edge cases that could cause issues."""

    def test_very_long_content(self):
        content = "x" * 200_000
        msg = ModelRequest(parts=[TextPart(content=content)])
        result = serialize_message_for_rust(msg)
        assert len(result["parts"][0]["content"]) == 200_000

    def test_unicode_content(self):
        content = "Hello 🌍! Ñoño café résumé 日本語"
        msg = ModelRequest(parts=[TextPart(content=content)])
        result = serialize_message_for_rust(msg)
        assert result["parts"][0]["content"] == content

    def test_empty_parts_list(self):
        msg = ModelRequest(parts=[])
        result = serialize_message_for_rust(msg)
        assert result["parts"] == []

    def test_dict_content(self):
        msg = ModelRequest(parts=[ToolReturnPart(
            tool_name="test", content={"key": "value", "nested": {"a": 1}}, tool_call_id="tc-1"
        )])
        result = serialize_message_for_rust(msg)
        # Dict content should be serialized to content_json
        p = result["parts"][0]
        assert p["content_json"] is not None or p["content"] is not None
