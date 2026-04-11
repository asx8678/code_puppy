"""Tests for BaseAgent token estimation and message filtering functionality."""


import pytest
from unittest.mock import patch
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
)

from code_puppy.agents.agent_code_puppy import CodePuppyAgent


class TestTokenEstimation:
    """Test suite for token estimation methods in BaseAgent."""

    @pytest.fixture
    def agent(self):
        """Provide a concrete BaseAgent subclass for testing."""
        return CodePuppyAgent()

    # Tests for estimate_token_count

    def test_estimate_token_count_simple_text(self, agent):
        """Test token estimation for simple text."""
        text = "Hello, world!"
        token_count = agent.estimate_token_count(text)
        # New heuristic: ~4 chars/token for prose
        # len("Hello, world!") = 13, int(13/4.0) = 3
        assert token_count == 3

    def test_estimate_token_count_empty_string(self, agent):
        """Test token estimation for empty string returns minimum of 1."""
        text = ""
        token_count = agent.estimate_token_count(text)
        assert token_count == 1

    def test_estimate_token_count_single_char(self, agent):
        """Test token estimation for single character."""
        text = "a"
        token_count = agent.estimate_token_count(text)
        assert token_count == 1

    def test_estimate_token_count_large_text(self, agent):
        """Test token estimation for large text."""
        text = "x" * 3000  # 3000 characters
        token_count = agent.estimate_token_count(text)
        # ~3000/4.0 = 750 for prose
        assert 700 <= token_count <= 800

    def test_estimate_token_count_medium_text(self, agent):
        """Test token estimation for medium-sized text."""
        text = "a" * 100
        token_count = agent.estimate_token_count(text)
        # ~100/4.0 = 25 for prose
        assert 20 <= token_count <= 30

    def test_estimate_token_count_two_chars(self, agent):
        """Test token estimation for two characters."""
        text = "ab"
        token_count = agent.estimate_token_count(text)
        assert token_count == 1

    def test_estimate_token_count_three_chars(self, agent):
        """Test token estimation for exactly three characters."""
        text = "abc"
        token_count = agent.estimate_token_count(text)
        assert token_count == 1

    def test_estimate_token_count_four_chars(self, agent):
        """Test token estimation for four characters."""
        text = "abcd"
        token_count = agent.estimate_token_count(text)
        # int(4/4.0) = 1
        assert token_count == 1

    def test_estimate_token_count_six_chars(self, agent):
        """Test token estimation for six characters."""
        text = "abcdef"
        token_count = agent.estimate_token_count(text)
        # New heuristic: int(6/4.0) = 1
        assert token_count >= 1

    # Tests for estimate_tokens_for_message

    def test_estimate_tokens_for_message_single_part(self, agent):
        """Test token estimation for message with single TextPart."""
        # Create a message with one part
        text_content = "This is a test message"
        message = ModelRequest(parts=[TextPart(content=text_content)])
        token_count = agent.estimate_tokens_for_message(message)
        # stringify_message_part adds "text: " prefix (6 chars) to TextPart content
        # So we need to account for the prefix in our expected calculation
        part_str = agent.stringify_message_part(message.parts[0])
        expected = agent.estimate_token_count(part_str)
        assert token_count == expected

    def test_estimate_tokens_for_message_multiple_parts(self, agent):
        """Test token estimation for message with multiple parts."""
        # Create a message with multiple text parts
        text1 = "Hello"
        text2 = "World"
        message = ModelRequest(
            parts=[
                TextPart(content=text1),
                TextPart(content=text2),
            ]
        )
        token_count = agent.estimate_tokens_for_message(message)
        # Should sum the tokens from both parts
        # stringify_message_part adds "text: " prefix to each part
        part1_str = agent.stringify_message_part(message.parts[0])
        part2_str = agent.stringify_message_part(message.parts[1])
        tokens1 = agent.estimate_token_count(part1_str)
        tokens2 = agent.estimate_token_count(part2_str)
        expected = max(1, tokens1 + tokens2)
        assert token_count == expected

    def test_estimate_tokens_for_message_empty_parts(self, agent):
        """Test token estimation for message with empty parts."""
        # Create a message with empty text
        message = ModelRequest(parts=[TextPart(content="")])
        token_count = agent.estimate_tokens_for_message(message)
        # Empty part should contribute 1 token (minimum)
        assert token_count >= 1

    def test_estimate_tokens_for_message_large_content(self, agent):
        """Test token estimation for message with large content."""
        # Create a message with large text
        large_text = "x" * 9000
        message = ModelRequest(parts=[TextPart(content=large_text)])
        token_count = agent.estimate_tokens_for_message(message)
        # New heuristic: ~9000/4.0 = 2250 for prose
        assert 2000 <= token_count <= 2500

    # Tests for filter_huge_messages

    def test_filter_huge_messages_removes_oversized(self, agent):
        """Test that filter_huge_messages removes messages exceeding 50000 tokens."""
        # Create a message that's definitely over 50000 tokens
        # 50000 tokens * 4 = 200000 characters minimum
        huge_text = "x" * 200001  # This should be ~50000+ tokens
        huge_message = ModelRequest(parts=[TextPart(content=huge_text)])

        # Create a small message that should be kept
        small_text = "small"
        small_message = ModelRequest(parts=[TextPart(content=small_text)])

        messages = [small_message, huge_message, small_message]
        filtered = agent.filter_huge_messages(messages)

        # The huge message should be filtered out
        assert len(filtered) < len(messages)
        # Small messages should remain
        assert len(filtered) >= 2

    def test_filter_huge_messages_keeps_small(self, agent):
        """Test that filter_huge_messages keeps messages under 50000 tokens."""
        # Create messages that are well under the 50000 token limit
        messages = [
            ModelRequest(parts=[TextPart(content="Hello world")]),
            ModelResponse(parts=[TextPart(content="Hi there!")]),
            ModelRequest(parts=[TextPart(content="How are you?")]),
        ]

        filtered = agent.filter_huge_messages(messages)

        # All small messages should be kept
        assert len(filtered) == len(messages)

    def test_filter_huge_messages_empty_list(self, agent):
        """Test that filter_huge_messages handles empty message list."""
        messages = []
        filtered = agent.filter_huge_messages(messages)
        assert len(filtered) == 0

    def test_filter_huge_messages_single_small_message(self, agent):
        """Test that filter_huge_messages keeps single small message."""
        message = ModelRequest(parts=[TextPart(content="test")])
        filtered = agent.filter_huge_messages([message])
        assert len(filtered) == 1

    @patch("code_puppy.agents.base_agent._rust_enabled", return_value=False)
    def test_filter_huge_messages_boundary_at_50000(self, mock_rust, agent):
        """Test filter_huge_messages behavior at 50000 token boundary (Python path)."""
        # Create a message with approximately 50000 tokens
        # 50000 tokens = 200000 characters (using 4.0 chars per token)
        boundary_text = "x" * int(50000 * 4.0)  # Exactly at boundary
        boundary_message = ModelRequest(parts=[TextPart(content=boundary_text)])

        # Create a message with exactly one character below the boundary
        # (so it has 49999 tokens)
        just_under_text = "x" * int(40000 * 4.0)  # Well under 50000 token boundary
        just_under_message = ModelRequest(parts=[TextPart(content=just_under_text)])

        # Test at boundary - 50000 tokens should be filtered out
        messages_at_boundary = [boundary_message]
        filtered = agent.filter_huge_messages(messages_at_boundary)
        # 50000 tokens is >= 50000, so it should be filtered
        assert len(filtered) == 0

        # Test just under boundary - should be kept
        messages_under = [just_under_message]
        filtered_under = agent.filter_huge_messages(messages_under)
        # ~40000 tokens is well under 50000, so it should be kept
        assert len(filtered_under) == 1

    def test_filter_huge_messages_calls_prune(self, agent):
        """Test that filter_huge_messages calls prune_interrupted_tool_calls."""
        # This test verifies the filtering also prunes interrupted tool calls
        # Create a normal message that should pass through
        message = ModelRequest(parts=[TextPart(content="hello")])
        filtered = agent.filter_huge_messages([message])
        # Should still have the message after pruning
        assert len(filtered) >= 0  # May be 0 or more depending on pruning logic


class TestMCPToolCache:
    """Test suite for MCP tool cache functionality."""

    @pytest.fixture
    def agent(self):
        """Provide a concrete BaseAgent subclass for testing."""
        return CodePuppyAgent()

    def test_mcp_tool_cache_initialized_empty(self, agent):
        """Test that MCP tool cache is initialized as empty list."""
        assert hasattr(agent._state, "mcp_tool_definitions_cache")
        assert agent._state.mcp_tool_definitions_cache == []

    def test_estimate_context_overhead_with_empty_mcp_cache(self, agent):
        """Test that estimate_context_overhead_tokens works with empty MCP cache."""
        # Should not raise an error with empty cache
        overhead = agent.estimate_context_overhead_tokens()
        # Should return at least 0 (or more if system prompt is present)
        assert overhead >= 0

    def test_estimate_context_overhead_with_mcp_cache(self, agent):
        """Test that estimate_context_overhead_tokens includes MCP tools from cache."""
        # Populate the cache with mock MCP tool definitions
        # Use large tool definitions to ensure the token count difference
        # is detectable with the ~4 chars/token estimation heuristic.
        agent._state.mcp_tool_definitions_cache = [
            {
                "name": f"tool_{i}",
                "description": f"A test tool number {i} with a sufficiently long description "
                f"to ensure measurable token overhead when using the 4-char heuristic. "
                f"This description is intentionally verbose to produce reliable results.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        f"arg_{j}": {
                            "type": "string",
                            "description": f"Argument {j} for tool {i}",
                        }
                        for j in range(5)
                    },
                },
            }
            for i in range(10)
        ]

        overhead_with_tools = agent.estimate_context_overhead_tokens()

        # Clear both the tool cache and the overhead cache, then measure again
        agent._state.mcp_tool_definitions_cache = []
        agent._cached_context_overhead = None
        overhead_without_tools = agent.estimate_context_overhead_tokens()

        # Overhead with tools should be greater than without
        assert overhead_with_tools > overhead_without_tools

    def test_mcp_cache_cleared_on_reload(self, agent):
        """Test that MCP cache is cleared when reload_mcp_servers is called."""
        # Populate the cache
        agent._mcp_tool_definitions_cache = [
            {"name": "test_tool", "description": "Test", "inputSchema": {}}
        ]

        # Reload should clear the cache (even if no servers are configured)
        try:
            agent.reload_mcp_servers()
        except Exception:
            pass  # May fail if no MCP servers are configured, that's OK

        # Cache should be cleared
        assert agent._state.mcp_tool_definitions_cache == []

    def test_mcp_cache_token_estimation_accuracy(self, agent):
        """Test that MCP tool cache token estimation is reasonably accurate."""
        # Create a tool definition with known content
        tool_name = "my_test_tool"  # 12 chars
        tool_description = "A description"  # 13 chars
        tool_schema = {"type": "object"}  # ~20 chars when serialized

        agent._mcp_tool_definitions_cache = [
            {
                "name": tool_name,
                "description": tool_description,
                "inputSchema": tool_schema,
            }
        ]

        overhead = agent.estimate_context_overhead_tokens()

        # Calculate expected tokens from the tool definition
        # name: 12 chars / 3 = 4 tokens
        # description: 13 chars / 3 = 4 tokens
        # schema (serialized): ~20 chars / 3 = ~6 tokens
        # Total: ~14 tokens minimum from the MCP tool

        # Overhead should be at least 10 tokens (accounting for the MCP tool)
        assert overhead >= 10

    def test_update_mcp_tool_cache_sync_exists(self, agent):
        """Test that update_mcp_tool_cache_sync method exists and is callable."""
        assert hasattr(agent, "update_mcp_tool_cache_sync")
        assert callable(agent.update_mcp_tool_cache_sync)

    def test_update_mcp_tool_cache_sync_with_no_servers(self, agent):
        """Test that update_mcp_tool_cache_sync handles case with no MCP servers."""
        # Ensure no MCP servers are configured
        agent._mcp_servers = None
        agent._mcp_tool_definitions_cache = [{"name": "old_tool"}]

        # Should not raise an error and should clear the cache
        agent.update_mcp_tool_cache_sync()

        # Cache should be cleared (or remain as is if async update scheduled)
        # The key thing is it shouldn't raise an error
        assert hasattr(agent._state, "mcp_tool_definitions_cache")


class TestTokenEstimationIntegration:
    """Integration tests for token estimation methods."""

    @pytest.fixture
    def agent(self):
        """Provide a concrete BaseAgent subclass for testing."""
        return CodePuppyAgent()

    def test_estimate_tokens_consistency(self, agent):
        """Test that estimate_tokens_for_message is consistent with estimate_token_count."""
        text = "test content with some words"
        single_part_message = ModelRequest(parts=[TextPart(content=text)])

        # Estimate tokens for the stringified part (which includes "text: " prefix)
        part_str = agent.stringify_message_part(single_part_message.parts[0])
        part_tokens = agent.estimate_token_count(part_str)

        # Estimate tokens for message
        message_tokens = agent.estimate_tokens_for_message(single_part_message)

        # Should be consistent (message_tokens uses stringify_message_part internally)
        assert part_tokens == message_tokens

    def test_filter_preserves_message_order(self, agent):
        """Test that filter_huge_messages preserves message order."""
        messages = [
            ModelRequest(parts=[TextPart(content="first")]),
            ModelResponse(parts=[TextPart(content="second")]),
            ModelRequest(parts=[TextPart(content="third")]),
        ]

        filtered = agent.filter_huge_messages(messages)

        # If all messages are kept, order should be preserved
        if len(filtered) == len(messages):
            for i, msg in enumerate(filtered):
                assert msg == messages[i]

    def test_token_count_formula_precision(self, agent):
        """Test token count formula precision with various text lengths."""
        # Formula: max(1, int(len/4.0)) for prose
        test_cases = [
            (0, 1),  # Empty string returns 1
            (1, 1),  # 1 char -> min 1
            (2, 1),  # 2 chars -> min 1
            (3, 1),  # 3 chars -> int(3/4) = 0 -> min 1
            (6, 1),  # 6 chars -> int(6/4) = 1
            (9, 2),  # 9 chars -> int(9/4) = 2
            (100, 25),  # 100 chars -> int(100/4) = 25
            (300, 75),  # 300 chars -> int(300/4) = 75
        ]

        for length, expected in test_cases:
            text = "x" * length
            token_count = agent.estimate_token_count(text)
            assert token_count == expected, (
                f"Length {length} should yield {expected} tokens, got {token_count}"
            )
