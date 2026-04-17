"""Tests for message_transport module (bd-113).

These tests verify the Python -> Elixir RPC integration for message processing.
They require the Elixir StdioService to be running.
"""

import pytest

# Skip all tests if Elixir transport isn't available
try:
    from code_puppy import message_transport
    from code_puppy.elixir_transport import ElixirTransportError
    TRANSPORT_AVAILABLE = True
except ImportError:
    TRANSPORT_AVAILABLE = False
    message_transport = None  # type: ignore
    ElixirTransportError = Exception  # type: ignore

pytestmark = [
    pytest.mark.skipif(not TRANSPORT_AVAILABLE, reason="Elixir transport not available"),
    pytest.mark.integration,
]


class TestPruneAndFilter:
    """Tests for prune_and_filter RPC."""
    
    def test_prunes_orphaned_tool_calls(self):
        """Messages with orphaned tool_call_ids are dropped."""
        messages = [
            {
                "kind": "request",
                "role": "user",
                "parts": [{"part_kind": "text", "content": "Hello"}],
            },
            {
                "kind": "response",
                "role": "assistant",
                "parts": [
                    {
                        "part_kind": "tool-call",
                        "tool_call_id": "orphan-123",
                        "tool_name": "test_tool",
                    }
                ],
            },
        ]
        
        result = message_transport.prune_and_filter(messages)
        
        assert result["surviving_indices"] == [0]
        assert result["dropped_count"] == 1
        assert result["had_pending_tool_calls"] is True
        assert result["pending_tool_call_count"] == 1
    
    def test_keeps_complete_messages(self):
        """Messages without issues are preserved."""
        messages = [
            {
                "kind": "request",
                "role": "user",
                "parts": [{"part_kind": "text", "content": "Hello"}],
            },
            {
                "kind": "response",
                "role": "assistant",
                "parts": [{"part_kind": "text", "content": "Hi there!"}],
            },
        ]
        
        result = message_transport.prune_and_filter(messages)
        
        assert result["surviving_indices"] == [0, 1]
        assert result["dropped_count"] == 0
        assert result["had_pending_tool_calls"] is False


class TestTruncationIndices:
    """Tests for truncation_indices RPC."""
    
    def test_always_keeps_first_message(self):
        """Index 0 is always preserved."""
        per_message_tokens = [1000, 2000, 3000]
        
        indices = message_transport.truncation_indices(
            per_message_tokens, protected_tokens=500
        )
        
        assert 0 in indices
    
    def test_respects_budget(self):
        """Messages from end are kept within budget."""
        # 5 messages: [100, 200, 300, 400, 500] = 1500 total
        per_message_tokens = [100, 200, 300, 400, 500]
        
        # Budget of 700 should keep index 0 + some from end
        indices = message_transport.truncation_indices(
            per_message_tokens, protected_tokens=700
        )
        
        assert 0 in indices
        # Should include index 4 (500 tokens) and maybe index 3
        assert len(indices) >= 2
    
    def test_protects_second_with_thinking(self):
        """second_has_thinking=True protects index 1."""
        per_message_tokens = [100, 50, 200, 300]
        
        indices = message_transport.truncation_indices(
            per_message_tokens,
            protected_tokens=400,
            second_has_thinking=True,
        )
        
        assert 0 in indices
        assert 1 in indices


class TestSplitForSummarization:
    """Tests for split_for_summarization RPC."""
    
    def test_splits_messages(self):
        """Messages are split into summarize and protected groups."""
        messages = [
            {"kind": "request", "parts": []},
            {"kind": "response", "parts": []},
            {"kind": "request", "parts": []},
            {"kind": "response", "parts": []},
        ]
        per_message_tokens = [100, 200, 150, 250]
        
        result = message_transport.split_for_summarization(
            per_message_tokens, messages, protected_tokens_limit=400
        )
        
        assert "summarize_indices" in result
        assert "protected_indices" in result
        assert "protected_token_count" in result
        assert isinstance(result["summarize_indices"], list)
        assert isinstance(result["protected_indices"], list)
        # Index 0 is always protected
        assert 0 in result["protected_indices"]


class TestSerializeSessjon:
    """Tests for serialize_session and deserialize_session RPC."""
    
    def test_roundtrip(self):
        """Serialize then deserialize preserves messages."""
        messages = [
            {
                "kind": "request",
                "role": "user",
                "parts": [{"part_kind": "text", "content": "Hello world"}],
            },
            {
                "kind": "response",
                "role": "assistant",
                "parts": [{"part_kind": "text", "content": "Hi!"}],
            },
        ]
        
        # Serialize
        data = message_transport.serialize_session(messages)
        assert isinstance(data, bytes)
        assert len(data) > 0
        
        # Deserialize
        restored = message_transport.deserialize_session(data)
        assert len(restored) == 2
        assert restored[0]["kind"] == "request"
        assert restored[1]["kind"] == "response"
    
    def test_incremental_serialization(self):
        """serialize_incremental appends to existing data."""
        initial = [{"kind": "request", "parts": []}]
        data = message_transport.serialize_session(initial)
        
        more = [{"kind": "response", "parts": []}]
        combined_data = message_transport.serialize_incremental(more, data)
        
        restored = message_transport.deserialize_session(combined_data)
        assert len(restored) == 2
    
    def test_incremental_fresh_start(self):
        """serialize_incremental with None creates fresh data."""
        messages = [{"kind": "request", "parts": []}]
        
        data = message_transport.serialize_incremental(messages, None)
        assert isinstance(data, bytes)
        
        restored = message_transport.deserialize_session(data)
        assert len(restored) == 1


class TestHashMessage:
    """Tests for hash_message and hash_batch RPC."""
    
    def test_consistent_hash(self):
        """Same message produces same hash."""
        message = {
            "kind": "request",
            "role": "user",
            "parts": [{"part_kind": "text", "content": "Test content"}],
        }
        
        hash1 = message_transport.hash_message(message)
        hash2 = message_transport.hash_message(message)
        
        assert hash1 == hash2
        assert isinstance(hash1, int)
        assert hash1 >= 0
    
    def test_different_content_different_hash(self):
        """Different content produces different hash."""
        msg1 = {"kind": "request", "parts": [{"part_kind": "text", "content": "A"}]}
        msg2 = {"kind": "request", "parts": [{"part_kind": "text", "content": "B"}]}
        
        hash1 = message_transport.hash_message(msg1)
        hash2 = message_transport.hash_message(msg2)
        
        assert hash1 != hash2
    
    def test_batch_hash(self):
        """hash_batch returns list of hashes."""
        messages = [
            {"kind": "request", "parts": []},
            {"kind": "response", "parts": []},
        ]
        
        hashes = message_transport.hash_batch(messages)
        
        assert len(hashes) == 2
        assert all(isinstance(h, int) for h in hashes)
        assert all(h >= 0 for h in hashes)


class TestStringifyPart:
    """Tests for stringify_part RPC."""
    
    def test_text_part(self):
        """Text parts are stringified correctly."""
        part = {"part_kind": "text", "content": "Hello"}
        
        result = message_transport.stringify_part(part)
        
        assert "text" in result
        assert "content=Hello" in result
    
    def test_tool_call_part(self):
        """Tool call parts include tool_name."""
        part = {
            "part_kind": "tool-call",
            "tool_name": "read_file",
            "tool_call_id": "abc123",
        }
        
        result = message_transport.stringify_part(part)
        
        assert "tool-call" in result
        assert "tool_name=read_file" in result
        assert "tool_call_id=abc123" in result
