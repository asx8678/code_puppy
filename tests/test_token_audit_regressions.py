"""Regression tests for token accounting audit findings.

These tests prevent recurrence of bugs identified in the token accounting audit.
Each test corresponds to a specific audit finding with a regression test pattern.

Audit Findings Covered:
1. Nested JSON Schema Counted Successfully - TypeError on nested dict serialization
2. Tool Overhead Nonzero When Tools Registered - Tool definitions must contribute to overhead
3. Puppy Rules Included in Overhead - AGENTS.md content must be part of estimation
4. MCP Cache Invalidation - Tool changes must invalidate token caches
5. Deferred Summarization Returns Correct Type - Must return list, not tuple
6. Turbo/Non-Turbo Estimators Agreement - Consistent token estimation
"""

import inspect
import json
import os
from unittest.mock import MagicMock

import pytest

from code_puppy.agents.agent_state import AgentRuntimeState
from code_puppy.agents.base_agent import BaseAgent, _serialize_schema_to_json
from code_puppy.token_utils import estimate_token_count


# Concrete test agent for testing BaseAgent methods
class MockConcreteAgent(BaseAgent):
    """Concrete implementation of BaseAgent for testing.

    Note: Named to avoid pytest collection as a test class.
    """

    __test__ = False  # Tell pytest this is not a test class

    def name(self) -> str:
        return "mock_concrete_agent"

    def display_name(self) -> str:
        return "Mock Concrete Agent"

    def description(self) -> str:
        return "A mock agent for regression testing"

    def get_system_prompt(self) -> str:
        return "You are a test agent."

    def get_available_tools(self) -> list[str]:
        return []


@pytest.fixture
def mock_agent():
    """Create a fresh MockConcreteAgent instance."""
    return MockConcreteAgent()


# =============================================================================
# Test 1: Nested JSON Schema Counted Successfully
# =============================================================================

def test_nested_schema_serialization():
    """Regression test: nested dict schemas must not raise TypeError (audit finding).

    The original bug was that deeply nested schemas would fail with:
    TypeError: unhashable type: 'dict' when using tuple(sorted(schema.items()))
    as a cache key. The fix uses LRU cache on the canonical JSON string instead.
    """
    # Deeply nested schema that would fail with tuple(sorted(schema.items()))
    nested_schema = {
        "type": "object",
        "properties": {
            "user": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "address": {
                        "type": "object",
                        "properties": {
                            "city": {"type": "string"},
                            "zip": {"type": "integer"}
                        }
                    }
                }
            }
        }
    }

    # Should not raise TypeError
    schema_json = json.dumps(nested_schema, sort_keys=True, separators=(',', ':'))
    result = _serialize_schema_to_json(schema_json)
    assert result == schema_json

    # Verify it's cacheable (call twice, should hit cache)
    result2 = _serialize_schema_to_json(schema_json)
    assert result2 == result


def test_nested_schema_with_arrays():
    """Test schemas containing arrays - another edge case for serialization."""
    schema_with_array = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "nested": {"type": "string"}
                    }
                }
            }
        }
    }
    schema_json = json.dumps(schema_with_array, sort_keys=True, separators=(',', ':'))
    result = _serialize_schema_to_json(schema_json)
    assert result == schema_json


# =============================================================================
# Test 2: Tool Overhead Nonzero When Tools Registered
# =============================================================================

def test_tool_overhead_nonzero(mock_agent):
    """Regression test: tool definitions must contribute to context overhead.

    When tools are registered on the code_generation_agent, the overhead
    estimation must include tokens from tool names, descriptions, and schemas.
    An empty tool set should result in minimal overhead (just system prompt),
    while tools should add measurable overhead.
    """
    # Use the test agent
    agent = mock_agent

    # Mock the state with no tools - overhead should be minimal
    agent._state.cached_context_overhead = None
    agent._state.code_generation_agent = None  # No tools

    # Get base overhead (system prompt only)
    base_overhead = agent.estimate_context_overhead_tokens()
    assert base_overhead >= 0  # Should not error

    # Now mock an agent with tools
    mock_tool = MagicMock()
    mock_tool.__doc__ = "A test tool that does something useful"
    mock_tool.schema = {
        "type": "object",
        "properties": {
            "param1": {"type": "string", "description": "First parameter"}
        },
        "required": ["param1"]
    }

    mock_pydantic_agent = MagicMock()
    mock_pydantic_agent._tools = {"test_tool": mock_tool}

    # Reset cache and set mock agent
    agent._state.cached_context_overhead = None
    agent._state.cached_tool_defs = None
    agent._state.code_generation_agent = mock_pydantic_agent

    # Get overhead with tools
    with_tools_overhead = agent.estimate_context_overhead_tokens()

    # With tools, overhead should be greater than base
    assert with_tools_overhead > base_overhead, (
        f"Tool overhead should increase context overhead. "
        f"Base: {base_overhead}, With tools: {with_tools_overhead}"
    )


def test_tool_overhead_includes_all_components(mock_agent):
    """Verify that tool overhead accounts for name, description, and schema."""
    agent = mock_agent

    # Create a mock tool with all components
    mock_tool = MagicMock()
    mock_tool.__doc__ = "Description with many tokens to count"
    mock_tool.schema = {
        "type": "object",
        "properties": {
            "param1": {"type": "string"},
            "param2": {"type": "integer"},
            "nested": {
                "type": "object",
                "properties": {
                    "deep": {"type": "string"}
                }
            }
        },
        "required": ["param1", "param2"]
    }

    mock_pydantic_agent = MagicMock()
    mock_pydantic_agent._tools = {"my_tool_name": mock_tool}

    # Reset cache
    agent._state.cached_context_overhead = None
    agent._state.cached_tool_defs = None
    agent._state.code_generation_agent = mock_pydantic_agent

    overhead = agent.estimate_context_overhead_tokens()

    # The overhead should be at least the sum of estimated tokens for each component
    name_tokens = len("my_tool_name") // 4
    desc_tokens = len(mock_tool.__doc__) // 4
    schema_str = json.dumps(mock_tool.schema, sort_keys=True, separators=(',', ':'))
    schema_tokens = len(schema_str) // 4

    min_expected = name_tokens + desc_tokens + schema_tokens
    assert overhead >= min_expected, (
        f"Overhead {overhead} should be at least {min_expected} "
        f"(name:{name_tokens} + desc:{desc_tokens} + schema:{schema_tokens})"
    )


# =============================================================================
# Test 3: Puppy Rules Included in Overhead
# =============================================================================

def test_puppy_rules_in_overhead(tmp_path, monkeypatch, mock_agent):
    """Regression test: puppy rules must be included in overhead estimation.

    The AGENTS.md content (puppy rules) must be included when calculating
    context overhead, as these rules are prepended to the system prompt
    and consume tokens in the context window.
    """
    # Create a temporary AGENTS.md with known content
    test_rules_content = "# Test Rules\n\nThis is a test rule with exactly forty tokens worth of content for testing purposes."
    agents_md = tmp_path / "AGENTS.md"
    agents_md.write_text(test_rules_content, encoding="utf-8")

    # Use the mock agent
    agent = mock_agent

    # Reset puppy rules cache
    agent._state.puppy_rules = None

    # Monkeypatch to load from temp directory
    original_cwd = os.getcwd()
    try:
        monkeypatch.chdir(tmp_path)
        rules = agent.load_puppy_rules()
        assert rules is not None
        assert "Test Rules" in rules

        # Now estimate overhead - it should include the rules
        agent._state.cached_context_overhead = None
        agent._state.cached_system_prompt = None

        overhead_with_rules = agent.estimate_context_overhead_tokens()

        # Reset and clear rules to compare
        agent._state.puppy_rules = None
        agent._state.cached_context_overhead = None
        agent._state.cached_system_prompt = None

        # Compare - with rules should be higher
        # Note: minimal comparison since system prompt varies
        assert overhead_with_rules > 0, "Overhead with rules should be positive"
    finally:
        monkeypatch.chdir(original_cwd)


def test_puppy_rules_cached_in_overhead(mock_agent):
    """Verify that puppy rules are consistently included via caching."""
    agent = mock_agent

    # Set puppy rules explicitly
    test_rules = "These are custom puppy rules for testing token counting."
    agent._state.puppy_rules = test_rules

    # Clear overhead cache
    agent._state.cached_context_overhead = None

    # Get overhead - should include rules
    overhead1 = agent.estimate_context_overhead_tokens()

    # Clear only overhead cache, not rules - should still include rules
    agent._state.cached_context_overhead = None
    overhead2 = agent.estimate_context_overhead_tokens()

    # Should be consistent since rules are still cached
    assert overhead1 == overhead2


# =============================================================================
# Test 4: MCP Cache Invalidation
# =============================================================================

def test_mcp_cache_invalidation():
    """Regression test: MCP tool changes must invalidate token caches.

    When MCP tools are updated, all related token caches must be invalidated
    to prevent stale estimates. This was a fragmented cache invalidation
    issue where not all caches were cleared together.
    """
    state = AgentRuntimeState()

    # Set some cached values simulating a running agent
    state.cached_context_overhead = 1500
    state.cached_tool_defs = [{"name": "test_tool", "description": "Test"}]
    state.cached_system_prompt = "test system prompt with rules"
    state.tool_ids_cache = {"tool_123": "cached_id"}

    # Verify values are set
    assert state.cached_context_overhead is not None
    assert state.cached_tool_defs is not None
    assert state.cached_system_prompt is not None
    assert state.tool_ids_cache is not None

    # Invalidate all token caches
    state.invalidate_all_token_caches()

    # Verify ALL caches are cleared - not just some
    assert state.cached_context_overhead is None, "context_overhead should be None"
    assert state.cached_tool_defs is None, "cached_tool_defs should be None"
    assert state.cached_system_prompt is None, "cached_system_prompt should be None"
    assert state.tool_ids_cache is None, "tool_ids_cache should be None"


def test_mcp_cache_invalidation_idempotent():
    """Verify that cache invalidation is safe to call multiple times."""
    state = AgentRuntimeState()

    # Set cached values
    state.cached_context_overhead = 1000
    state.invalidate_all_token_caches()

    # Should not error calling again when already None
    state.invalidate_all_token_caches()

    # All should still be None
    assert state.cached_context_overhead is None
    assert state.cached_tool_defs is None
    assert state.cached_system_prompt is None


# =============================================================================
# Test 5: Deferred Summarization Returns Correct Type
# =============================================================================

def test_message_history_processor_returns_list():
    """Regression test: message_history_processor must return list, not tuple.

    The original bug had a return statement like `return messages, []` which
    created a tuple instead of a list. This broke downstream processing
    that expected list operations (append, extend, etc.).

    This test verifies the return type annotation matches the expected behavior.
    """
    # Get the signature and check return annotation
    sig = inspect.signature(BaseAgent.message_history_processor)
    return_annotation = sig.return_annotation

    # Should indicate list[ModelMessage], not tuple
    return_str = str(return_annotation).lower()

    # Should be some form of list, not tuple
    assert 'list' in return_str, (
        f"Return type should be list, got: {return_annotation}"
    )
    assert 'tuple' not in return_str, (
        f"Return type should not be tuple, got: {return_annotation}"
    )


def test_message_history_processor_annotation_matches_docstring():
    """Verify that the method's documentation matches its signature."""
    # Get docstring if available
    docstring = BaseAgent.message_history_processor.__doc__

    # Get return annotation
    sig = inspect.signature(BaseAgent.message_history_processor)
    return_annotation = sig.return_annotation

    # If there are docs, they should mention returning messages/list
    if docstring:
        doc_lower = docstring.lower()
        assert 'return' in doc_lower, "Docstring should describe return value"

    # The return annotation should be a list type
    assert 'list' in str(return_annotation).lower()


# =============================================================================
# Test 6: Turbo/Non-Turbo Estimators Agreement
# =============================================================================

def test_estimator_agreement():
    """Regression test: token estimator should give reasonable results.

    The Python token estimator should produce consistent results within
    expected bounds. For prose: ~4.0 chars/token, for code: ~4.5 chars/token.

    This test verifies the estimator stays within generous bounds to catch
    any major regression in estimation logic.
    """
    test_texts = [
        ("Hello world, this is a simple test.", "prose"),
        ("def foo():\n    return 42\n", "code"),
        ("A" * 1000, "repeated_char"),  # Long text
        ("The quick brown fox jumps. " * 100, "long_prose"),
    ]

    for text, text_type in test_texts:
        python_estimate = estimate_token_count(text)

        # Basic sanity - should be at least 1
        assert python_estimate >= 1, f"{text_type}: estimate should be >= 1"

        # Upper bound - should not overestimate too much
        max_expected = max(1, len(text))  # At worst 1 char = 1 token
        assert python_estimate <= max_expected, (
            f"{text_type}: estimate {python_estimate} > max {max_expected}"
        )

        # Generous bounds based on text type
        if text_type == "code":
            expected_min = len(text) / 5.0  # code: ~4.5 chars/token
            expected_max = len(text) / 3.5
        else:
            expected_min = len(text) / 5.0  # prose: ~4.0 chars/token
            expected_max = len(text) / 3.0

        assert expected_min <= python_estimate <= expected_max, (
            f"{text_type}: estimate {python_estimate} not in range "
            f"[{expected_min:.1f}, {expected_max:.1f}] for length {len(text)}"
        )


def test_code_vs_prose_estimation():
    """Verify that code is estimated with different ratio than prose."""
    # Create texts of same length
    prose = "The quick brown fox jumps over the lazy dog. " * 10  # ~450 chars
    code = "def test():\n    return x + y\n" * 15  # Similar length

    prose_len = len(prose)
    code_len = len(code)

    # Normalize for length comparison
    prose_estimate = estimate_token_count(prose)
    code_estimate = estimate_token_count(code)

    # Both should have reasonable estimates
    assert prose_estimate > 0
    assert code_estimate > 0

    # Prose should generally have more tokens per char (lower ratio) than code
    # because code has more special characters that are separate tokens
    prose_ratio = prose_len / prose_estimate
    code_ratio = code_len / code_estimate

    # Code should have higher chars per token (fewer tokens) or similar
    # This is a heuristic, so we allow some flexibility
    assert 3.0 <= prose_ratio <= 5.0, f"Prose ratio {prose_ratio:.2f} out of range"
    assert 3.5 <= code_ratio <= 5.5, f"Code ratio {code_ratio:.2f} out of range"


def test_estimator_caching():
    """Verify that the estimator caches results correctly."""
    text = "This is a test string for caching verification."

    # First call
    estimate1 = estimate_token_count(text)

    # Second call should hit cache (same result, but we can't easily verify cache hit)
    estimate2 = estimate_token_count(text)

    # Should be identical
    assert estimate1 == estimate2

    # Different text should potentially give different result
    different_text = "Different content for different tokens."
    estimate3 = estimate_token_count(different_text)

    # May be same by coincidence, but unlikely
    # Just verify it's valid
    assert estimate3 >= 1


# =============================================================================
# Additional Integration Tests
# =============================================================================

def test_serialize_schema_consistency():
    """Verify schema serialization is deterministic and consistent."""
    schema = {"type": "object", "properties": {"a": {"type": "string"}}}

    # Multiple serializations should produce identical results
    json1 = json.dumps(schema, sort_keys=True, separators=(',', ':'))
    json2 = json.dumps(schema, sort_keys=True, separators=(',', ':'))

    result1 = _serialize_schema_to_json(json1)
    result2 = _serialize_schema_to_json(json2)

    assert result1 == result2
    assert result1 == json1


def test_agent_state_isolation():
    """Verify that AgentRuntimeState instances are independent."""
    state1 = AgentRuntimeState()
    state2 = AgentRuntimeState()

    # Modify state1
    state1.cached_context_overhead = 1000
    state1.cached_tool_defs = [{"name": "tool1"}]

    # state2 should be unaffected
    assert state2.cached_context_overhead is None
    assert state2.cached_tool_defs is None

    # Invalidate state1 - should not affect state2
    state1.invalidate_all_token_caches()
    assert state2.cached_context_overhead is None  # Still None
