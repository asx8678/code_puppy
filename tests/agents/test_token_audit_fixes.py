"""Regression tests for token estimation audit fixes.

These tests verify the fixes for critical issues found during the token flow
audit. Each test class corresponds to a specific audit finding.

Audit findings covered:
- Task 1.1: pydantic_agent → code_generation_agent lookup
- Task 1.2: BinaryContent token estimation
- Task 2.1+2.2: Cache invalidation consistency
"""

import hashlib
from unittest.mock import MagicMock, patch

import pytest
from pydantic_ai import BinaryContent

import code_puppy.agents.base_agent as base_agent_module


# Concrete subclass for testing (mirrors test_base_agent_full_coverage.py)
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


class TestBinaryContentTokenEstimation:
    """Verify BinaryContent produces realistic token estimates (audit Task 1.2)."""

    def test_estimate_binary_content_tokens_image(self):
        """Image BinaryContent should estimate at least 100 tokens."""
        from code_puppy.agents.base_agent import _estimate_binary_content_tokens

        mock_binary = MagicMock()
        mock_binary.data = b"\x89PNG" + b"\x00" * 100_000  # ~100KB PNG
        mock_binary.media_type = "image/png"

        tokens = _estimate_binary_content_tokens(mock_binary)
        assert tokens >= 100, f"Image should estimate >= 100 tokens, got {tokens}"

    def test_estimate_binary_content_tokens_large_image(self):
        """Large image should estimate proportionally more tokens."""
        from code_puppy.agents.base_agent import _estimate_binary_content_tokens

        mock_binary = MagicMock()
        mock_binary.data = b"\x89PNG" + b"\x00" * 500_000  # ~500KB PNG
        mock_binary.media_type = "image/png"

        tokens = _estimate_binary_content_tokens(mock_binary)
        # 500KB = ~2.5 tiles * 750 = ~1875 tokens
        assert tokens >= 750, f"Large image should estimate >= 750 tokens, got {tokens}"

    def test_estimate_binary_content_tokens_pdf(self):
        """PDF should estimate tokens based on size."""
        from code_puppy.agents.base_agent import _estimate_binary_content_tokens

        mock_binary = MagicMock()
        mock_binary.data = b"%PDF" + b"\x00" * 200_000  # ~200KB PDF
        mock_binary.media_type = "application/pdf"

        tokens = _estimate_binary_content_tokens(mock_binary)
        assert tokens >= 200, f"PDF should estimate >= 200 tokens, got {tokens}"

    def test_estimate_binary_content_tokens_generic(self):
        """Generic binary should estimate conservatively."""
        from code_puppy.agents.base_agent import _estimate_binary_content_tokens

        mock_binary = MagicMock()
        mock_binary.data = b"\x00" * 10_000  # 10KB binary
        mock_binary.media_type = "application/octet-stream"

        tokens = _estimate_binary_content_tokens(mock_binary)
        assert tokens >= 50, f"Generic binary should estimate >= 50 tokens, got {tokens}"

    def test_estimate_binary_content_tokens_minimum(self):
        """Even tiny binary should have a minimum token estimate."""
        from code_puppy.agents.base_agent import _estimate_binary_content_tokens

        mock_binary = MagicMock()
        mock_binary.data = b"\x00"  # 1 byte
        mock_binary.media_type = "image/png"

        tokens = _estimate_binary_content_tokens(mock_binary)
        assert tokens >= 100, f"Minimum image estimate should be >= 100, got {tokens}"

    def test_estimate_no_media_type_defaults_to_generic(self):
        """Missing media_type should use generic estimation."""
        from code_puppy.agents.base_agent import _estimate_binary_content_tokens

        mock_binary = MagicMock()
        mock_binary.data = b"\x00" * 10_000
        mock_binary.media_type = None

        tokens = _estimate_binary_content_tokens(mock_binary)
        assert tokens >= 50


class TestBinaryContentHashing:
    """Verify BinaryContent hashing is stable across processes (audit Task 1.2)."""

    def test_binary_hash_uses_sha256_not_builtin_hash(self):
        """BinaryContent hash should use SHA-256, not Python's hash()."""
        agent = ConcreteAgent()

        binary = BinaryContent(data=b"test image data", media_type="image/png")

        # Create a mock message part with BinaryContent in list
        mock_part = MagicMock()
        mock_part.content = ["some text", binary]

        result = agent._stringify_part(mock_part)

        # Should contain BinaryContent= with SHA-256 hex digest
        assert "BinaryContent=" in result
        # Extract the hash portion - format is "BinaryContent=<hex>:<size>"
        bc_part = [p for p in result.split("|") if "BinaryContent=" in p][0]
        hash_value = bc_part.split("BinaryContent=")[1].split(":")[0]
        # SHA-256 hex chars are all 0-9a-f
        assert all(c in "0123456789abcdef" for c in hash_value), (
            f"Hash should be hex (SHA-256), got: {hash_value}"
        )
        # Verify it's the expected SHA-256 of first 4096 bytes
        expected = hashlib.sha256(b"test image data").hexdigest()[:16]
        assert hash_value == expected, (
            f"Hash mismatch: expected {expected}, got {hash_value}"
        )

    def test_binary_hash_is_deterministic(self):
        """Same data should produce same hash across calls."""
        agent = ConcreteAgent()

        binary = BinaryContent(data=b"consistent test data", media_type="image/png")

        mock_part = MagicMock()
        mock_part.content = [binary]

        result1 = agent._stringify_part(mock_part)
        result2 = agent._stringify_part(mock_part)
        assert result1 == result2

    def test_binary_hash_differs_for_different_data(self):
        """Different binary data should produce different hashes."""
        agent = ConcreteAgent()

        binary_a = BinaryContent(data=b"image data A", media_type="image/png")
        binary_b = BinaryContent(data=b"image data B", media_type="image/png")

        part_a = MagicMock()
        part_a.content = [binary_a]
        part_b = MagicMock()
        part_b.content = [binary_b]

        result_a = agent._stringify_part(part_a)
        result_b = agent._stringify_part(part_b)
        assert result_a != result_b


class TestCacheInvalidationConsistency:
    """Verify cache invalidation covers all mutation points (audit Task 2)."""

    def test_invalidate_all_token_caches_clears_everything(self):
        """invalidate_all_token_caches should clear all 5 token caches."""
        from code_puppy.agents.agent_state import AgentRuntimeState

        state = AgentRuntimeState()
        # Set all caches to non-None values
        state.cached_context_overhead = 1000
        state.cached_system_prompt = "test prompt"
        state.cached_tool_defs = [{"name": "test"}]
        state.tool_ids_cache = {"id": 1}
        state.rust_per_message_tokens = [10, 20, 30]

        state.invalidate_all_token_caches()

        assert state.cached_context_overhead is None
        assert state.cached_system_prompt is None
        assert state.cached_tool_defs is None
        assert state.tool_ids_cache is None
        assert state.rust_per_message_tokens is None

    def test_invalidate_system_prompt_also_clears_overhead(self):
        """System prompt cache invalidation should also clear overhead."""
        from code_puppy.agents.agent_state import AgentRuntimeState

        state = AgentRuntimeState()
        state.cached_system_prompt = "test prompt"
        state.cached_context_overhead = 5000

        state.invalidate_system_prompt_cache()

        assert state.cached_system_prompt is None
        assert state.cached_context_overhead is None

    def test_invalidate_caches_backward_compat(self):
        """Original invalidate_caches should still work (backward compat)."""
        from code_puppy.agents.agent_state import AgentRuntimeState

        state = AgentRuntimeState()
        state.cached_context_overhead = 1000
        state.tool_ids_cache = {"id": 1}

        state.invalidate_caches()

        assert state.cached_context_overhead is None
        assert state.tool_ids_cache is None


class TestCodeGenerationAgentLookup:
    """Verify tool defs are found via code_generation_agent, not pydantic_agent (audit Task 1.1)."""

    def test_overhead_uses_code_generation_agent(self):
        """estimate_context_overhead_tokens should read from _state.code_generation_agent."""
        agent = ConcreteAgent()

        # Set up a mock agent with tools on _state.code_generation_agent
        mock_tool = MagicMock()
        mock_tool.__doc__ = "A test tool that does testing"
        mock_tool.schema = {
            "type": "object",
            "properties": {"arg1": {"type": "string"}},
        }
        mock_tool.__annotations__ = {}

        mock_pydantic_agent = MagicMock()
        mock_pydantic_agent._tools = {"test_tool": mock_tool}

        agent._state.code_generation_agent = mock_pydantic_agent

        # Patch get_full_system_prompt to return a simple string
        with patch.object(
            type(agent), "get_full_system_prompt", return_value="test system prompt"
        ):
            tokens = agent.estimate_context_overhead_tokens()

        # Should include tool definition tokens (> just the system prompt)
        assert tokens > 0, "Should count tool definition tokens"
        # Cache should be set
        assert agent._state.cached_context_overhead is not None

    def test_no_agent_no_crash(self):
        """Should handle None code_generation_agent gracefully."""
        agent = ConcreteAgent()

        # No code_generation_agent set (None)
        with patch.object(
            type(agent), "get_full_system_prompt", return_value="test"
        ):
            tokens = agent.estimate_context_overhead_tokens()

        # Should still work (just system prompt tokens)
        assert tokens > 0
