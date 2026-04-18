"""End-to-end integration tests for message RPC (bd-115).

These tests verify the full round-trip of message operations through
the Elixir StdioService backend. They require the Elixir service to
be running.

Run with:
    pytest tests/integration/test_message_rpc_e2e.py -v --tb=short
"""

import pytest
from typing import Any

# Skip all tests if transport not available
try:
    from code_puppy import message_transport
    from code_puppy.elixir_transport_helpers import get_transport, shutdown
    TRANSPORT_AVAILABLE = True
except ImportError:
    TRANSPORT_AVAILABLE = False
    message_transport = None  # type: ignore

pytestmark = [
    pytest.mark.skipif(not TRANSPORT_AVAILABLE, reason="Elixir transport not available"),
    pytest.mark.integration,
    pytest.mark.e2e,
]


@pytest.fixture(scope="module")
def transport():
    """Ensure transport is started for the test module."""
    if TRANSPORT_AVAILABLE:
        t = get_transport()
        yield t
        # Don't shutdown - let other tests use the singleton
    else:
        yield None


class TestSerializationRoundTrip:
    """Test serialize/deserialize round-trip integrity."""

    def test_simple_message_roundtrip(self, transport):
        """Simple text messages survive serialization."""
        messages = [
            {"kind": "request", "role": "user", "parts": [
                {"part_kind": "text", "content": "Hello, world!"}
            ]},
            {"kind": "response", "role": "assistant", "parts": [
                {"part_kind": "text", "content": "Hi there!"}
            ]},
        ]
        
        data = message_transport.serialize_session(messages)
        restored = message_transport.deserialize_session(data)
        
        assert len(restored) == 2
        assert restored[0]["kind"] == "request"
        assert restored[0]["parts"][0]["content"] == "Hello, world!"
        assert restored[1]["kind"] == "response"
        assert restored[1]["parts"][0]["content"] == "Hi there!"

    def test_tool_call_roundtrip(self, transport):
        """Tool calls with IDs survive serialization."""
        messages = [
            {"kind": "request", "role": "user", "parts": [
                {"part_kind": "text", "content": "Read the file"}
            ]},
            {"kind": "response", "role": "assistant", "parts": [
                {"part_kind": "tool-call", "tool_call_id": "call_abc123",
                 "tool_name": "read_file", "content": None}
            ]},
            {"kind": "request", "role": "user", "parts": [
                {"part_kind": "tool-return", "tool_call_id": "call_abc123",
                 "content": "file contents here"}
            ]},
        ]
        
        data = message_transport.serialize_session(messages)
        restored = message_transport.deserialize_session(data)
        
        assert len(restored) == 3
        # Verify tool call ID preserved
        assert restored[1]["parts"][0]["tool_call_id"] == "call_abc123"
        assert restored[1]["parts"][0]["tool_name"] == "read_file"
        # Verify tool return ID preserved
        assert restored[2]["parts"][0]["tool_call_id"] == "call_abc123"

    def test_unicode_content_roundtrip(self, transport):
        """Unicode content is preserved through serialization."""
        messages = [
            {"kind": "request", "role": "user", "parts": [
                {"part_kind": "text", "content": "Hello 你好 🐶 émoji naïve"}
            ]},
        ]
        
        data = message_transport.serialize_session(messages)
        restored = message_transport.deserialize_session(data)
        
        assert restored[0]["parts"][0]["content"] == "Hello 你好 🐶 émoji naïve"

    def test_empty_messages_roundtrip(self, transport):
        """Empty message lists are handled correctly."""
        data = message_transport.serialize_session([])
        restored = message_transport.deserialize_session(data)
        assert restored == []

    def test_incremental_append(self, transport):
        """Incremental serialization appends correctly."""
        initial = [{"kind": "request", "role": "user", "parts": []}]
        data = message_transport.serialize_session(initial)
        
        # Append more messages
        more = [
            {"kind": "response", "role": "assistant", "parts": []},
            {"kind": "request", "role": "user", "parts": []},
        ]
        data = message_transport.serialize_incremental(more, data)
        
        restored = message_transport.deserialize_session(data)
        assert len(restored) == 3


class TestHashConsistency:
    """Test hash computation consistency."""

    def test_identical_messages_same_hash(self, transport):
        """Identical messages produce identical hashes."""
        msg = {"kind": "request", "role": "user", "parts": [
            {"part_kind": "text", "content": "Test message"}
        ]}
        
        hash1 = message_transport.hash_message(msg)
        hash2 = message_transport.hash_message(msg)
        
        assert hash1 == hash2

    def test_different_content_different_hash(self, transport):
        """Different content produces different hashes."""
        msg1 = {"kind": "request", "parts": [
            {"part_kind": "text", "content": "Message A"}
        ]}
        msg2 = {"kind": "request", "parts": [
            {"part_kind": "text", "content": "Message B"}
        ]}
        
        assert message_transport.hash_message(msg1) != message_transport.hash_message(msg2)

    def test_different_roles_different_hash(self, transport):
        """Different roles produce different hashes."""
        msg1 = {"kind": "request", "role": "user", "parts": []}
        msg2 = {"kind": "request", "role": "assistant", "parts": []}
        
        assert message_transport.hash_message(msg1) != message_transport.hash_message(msg2)

    def test_batch_hash_matches_individual(self, transport):
        """Batch hashing produces same results as individual."""
        messages = [
            {"kind": "request", "parts": [{"part_kind": "text", "content": "A"}]},
            {"kind": "response", "parts": [{"part_kind": "text", "content": "B"}]},
            {"kind": "request", "parts": [{"part_kind": "text", "content": "C"}]},
        ]
        
        batch_hashes = message_transport.hash_batch(messages)
        individual_hashes = [message_transport.hash_message(m) for m in messages]
        
        assert batch_hashes == individual_hashes

    def test_hash_survives_serialization(self, transport):
        """Hash is consistent before and after serialization roundtrip."""
        msg = {"kind": "request", "role": "user", "parts": [
            {"part_kind": "text", "content": "Persistence test"}
        ]}
        
        hash_before = message_transport.hash_message(msg)
        
        data = message_transport.serialize_session([msg])
        restored = message_transport.deserialize_session(data)
        
        hash_after = message_transport.hash_message(restored[0])
        
        assert hash_before == hash_after


class TestPruningIntegrity:
    """Test pruning preserves message integrity."""

    def test_complete_pairs_preserved(self, transport):
        """Complete tool call/return pairs are preserved."""
        messages = [
            {"kind": "request", "role": "user", "parts": [
                {"part_kind": "text", "content": "Start"}
            ]},
            {"kind": "response", "role": "assistant", "parts": [
                {"part_kind": "tool-call", "tool_call_id": "tc1", "tool_name": "test"}
            ]},
            {"kind": "request", "role": "user", "parts": [
                {"part_kind": "tool-return", "tool_call_id": "tc1", "content": "done"}
            ]},
            {"kind": "response", "role": "assistant", "parts": [
                {"part_kind": "text", "content": "Finished"}
            ]},
        ]
        
        result = message_transport.prune_and_filter(messages)
        
        # All 4 messages should survive (complete pair)
        assert result["surviving_indices"] == [0, 1, 2, 3]
        assert result["dropped_count"] == 0
        assert result["had_pending_tool_calls"] is False

    def test_orphaned_call_dropped(self, transport):
        """Orphaned tool calls are correctly identified and dropped."""
        messages = [
            {"kind": "request", "role": "user", "parts": [
                {"part_kind": "text", "content": "Start"}
            ]},
            {"kind": "response", "role": "assistant", "parts": [
                {"part_kind": "tool-call", "tool_call_id": "orphan", "tool_name": "test"}
            ]},
            # Missing tool-return for "orphan"
        ]
        
        result = message_transport.prune_and_filter(messages)
        
        # Only first message survives
        assert result["surviving_indices"] == [0]
        assert result["dropped_count"] == 1
        assert result["had_pending_tool_calls"] is True
        assert result["pending_tool_call_count"] == 1

    def test_orphaned_return_dropped(self, transport):
        """Orphaned tool returns are dropped."""
        messages = [
            {"kind": "request", "role": "user", "parts": [
                {"part_kind": "text", "content": "Start"}
            ]},
            # No tool-call, just a return
            {"kind": "request", "role": "user", "parts": [
                {"part_kind": "tool-return", "tool_call_id": "ghost", "content": "???"}
            ]},
        ]
        
        result = message_transport.prune_and_filter(messages)
        
        assert result["surviving_indices"] == [0]
        assert result["dropped_count"] == 1

    def test_mixed_valid_and_orphaned(self, transport):
        """Valid pairs preserved while orphaned messages dropped."""
        messages = [
            {"kind": "request", "parts": [{"part_kind": "text", "content": "A"}]},
            {"kind": "response", "parts": [
                {"part_kind": "tool-call", "tool_call_id": "valid1", "tool_name": "t"}
            ]},
            {"kind": "request", "parts": [
                {"part_kind": "tool-return", "tool_call_id": "valid1", "content": "ok"}
            ]},
            {"kind": "response", "parts": [
                {"part_kind": "tool-call", "tool_call_id": "orphan", "tool_name": "t"}
            ]},
            # Missing return for "orphan"
            {"kind": "response", "parts": [{"part_kind": "text", "content": "Done"}]},
        ]
        
        result = message_transport.prune_and_filter(messages)
        
        # Index 3 (orphaned tool call) should be dropped
        assert 3 not in result["surviving_indices"]
        assert result["dropped_count"] == 1


class TestTruncationLogic:
    """Test truncation index calculation."""

    def test_always_keeps_first(self, transport):
        """Index 0 is always in the result."""
        tokens = [1000, 2000, 3000, 4000]
        
        indices = message_transport.truncation_indices(tokens, protected_tokens=100)
        
        assert 0 in indices

    def test_keeps_from_end_within_budget(self, transport):
        """Messages from end are kept within budget."""
        # 4 messages: [100, 100, 100, 100]
        tokens = [100, 100, 100, 100]
        
        # Budget of 250 = index 0 (100) + from end until 250
        indices = message_transport.truncation_indices(tokens, protected_tokens=250)
        
        assert 0 in indices
        # Should include index 3 (100 tokens from end)
        assert 3 in indices

    def test_protects_thinking_message(self, transport):
        """second_has_thinking=True keeps index 1."""
        tokens = [100, 50, 200, 300, 400]
        
        indices = message_transport.truncation_indices(
            tokens, protected_tokens=200, second_has_thinking=True
        )
        
        assert 0 in indices
        assert 1 in indices  # Protected thinking message


class TestSplitForSummarization:
    """Test message splitting for summarization."""

    def test_protects_first_and_tail(self, transport):
        """First message and tail messages are protected."""
        messages = [
            {"kind": "request", "parts": []},
            {"kind": "response", "parts": []},
            {"kind": "request", "parts": []},
            {"kind": "response", "parts": []},
        ]
        tokens = [100, 200, 150, 250]  # total 700
        
        result = message_transport.split_for_summarization(
            tokens, messages, protected_tokens_limit=400
        )
        
        # Index 0 always protected
        assert 0 in result["protected_indices"]
        # Some tail messages protected
        assert len(result["protected_indices"]) >= 1
        # Remaining go to summarize
        assert isinstance(result["summarize_indices"], list)

    def test_small_history_no_summarization(self, transport):
        """Small histories have nothing to summarize."""
        messages = [{"kind": "request", "parts": []}]
        tokens = [100]
        
        result = message_transport.split_for_summarization(
            tokens, messages, protected_tokens_limit=500
        )
        
        assert result["summarize_indices"] == []
        assert result["protected_indices"] == [0]
