"""Tests for agent_tools state isolation via _EXCLUDED_STATE_KEYS.

Tests the filter_context_for_subagent helper that prevents parent context
keys from leaking to sub-agents.
"""

from code_puppy.tools.agent_tools import (
    _EXCLUDED_STATE_KEYS,
    filter_context_for_subagent,
)


class TestExcludedStateKeys:
    """Tests for the _EXCLUDED_STATE_KEYS constant."""

    def test_is_frozen_set(self):
        """_EXCLUDED_STATE_KEYS should be a frozenset."""
        assert isinstance(_EXCLUDED_STATE_KEYS, frozenset)

    def test_contains_expected_keys(self):
        """Should contain expected sensitive/parent-specific keys."""
        expected_keys = {
            "parent_session_id",
            "agent_session_id",
            "session_history",
            "previous_tool_results",
            "tool_call_history",
            "tool_outputs",
            "_private_state",
            "_internal_metadata",
            "callback_registry",
            "hook_state",
            "render_context",
            "console_state",
        }
        for key in expected_keys:
            assert key in _EXCLUDED_STATE_KEYS, (
                f"Expected {key} in _EXCLUDED_STATE_KEYS"
            )

    def test_keys_are_strings(self):
        """All keys should be strings."""
        for key in _EXCLUDED_STATE_KEYS:
            assert isinstance(key, str)


class TestFilterContextForSubagent:
    """Tests for filter_context_for_subagent function."""

    def test_none_input_returns_empty_dict(self):
        """filter_context_for_subagent(None) returns {}."""
        result = filter_context_for_subagent(None)
        assert result == {}
        assert isinstance(result, dict)

    def test_empty_dict_returns_empty_dict(self):
        """filter_context_for_subagent({}) returns {}."""
        result = filter_context_for_subagent({})
        assert result == {}

    def test_allowed_keys_pass_through(self):
        """A context with only allowed keys passes through unchanged."""
        context = {
            "user_prompt": "Hello",
            "file_path": "/tmp/test.py",
            "model_name": "claude-opus-4",
        }
        result = filter_context_for_subagent(context)
        assert result == context
        assert result is not context  # Should be a new dict

    def test_excluded_keys_removed(self):
        """A context with excluded keys has them removed."""
        context = {
            "user_prompt": "Hello",
            "parent_session_id": "abc-123",  # excluded
            "tool_outputs": [{"result": 42}],  # excluded
            "model_name": "claude-opus-4",
        }
        result = filter_context_for_subagent(context)
        assert "user_prompt" in result
        assert "model_name" in result
        assert "parent_session_id" not in result
        assert "tool_outputs" not in result

    def test_mixed_context_allowed_and_excluded(self):
        """A context with a mix: allowed kept, excluded removed."""
        context = {
            "allowed_key": "value1",
            "parent_session_id": "abc",  # excluded
            "allowed_key2": "value2",
            "agent_session_id": "xyz",  # excluded
            "allowed_key3": "value3",
        }
        result = filter_context_for_subagent(context)
        assert result == {
            "allowed_key": "value1",
            "allowed_key2": "value2",
            "allowed_key3": "value3",
        }

    def test_original_context_not_mutated(self):
        """Original context dict should not be mutated."""
        context = {
            "user_prompt": "Hello",
            "parent_session_id": "abc-123",
            "tool_outputs": [{"result": 42}],
        }
        original_keys = set(context.keys())
        result = filter_context_for_subagent(context)
        # Original should be unchanged
        assert set(context.keys()) == original_keys
        assert "parent_session_id" in context
        # Result should have filtered keys
        assert "parent_session_id" not in result

    def test_all_excluded_keys_actually_excluded(self):
        """Every key in _EXCLUDED_STATE_KEYS should be excluded."""
        # Create a context with all excluded keys plus one allowed
        context = {key: f"value_{key}" for key in _EXCLUDED_STATE_KEYS}
        context["allowed_key"] = "I should remain"

        result = filter_context_for_subagent(context)

        # All excluded keys should be gone
        for key in _EXCLUDED_STATE_KEYS:
            assert key not in result, f"Key {key} should be excluded but is present"

        # The allowed key should remain
        assert "allowed_key" in result
        assert result["allowed_key"] == "I should remain"

    def test_handles_nested_values(self):
        """Function should handle nested dict/list values correctly."""
        context = {
            "simple_value": "string",
            "nested_dict": {"a": 1, "b": 2},
            "list_value": [1, 2, 3],
            "parent_session_id": "abc",  # excluded
        }
        result = filter_context_for_subagent(context)
        assert result["simple_value"] == "string"
        assert result["nested_dict"] == {"a": 1, "b": 2}
        assert result["list_value"] == [1, 2, 3]
        assert "parent_session_id" not in result

    def test_handles_none_values(self):
        """Function should handle None values in context."""
        context = {
            "none_value": None,
            "parent_session_id": None,  # excluded
        }
        result = filter_context_for_subagent(context)
        assert "none_value" in result
        assert result["none_value"] is None
        assert "parent_session_id" not in result
