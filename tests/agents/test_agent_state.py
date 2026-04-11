"""Tests for AgentRuntimeState dataclass.

This module tests the AgentRuntimeState dataclass which encapsulates
all mutable runtime state for an agent instance, separating it from
immutable agent configuration.
"""

from unittest.mock import MagicMock


from code_puppy.agents.agent_state import AgentRuntimeState


class TestAgentRuntimeStateInitialization:
    """Test default initialization of AgentRuntimeState."""

    def test_default_initialization_all_fields(self):
        """Test that all fields have expected defaults when initialized."""
        state = AgentRuntimeState()

        # Message history and tracking
        assert state.message_history == []
        assert state.compacted_message_hashes == set()
        assert state.message_history_hashes == set()

        # Agent and model caching
        assert state.code_generation_agent is None
        assert state.last_model_name is None
        assert state.puppy_rules is None
        assert state.cur_model is None

        # Tool and prompt caching
        assert state.mcp_tool_definitions_cache == []
        assert state.cached_system_prompt is None
        assert state.cached_tool_defs is None

        # State flags and temporary caches
        assert state.delayed_compaction_requested is False
        assert state.tool_ids_cache is None
        assert state.cached_context_overhead is None
        assert state.model_name_cache is None
        assert state.resolved_model_components_cache is None

        # MCP server connections
        assert state.mcp_servers == []
        assert state.rust_per_message_tokens is None


class TestAgentRuntimeStateClearHistory:
    """Test the clear_history() method."""

    def test_clear_history_clears_all_history_fields(self):
        """Test that clear_history() clears all history-related fields."""
        state = AgentRuntimeState()

        # Populate the fields
        state.message_history = [MagicMock(), MagicMock()]
        state.compacted_message_hashes = {"hash1", "hash2"}
        state.message_history_hashes = {"123", "456"}

        # Clear history
        state.clear_history()

        # Verify all history fields are cleared
        assert state.message_history == []
        assert state.compacted_message_hashes == set()
        assert state.message_history_hashes == set()

    def test_clear_history_empty_already(self):
        """Test clear_history() on already empty state doesn't cause issues."""
        state = AgentRuntimeState()

        # Should not raise
        state.clear_history()

        assert state.message_history == []
        assert state.compacted_message_hashes == set()
        assert state.message_history_hashes == set()


class TestAgentRuntimeStateAppendMessage:
    """Test the append_message() method."""

    def test_append_single_message(self):
        """Test appending a single message and its hash."""
        state = AgentRuntimeState()

        message = {"role": "user", "content": "Hello"}
        message_hash = str(hash("Hello"))

        state.append_message(message, message_hash)

        assert state.message_history == [message]
        assert message_hash in state.message_history_hashes

    def test_append_multiple_messages(self):
        """Test appending multiple messages builds history correctly."""
        state = AgentRuntimeState()

        message1 = {"role": "user", "content": "Hello"}
        message2 = {"role": "assistant", "content": "Hi there"}
        hash1, hash2 = str(hash("Hello")), str(hash("Hi there"))

        state.append_message(message1, hash1)
        state.append_message(message2, hash2)

        assert state.message_history == [message1, message2]
        assert hash1 in state.message_history_hashes
        assert hash2 in state.message_history_hashes

    def test_append_duplicate_hash(self):
        """Test appending a message with a duplicate hash (set handles it)."""
        state = AgentRuntimeState()

        message1 = {"role": "user", "content": "Hello"}
        message2 = {"role": "user", "content": "Hello again"}
        same_hash = "12345"

        state.append_message(message1, same_hash)
        state.append_message(message2, same_hash)

        assert len(state.message_history) == 2
        # Set should only contain one copy of the hash
        assert state.message_history_hashes == {same_hash}


class TestAgentRuntimeStateExtendHistory:
    """Test the extend_history() method."""

    def test_extend_with_multiple_entries(self):
        """Test extending history with multiple messages and hashes."""
        state = AgentRuntimeState()

        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
            {"role": "user", "content": "How are you?"},
        ]
        hashes = ["111", "222", "333"]

        state.extend_history(messages, hashes)

        assert state.message_history == messages
        assert state.message_history_hashes == {"111", "222", "333"}

    def test_extend_empty_lists(self):
        """Test extend_history() with empty lists."""
        state = AgentRuntimeState()

        state.extend_history([], [])

        assert state.message_history == []
        assert state.message_history_hashes == set()

    def test_extend_appends_to_existing(self):
        """Test that extend appends to existing history."""
        state = AgentRuntimeState()

        # Initial state
        state.message_history = [{"role": "system", "content": "Setup"}]
        state.message_history_hashes = {"999"}

        # Extend
        new_messages = [{"role": "user", "content": "Hello"}]
        new_hashes = ["111"]

        state.extend_history(new_messages, new_hashes)

        assert state.message_history == [
            {"role": "system", "content": "Setup"},
            {"role": "user", "content": "Hello"},
        ]
        assert state.message_history_hashes == {"999", "111"}


class TestAgentRuntimeStateInvalidateCaches:
    """Test the invalidate_caches() method."""

    def test_invalidate_resets_ephemeral_caches(self):
        """Test that invalidate_caches() resets ephemeral caches only."""
        state = AgentRuntimeState()

        # Set ephemeral caches
        state.cached_context_overhead = 100
        state.tool_ids_cache = ("key", "value")

        # Set session-scoped caches (should NOT be reset)
        state.cached_system_prompt = "System prompt"
        state.cached_tool_defs = [{"tool": "definition"}]

        # Invalidate caches
        state.invalidate_caches()

        # Ephemeral caches should be reset
        assert state.cached_context_overhead is None
        assert state.tool_ids_cache is None

        # Session-scoped caches should remain
        assert state.cached_system_prompt == "System prompt"
        assert state.cached_tool_defs == [{"tool": "definition"}]

    def test_invalidate_when_already_none(self):
        """Test invalidate_caches() when caches are already None."""
        state = AgentRuntimeState()

        # Should not raise
        state.invalidate_caches()

        assert state.cached_context_overhead is None
        assert state.tool_ids_cache is None

    def test_invalidate_preserves_other_state(self):
        """Test that invalidate_caches() doesn't affect other state fields."""
        state = AgentRuntimeState()

        # Set various state fields
        state.message_history = [{"role": "user", "content": "Hello"}]
        state.message_history_hashes = {"123"}
        state.compacted_message_hashes = {"abc"}
        state.model_name_cache = "gpt-4"
        state.delayed_compaction_requested = True
        state.mcp_servers = [MagicMock()]

        # Set ephemeral caches to invalidate
        state.cached_context_overhead = 100
        state.tool_ids_cache = ("key", "value")

        # Invalidate
        state.invalidate_caches()

        # Other state should be preserved
        assert state.message_history == [{"role": "user", "content": "Hello"}]
        assert state.message_history_hashes == {"123"}
        assert state.compacted_message_hashes == {"abc"}
        assert state.model_name_cache == "gpt-4"
        assert state.delayed_compaction_requested is True
        assert len(state.mcp_servers) == 1

        # Only ephemeral caches should be reset
        assert state.cached_context_overhead is None
        assert state.tool_ids_cache is None
