"""
Integration tests for message RPC - Python -> Elixir message flow.

These tests verify real Elixir backend behavior with actual message data.
Unlike test_message_transport.py which uses basic patterns, these tests focus on:
- End-to-end data integrity
- Consistency guarantees
- Real-world message patterns
"""

import pytest

# Skip all tests if Elixir transport isn't available
try:
    from code_puppy import message_transport
    from code_puppy.elixir_transport import ElixirTransportError
    from code_puppy.elixir_transport_helpers import health_check

    # Actually test if transport works by trying a health check
    try:
        health_check()
        TRANSPORT_AVAILABLE = True
    except Exception:
        TRANSPORT_AVAILABLE = False
except ImportError:
    TRANSPORT_AVAILABLE = False
    message_transport = None  # type: ignore
    ElixirTransportError = Exception  # type: ignore

pytestmark = [
    pytest.mark.skipif(
        not TRANSPORT_AVAILABLE, reason="Elixir transport not available"
    ),
    pytest.mark.integration,
]


class TestRoundTripSerialization:
    """Tests verifying serialize -> deserialize preserves message integrity."""

    def test_simple_text_messages_roundtrip(self):
        """Serialize and deserialize simple text messages - content matches exactly."""
        messages = [
            {
                "kind": "request",
                "role": "user",
                "parts": [{"part_kind": "text", "content": "Hello, world!"}],
            },
            {
                "kind": "response",
                "role": "assistant",
                "parts": [
                    {"part_kind": "text", "content": "Hi there! How can I help?"}
                ],
            },
        ]

        # Serialize to binary
        data = message_transport.serialize_session(messages)
        assert isinstance(data, bytes)
        assert len(data) > 0

        # Deserialize back
        restored = message_transport.deserialize_session(data)

        # Verify structure preserved
        assert len(restored) == 2
        assert restored[0]["kind"] == "request"
        assert restored[0]["role"] == "user"
        assert restored[1]["kind"] == "response"
        assert restored[1]["role"] == "assistant"

        # Verify content matches exactly
        assert restored[0]["parts"][0]["part_kind"] == "text"
        assert restored[0]["parts"][0]["content"] == "Hello, world!"
        assert restored[1]["parts"][0]["part_kind"] == "text"
        assert restored[1]["parts"][0]["content"] == "Hi there! How can I help?"

    def test_complex_messages_with_tool_calls_roundtrip(self):
        """Serialize messages with tool calls - tool data preserved exactly."""
        messages = [
            {
                "kind": "request",
                "role": "user",
                "parts": [{"part_kind": "text", "content": "Read file test.py"}],
            },
            {
                "kind": "response",
                "role": "assistant",
                "parts": [
                    {
                        "part_kind": "tool-call",
                        "tool_name": "read_file",
                        "tool_call_id": "call_abc123",
                        "args": {"file_path": "test.py"},
                    }
                ],
            },
            {
                "kind": "request",
                "role": "tool",
                "parts": [
                    {
                        "part_kind": "tool-return",
                        "tool_call_id": "call_abc123",
                        "tool_name": "read_file",
                        "content": "def hello():\n    pass\n",
                    }
                ],
            },
            {
                "kind": "response",
                "role": "assistant",
                "parts": [
                    {"part_kind": "text", "content": "Here's the file content..."}
                ],
            },
        ]

        # Round-trip
        data = message_transport.serialize_session(messages)
        restored = message_transport.deserialize_session(data)

        # Verify all messages preserved
        assert len(restored) == 4

        # Verify tool call preserved
        tool_call = restored[1]["parts"][0]
        assert tool_call["part_kind"] == "tool-call"
        assert tool_call["tool_name"] == "read_file"
        assert tool_call["tool_call_id"] == "call_abc123"
        assert tool_call["args"]["file_path"] == "test.py"

        # Verify tool return preserved
        tool_return = restored[2]["parts"][0]
        assert tool_return["part_kind"] == "tool-return"
        assert tool_return["tool_call_id"] == "call_abc123"
        assert tool_return["content"] == "def hello():\n    pass\n"

    def test_unicode_content_roundtrip(self):
        """Unicode content survives serialization round-trip."""
        messages = [
            {
                "kind": "request",
                "role": "user",
                "parts": [
                    {
                        "part_kind": "text",
                        "content": "Hello 世界 🌍 ñáéíóú «»",
                    }
                ],
            }
        ]

        data = message_transport.serialize_session(messages)
        restored = message_transport.deserialize_session(data)

        # Verify exact Unicode preservation
        assert restored[0]["parts"][0]["content"] == "Hello 世界 🌍 ñáéíóú «»"

    def test_incremental_serialization_roundtrip(self):
        """Incremental serialization appends correctly and round-trips."""
        # First batch
        batch1 = [
            {
                "kind": "request",
                "role": "user",
                "parts": [{"part_kind": "text", "content": "First"}],
            },
            {
                "kind": "response",
                "role": "assistant",
                "parts": [{"part_kind": "text", "content": "Response 1"}],
            },
        ]

        # Serialize first batch
        data = message_transport.serialize_incremental(batch1, None)
        assert isinstance(data, bytes)

        # Second batch
        batch2 = [
            {
                "kind": "request",
                "role": "user",
                "parts": [{"part_kind": "text", "content": "Second"}],
            },
            {
                "kind": "response",
                "role": "assistant",
                "parts": [{"part_kind": "text", "content": "Response 2"}],
            },
        ]

        # Append second batch
        data = message_transport.serialize_incremental(batch2, data)

        # Deserialize and verify all 4 messages
        restored = message_transport.deserialize_session(data)
        assert len(restored) == 4
        assert restored[0]["parts"][0]["content"] == "First"
        assert restored[1]["parts"][0]["content"] == "Response 1"
        assert restored[2]["parts"][0]["content"] == "Second"
        assert restored[3]["parts"][0]["content"] == "Response 2"


class TestPruningPreservesIntegrity:
    """Tests verifying prune_and_filter preserves surviving message integrity."""

    def test_pruning_keeps_message_content_intact(self):
        """When messages are pruned, surviving messages remain unchanged."""
        messages = [
            {
                "kind": "request",
                "role": "user",
                "parts": [
                    {"part_kind": "text", "content": "First message - must survive"}
                ],
            },
            {
                "kind": "response",
                "role": "assistant",
                "parts": [
                    {
                        "part_kind": "tool-call",
                        "tool_call_id": "orphan-123",
                        "tool_name": "orphaned_tool",
                        "args": {"some": "data"},
                    }
                ],
            },
            {
                "kind": "request",
                "role": "user",
                "parts": [
                    {"part_kind": "text", "content": "Third message - must survive"}
                ],
            },
        ]

        result = message_transport.prune_and_filter(messages)

        # Verify surviving indices are valid
        assert 0 in result["surviving_indices"]
        assert 2 in result["surviving_indices"]
        assert 1 not in result["surviving_indices"]  # Orphaned tool call dropped

        # Verify surviving messages are completely intact
        surviving = [messages[i] for i in result["surviving_indices"]]

        # First message unchanged
        assert surviving[0]["kind"] == "request"
        assert surviving[0]["role"] == "user"
        assert surviving[0]["parts"][0]["content"] == "First message - must survive"

        # Third message unchanged
        assert surviving[1]["kind"] == "request"
        assert surviving[1]["role"] == "user"
        assert surviving[1]["parts"][0]["content"] == "Third message - must survive"

    def test_complete_conversation_pruning_preserves_integrity(self):
        """Pruning a complete conversation preserves all messages."""
        messages = [
            {
                "kind": "request",
                "role": "user",
                "parts": [{"part_kind": "text", "content": "Call a tool"}],
            },
            {
                "kind": "response",
                "role": "assistant",
                "parts": [
                    {
                        "part_kind": "tool-call",
                        "tool_call_id": "call_001",
                        "tool_name": "test_tool",
                        "args": {},
                    }
                ],
            },
            {
                "kind": "request",
                "role": "tool",
                "parts": [
                    {
                        "part_kind": "tool-return",
                        "tool_call_id": "call_001",
                        "tool_name": "test_tool",
                        "content": "Tool result",
                    }
                ],
            },
            {
                "kind": "response",
                "role": "assistant",
                "parts": [{"part_kind": "text", "content": "Done!"}],
            },
        ]

        result = message_transport.prune_and_filter(messages)

        # All messages should survive (no orphans)
        assert result["dropped_count"] == 0
        assert result["had_pending_tool_calls"] is False
        assert len(result["surviving_indices"]) == 4

        # Verify each surviving message is intact
        for i in result["surviving_indices"]:
            assert messages[i]["kind"] in ["request", "response"]
            assert len(messages[i]["parts"]) > 0

    def test_large_message_dropped_others_preserved(self):
        """When a message exceeds token limit, other messages remain intact."""
        messages = [
            {
                "kind": "request",
                "role": "user",
                "parts": [{"part_kind": "text", "content": "Small message 1"}],
            },
            {
                "kind": "request",
                "role": "user",
                "parts": [
                    {"part_kind": "text", "content": "x" * 100}
                ],  # Will exceed 50 token limit
            },
            {
                "kind": "request",
                "role": "user",
                "parts": [{"part_kind": "text", "content": "Small message 3"}],
            },
        ]

        result = message_transport.prune_and_filter(messages, max_tokens_per_message=50)

        # Middle message dropped
        assert 1 not in result["surviving_indices"]
        # Surviving messages intact
        assert 0 in result["surviving_indices"]
        assert 2 in result["surviving_indices"]

        # Verify surviving messages unchanged
        surviving = [messages[i] for i in result["surviving_indices"]]
        assert surviving[0]["parts"][0]["content"] == "Small message 1"
        assert surviving[1]["parts"][0]["content"] == "Small message 3"


class TestHashConsistency:
    """Tests verifying hash consistency guarantees."""

    def test_same_message_same_hash(self):
        """Hashing the same message multiple times produces identical hash."""
        message = {
            "kind": "request",
            "role": "user",
            "parts": [
                {"part_kind": "text", "content": "Test content for hashing"},
                {"part_kind": "text", "content": "More content"},
            ],
        }

        # Hash multiple times
        hash1 = message_transport.hash_message(message)
        hash2 = message_transport.hash_message(message)
        hash3 = message_transport.hash_message(message)

        # All hashes must be identical
        assert hash1 == hash2 == hash3
        assert isinstance(hash1, int)
        assert hash1 >= 0

    def test_hash_consistent_across_identical_complex_messages(self):
        """Complex messages with same content produce same hash."""
        message1 = {
            "kind": "response",
            "role": "assistant",
            "parts": [
                {
                    "part_kind": "tool-call",
                    "tool_name": "read_file",
                    "tool_call_id": "call_123",
                    "args": {"file_path": "test.py"},
                },
                {"part_kind": "text", "content": "Here's the file"},
            ],
        }

        message2 = {
            "kind": "response",
            "role": "assistant",
            "parts": [
                {
                    "part_kind": "tool-call",
                    "tool_name": "read_file",
                    "tool_call_id": "call_123",
                    "args": {"file_path": "test.py"},
                },
                {"part_kind": "text", "content": "Here's the file"},
            ],
        }

        hash1 = message_transport.hash_message(message1)
        hash2 = message_transport.hash_message(message2)

        assert hash1 == hash2

    def test_different_content_different_hash(self):
        """Different message content produces different hash values."""
        messages = [
            {
                "kind": "request",
                "role": "user",
                "parts": [{"part_kind": "text", "content": "A"}],
            },
            {
                "kind": "request",
                "role": "user",
                "parts": [{"part_kind": "text", "content": "B"}],
            },
            {
                "kind": "request",
                "role": "user",
                "parts": [{"part_kind": "text", "content": "C"}],
            },
        ]

        hashes = [message_transport.hash_message(m) for m in messages]

        # All hashes should be different
        assert len(set(hashes)) == 3

    def test_batch_hash_consistency(self):
        """Batch hashing produces same results as individual hashing."""
        messages = [
            {
                "kind": "request",
                "role": "user",
                "parts": [{"part_kind": "text", "content": "First"}],
            },
            {
                "kind": "response",
                "role": "assistant",
                "parts": [{"part_kind": "text", "content": "Second"}],
            },
            {
                "kind": "request",
                "role": "user",
                "parts": [{"part_kind": "text", "content": "Third"}],
            },
        ]

        # Individual hashes
        individual_hashes = [message_transport.hash_message(m) for m in messages]

        # Batch hash
        batch_hashes = message_transport.hash_batch(messages)

        # Results must match
        assert individual_hashes == batch_hashes

    def test_hash_stability_for_tool_pairs(self):
        """Tool call/return pairs maintain hash stability."""
        tool_call = {
            "kind": "response",
            "role": "assistant",
            "parts": [
                {
                    "part_kind": "tool-call",
                    "tool_name": "test_tool",
                    "tool_call_id": "pair_001",
                    "args": {"key": "value"},
                }
            ],
        }

        tool_return = {
            "kind": "request",
            "role": "tool",
            "parts": [
                {
                    "part_kind": "tool-return",
                    "tool_call_id": "pair_001",
                    "tool_name": "test_tool",
                    "content": "Result data",
                }
            ],
        }

        # Hash each multiple times
        call_hashes = [message_transport.hash_message(tool_call) for _ in range(5)]
        return_hashes = [message_transport.hash_message(tool_return) for _ in range(5)]

        # Each set should be internally consistent
        assert len(set(call_hashes)) == 1
        assert len(set(return_hashes)) == 1

        # But call and return should be different
        assert call_hashes[0] != return_hashes[0]


class TestCrossOperationIntegrity:
    """Tests verifying operations work correctly in sequence."""

    def test_serialize_then_prune_consistency(self):
        """Messages survive serialize -> deserialize -> prune pipeline."""
        messages = [
            {
                "kind": "request",
                "role": "user",
                "parts": [{"part_kind": "text", "content": "Hello"}],
            },
            {
                "kind": "response",
                "role": "assistant",
                "parts": [{"part_kind": "text", "content": "Hi!"}],
            },
        ]

        # Serialize and deserialize
        data = message_transport.serialize_session(messages)
        restored = message_transport.deserialize_session(data)

        # Now prune the restored messages
        result = message_transport.prune_and_filter(restored)

        # All should survive
        assert result["surviving_indices"] == [0, 1]
        assert result["dropped_count"] == 0

    def test_hash_after_serialization_consistency(self):
        """Hash values consistent before and after serialization round-trip."""
        message = {
            "kind": "request",
            "role": "user",
            "parts": [{"part_kind": "text", "content": "Consistency test"}],
        }

        # Hash before serialization
        hash_before = message_transport.hash_message(message)

        # Serialize and deserialize
        data = message_transport.serialize_session([message])
        restored = message_transport.deserialize_session(data)

        # Hash after deserialization
        hash_after = message_transport.hash_message(restored[0])

        # Hashes should match
        assert hash_before == hash_after
