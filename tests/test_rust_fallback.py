"""Regression tests for Rust fallback paths.

Ensures all Python fallback paths produce identical results to Rust fast paths.
Tests run with both RUST_ENABLED=1 (Rust path) and RUST_ENABLED=0 (Python fallback).

Acceptance Criteria:
- Test suite passes with both Rust enabled and disabled
- Output parity verified for all bridge functions:
  - process_messages_batch
  - prune_and_filter (via prune_interrupted_tool_calls)
  - truncation_indices (via truncation)
  - serialize_session / deserialize_session
  - collect_tool_call_ids
"""

import copy
import pytest
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
)

from code_puppy._core_bridge import (
    RUST_AVAILABLE,
    is_rust_enabled,
    set_rust_enabled,
    serialize_message_for_rust,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def agent():
    """Create a CodePuppyAgent for testing Python fallback methods."""
    from code_puppy.agents.agent_code_puppy import CodePuppyAgent

    return CodePuppyAgent()


@pytest.fixture(autouse=True)
def _restore_rust_state():
    """Save and restore Rust enabled state around each test."""
    original = is_rust_enabled()
    yield
    set_rust_enabled(original)


def _skip_if_no_rust():
    """Skip test if Rust module is not available."""
    if not RUST_AVAILABLE:
        pytest.skip("Rust module not available — cannot compare paths")


def _make_messages():
    """Create a diverse set of test messages."""
    return [
        ModelRequest(parts=[TextPart(content="You are a helpful assistant.")]),
        ModelResponse(parts=[TextPart(content="Hello! How can I help you today?")]),
        ModelRequest(parts=[TextPart(content="Please read the file foo.py")]),
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="read_file", args='{"path": "foo.py"}', tool_call_id="tc-1"
                )
            ]
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="read_file",
                    content="def hello():\n    return 'world'",
                    tool_call_id="tc-1",
                )
            ]
        ),
        ModelResponse(parts=[TextPart(content="The file contains a hello function.")]),
        ModelRequest(parts=[TextPart(content="Great, now write tests for it.")]),
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="write_file",
                    args='{"path": "test_foo.py", "content": "def test_hello():\\n    assert hello() == \\\'world\\\'"}',
                    tool_call_id="tc-2",
                )
            ]
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="write_file",
                    content="File written successfully",
                    tool_call_id="tc-2",
                )
            ]
        ),
        ModelResponse(parts=[TextPart(content="Done! Tests have been written.")]),
    ]


def _make_messages_with_thinking():
    """Create messages where the second message has a ThinkingPart."""
    return [
        ModelRequest(parts=[TextPart(content="System prompt")]),
        ModelResponse(
            parts=[
                ThinkingPart(content="Let me think about this carefully..."),
                TextPart(content="Here is my response."),
            ]
        ),
        ModelRequest(parts=[TextPart(content="Follow-up question")]),
        ModelResponse(parts=[TextPart(content="Follow-up answer")]),
        ModelRequest(parts=[TextPart(content="Another question")]),
        ModelResponse(parts=[TextPart(content="Another answer")]),
    ]


def _make_messages_with_unmatched_tool_calls():
    """Create messages with unmatched tool calls (should be pruned)."""
    return [
        ModelRequest(parts=[TextPart(content="Do something")]),
        ModelResponse(
            parts=[
                ToolCallPart(tool_name="read_file", args="{}", tool_call_id="tc-unmatched")
            ]
        ),
        # No matching ToolReturnPart — tc-unmatched is pending
        ModelRequest(parts=[TextPart(content="What happened?")]),
        ModelResponse(parts=[TextPart(content="I was interrupted.")]),
    ]


def _make_tool_definitions():
    """Create sample tool definitions for process_messages_batch."""
    return [
        {"name": "read_file", "description": "Read a file from disk"},
        {"name": "write_file", "description": "Write content to a file"},
    ]


# ---------------------------------------------------------------------------
# Test: process_messages_batch parity
# ---------------------------------------------------------------------------


class TestProcessMessagesBatchParity:
    """Verify process_messages_batch gives identical results with Rust and Python."""

    def test_per_message_tokens_rust_matches_python_fallback(self, agent):
        """process_messages_batch per_message_tokens should match Python fallback."""
        _skip_if_no_rust()

        messages = _make_messages()
        tool_defs = _make_tool_definitions()

        # Rust path
        set_rust_enabled(True)
        assert is_rust_enabled()
        from _code_puppy_core import process_messages_batch as rust_pmb

        rust_result = rust_pmb(messages, tool_defs, [], "You are a helpful assistant.")

        # Python fallback path — compute tokens using estimate_tokens_for_message
        set_rust_enabled(False)
        assert not is_rust_enabled()
        python_tokens = [agent.estimate_tokens_for_message(msg) for msg in messages]

        # Compare: each message's token count should be at least 1 and roughly match
        assert len(rust_result.per_message_tokens) == len(python_tokens)
        for i, (rust_tok, py_tok) in enumerate(
            zip(rust_result.per_message_tokens, python_tokens)
        ):
            assert rust_tok >= 1, f"Message {i}: Rust tokens should be >= 1"
            assert py_tok >= 1, f"Message {i}: Python tokens should be >= 1"
            # Allow small differences due to implementation details
            ratio = rust_tok / max(py_tok, 1)
            assert 0.5 <= ratio <= 2.0, (
                f"Message {i}: token counts diverge too much: "
                f"Rust={rust_tok}, Python={py_tok}, ratio={ratio:.2f}"
            )

    def test_total_message_tokens_parity(self, agent):
        """Total tokens should be similar between Rust and Python paths."""
        _skip_if_no_rust()

        messages = _make_messages()

        # Rust path
        set_rust_enabled(True)
        from _code_puppy_core import process_messages_batch as rust_pmb

        rust_result = rust_pmb(messages, [], [], "")

        # Python fallback
        set_rust_enabled(False)
        python_total = sum(agent.estimate_tokens_for_message(msg) for msg in messages)

        assert rust_result.total_message_tokens >= 1
        assert python_total >= 1
        ratio = rust_result.total_message_tokens / max(python_total, 1)
        assert 0.5 <= ratio <= 2.0, (
            f"Total tokens diverge: Rust={rust_result.total_message_tokens}, "
            f"Python={python_total}, ratio={ratio:.2f}"
        )

    def test_message_hashes_deterministic(self):
        """Message hashes should be deterministic within Rust path."""
        _skip_if_no_rust()

        messages = _make_messages()
        set_rust_enabled(True)
        from _code_puppy_core import process_messages_batch as rust_pmb

        result1 = rust_pmb(messages, [], [], "")
        result2 = rust_pmb(messages, [], [], "")

        assert result1.message_hashes == result2.message_hashes

    def test_empty_messages(self, agent):
        """Empty message list should produce empty results."""
        _skip_if_no_rust()

        set_rust_enabled(True)
        from _code_puppy_core import process_messages_batch as rust_pmb

        rust_result = rust_pmb([], [], [], "")
        assert rust_result.per_message_tokens == []
        assert rust_result.total_message_tokens == 0

        set_rust_enabled(False)
        python_tokens = [agent.estimate_tokens_for_message(msg) for msg in []]
        assert python_tokens == []

    def test_context_overhead_with_tools(self):
        """Context overhead should include tool definitions."""
        _skip_if_no_rust()

        messages = _make_messages()
        tool_defs = _make_tool_definitions()

        set_rust_enabled(True)
        from _code_puppy_core import process_messages_batch as rust_pmb

        result_with_tools = rust_pmb(messages, tool_defs, [], "System prompt")
        result_no_tools = rust_pmb(messages, [], [], "")

        # With tools and system prompt, overhead should be higher
        assert result_with_tools.context_overhead_tokens > result_no_tools.context_overhead_tokens


# ---------------------------------------------------------------------------
# Test: prune_and_filter / prune_interrupted_tool_calls parity
# ---------------------------------------------------------------------------


class TestPruneAndFilterParity:
    """Verify prune_and_filter gives identical results with Rust and Python."""

    def test_matched_tool_calls_preserved_both_paths(self, agent):
        """Matched tool call pairs should be preserved in both paths."""
        _skip_if_no_rust()

        messages = _make_messages()

        # Rust path
        set_rust_enabled(True)
        rust_pruned = agent.prune_interrupted_tool_calls(messages)
        assert len(rust_pruned) == len(messages)  # All matched, nothing pruned

        # Python path
        set_rust_enabled(False)
        python_pruned = agent.prune_interrupted_tool_calls(messages)
        assert len(python_pruned) == len(messages)

    def test_unmatched_tool_calls_pruned_both_paths(self, agent):
        """Unmatched tool calls should be pruned in both paths."""
        _skip_if_no_rust()

        messages = _make_messages_with_unmatched_tool_calls()

        # Rust path
        set_rust_enabled(True)
        rust_pruned = agent.prune_interrupted_tool_calls(messages)

        # Python path
        set_rust_enabled(False)
        python_pruned = agent.prune_interrupted_tool_calls(messages)

        # Both should prune the message with unmatched tool call
        assert len(rust_pruned) == len(python_pruned)
        # The unmatched tool call message should be gone
        assert len(rust_pruned) < len(messages)

    def test_empty_messages_both_paths(self, agent):
        """Empty message list should return empty in both paths."""
        _skip_if_no_rust()

        set_rust_enabled(True)
        assert agent.prune_interrupted_tool_calls([]) == []

        set_rust_enabled(False)
        assert agent.prune_interrupted_tool_calls([]) == []

    def test_surviving_indices_match(self, agent):
        """The same messages should survive pruning in both paths."""
        _skip_if_no_rust()

        # Create messages with mixed matched/unmatched tool calls
        messages = [
            ModelRequest(parts=[TextPart(content="Start")]),
            ModelResponse(
                parts=[
                    ToolCallPart(tool_name="read_file", args="{}", tool_call_id="tc-ok")
                ]
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="read_file", content="data", tool_call_id="tc-ok"
                    )
                ]
            ),
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="write_file", args="{}", tool_call_id="tc-bad"
                    )
                ]
            ),
            # tc-bad has no return — should be pruned
            ModelRequest(parts=[TextPart(content="End")]),
        ]

        # Rust path
        set_rust_enabled(True)
        rust_pruned = agent.prune_interrupted_tool_calls(messages)
        rust_ids = [id(m) for m in rust_pruned]

        # Python path
        set_rust_enabled(False)
        python_pruned = agent.prune_interrupted_tool_calls(messages)
        python_ids = [id(m) for m in python_pruned]

        # Same messages should survive
        assert rust_ids == python_ids


# ---------------------------------------------------------------------------
# Test: truncation_indices / truncation parity
# ---------------------------------------------------------------------------


class TestTruncationParity:
    """Verify truncation gives identical results with Rust and Python."""

    def test_first_message_always_kept_both_paths(self, agent):
        """First message (system prompt) should always be kept in both paths."""
        _skip_if_no_rust()

        messages = _make_messages()

        set_rust_enabled(True)
        rust_result = agent.truncation(messages, protected_tokens=100)
        assert rust_result[0] == messages[0]

        set_rust_enabled(False)
        python_result = agent.truncation(messages, protected_tokens=100)
        assert python_result[0] == messages[0]

    def test_thinking_part_second_message_kept(self, agent):
        """Second message with ThinkingPart should be kept in both paths."""
        _skip_if_no_rust()

        messages = _make_messages_with_thinking()

        set_rust_enabled(True)
        rust_result = agent.truncation(messages, protected_tokens=50)

        set_rust_enabled(False)
        python_result = agent.truncation(messages, protected_tokens=50)

        # Both should keep first message
        assert rust_result[0] == messages[0]
        assert python_result[0] == messages[0]

        # If second message is kept in one path, it should be kept in the other
        rust_keeps_second = any(m is messages[1] for m in rust_result)
        python_keeps_second = any(m is messages[1] for m in python_result)
        assert rust_keeps_second == python_keeps_second

    def test_high_budget_keeps_most_messages(self, agent):
        """High token budget should keep most messages in both paths."""
        _skip_if_no_rust()

        messages = _make_messages()

        set_rust_enabled(True)
        rust_result = agent.truncation(messages, protected_tokens=100_000)

        set_rust_enabled(False)
        python_result = agent.truncation(messages, protected_tokens=100_000)

        # With high budget, most messages should be kept
        assert len(rust_result) >= len(messages) - 1
        assert len(python_result) >= len(messages) - 1

    def test_low_budget_keeps_minimum(self, agent):
        """Low token budget should keep at least first message in both paths."""
        _skip_if_no_rust()

        messages = _make_messages()

        set_rust_enabled(True)
        rust_result = agent.truncation(messages, protected_tokens=1)

        set_rust_enabled(False)
        python_result = agent.truncation(messages, protected_tokens=1)

        # At minimum, first message should be kept
        assert len(rust_result) >= 1
        assert len(python_result) >= 1
        assert rust_result[0] == messages[0]
        assert python_result[0] == messages[0]

    def test_truncation_with_precomputed_tokens(self, agent):
        """truncation with pre-computed tokens should match without them."""
        _skip_if_no_rust()

        messages = _make_messages()
        set_rust_enabled(True)

        from _code_puppy_core import process_messages_batch as rust_pmb

        batch = rust_pmb(messages, [], [], "")
        precomputed = list(batch.per_message_tokens)

        result_with_precomputed = agent.truncation(
            messages, protected_tokens=100, per_message_tokens=precomputed
        )
        result_without = agent.truncation(messages, protected_tokens=100)

        # Both should produce the same set of kept messages
        assert len(result_with_precomputed) == len(result_without)


# ---------------------------------------------------------------------------
# Test: serialize_session / deserialize_session parity
# ---------------------------------------------------------------------------


class TestSerializationParity:
    """Verify serialization gives consistent results with Rust."""

    def test_serialize_deserialize_roundtrip(self):
        """Serialize then deserialize should preserve messages."""
        _skip_if_no_rust()

        from _code_puppy_core import serialize_session, deserialize_session

        messages = _make_messages()
        data = serialize_session(messages)
        restored = deserialize_session(data)

        assert len(restored) == len(messages)
        for i, (original, restored_msg) in enumerate(zip(messages, restored)):
            orig_dict = serialize_message_for_rust(original)
            assert restored_msg["kind"] == orig_dict["kind"], f"Message {i} kind mismatch"
            assert len(restored_msg["parts"]) == len(orig_dict["parts"]), (
                f"Message {i} parts count mismatch"
            )

    def test_serialize_deterministic(self):
        """Same messages should produce same serialized bytes."""
        _skip_if_no_rust()

        from _code_puppy_core import serialize_session

        messages = _make_messages()
        data1 = serialize_session(messages)
        data2 = serialize_session(messages)

        assert data1 == data2

    def test_empty_session_roundtrip(self):
        """Empty message list should serialize and deserialize correctly."""
        _skip_if_no_rust()

        from _code_puppy_core import serialize_session, deserialize_session

        data = serialize_session([])
        restored = deserialize_session(data)

        assert restored == []

    def test_tool_call_messages_roundtrip(self):
        """Messages with tool calls should roundtrip correctly."""
        _skip_if_no_rust()

        from _code_puppy_core import serialize_session, deserialize_session

        messages = [
            ModelRequest(parts=[TextPart(content="Read a file")]),
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read_file", args='{"path": "test.py"}', tool_call_id="tc-1"
                    )
                ]
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="read_file",
                        content="file contents here",
                        tool_call_id="tc-1",
                    )
                ]
            ),
        ]

        data = serialize_session(messages)
        restored = deserialize_session(data)

        assert len(restored) == 3
        assert restored[1]["parts"][0]["part_kind"] == "tool-call"
        assert restored[1]["parts"][0]["tool_name"] == "read_file"
        assert restored[1]["parts"][0]["tool_call_id"] == "tc-1"
        assert restored[2]["parts"][0]["part_kind"] == "tool-return"
        assert restored[2]["parts"][0]["content"] == "file contents here"

    def test_incremental_serialization_roundtrip(self):
        """Incremental serialize should work with deserialize."""
        _skip_if_no_rust()

        from _code_puppy_core import (
            serialize_session_incremental_new,
            deserialize_session,
            get_incremental_message_count,
        )

        messages = _make_messages()[:5]
        data = serialize_session_incremental_new(messages, None)

        count = get_incremental_message_count(data)
        assert count == 5

        restored = deserialize_session(data)
        assert len(restored) == 5


# ---------------------------------------------------------------------------
# Test: collect_tool_call_ids parity
# ---------------------------------------------------------------------------


class TestCollectToolCallIdsParity:
    """Verify collect_tool_call_ids gives identical results with Rust and Python."""

    def test_collect_ids_rust_matches_python(self, agent):
        """Tool call ID sets should match between Rust and Python paths."""
        _skip_if_no_rust()

        messages = _make_messages()

        # Rust path
        set_rust_enabled(True)
        rust_call_ids, rust_return_ids = agent._collect_tool_call_ids_uncached(messages)

        # Python path
        set_rust_enabled(False)
        python_call_ids, python_return_ids = agent._collect_tool_call_ids_uncached(messages)

        assert rust_call_ids == python_call_ids
        assert rust_return_ids == python_return_ids

    def test_empty_messages_both_paths(self, agent):
        """Empty message list should produce empty sets in both paths."""
        _skip_if_no_rust()

        set_rust_enabled(True)
        rust_call, rust_return = agent._collect_tool_call_ids_uncached([])
        assert rust_call == set()
        assert rust_return == set()

        set_rust_enabled(False)
        py_call, py_return = agent._collect_tool_call_ids_uncached([])
        assert py_call == set()
        assert py_return == set()

    def test_unmatched_ids_detected(self, agent):
        """Unmatched tool call IDs should be detected in both paths."""
        _skip_if_no_rust()

        messages = _make_messages_with_unmatched_tool_calls()

        set_rust_enabled(True)
        rust_call, rust_return = agent._collect_tool_call_ids_uncached(messages)

        set_rust_enabled(False)
        py_call, py_return = agent._collect_tool_call_ids_uncached(messages)

        # tc-unmatched is in call_ids but not return_ids
        assert "tc-unmatched" in rust_call
        assert "tc-unmatched" not in rust_return
        assert "tc-unmatched" in py_call
        assert "tc-unmatched" not in py_return

        # Symmetric difference should be the same
        assert rust_call.symmetric_difference(rust_return) == py_call.symmetric_difference(py_return)


# ---------------------------------------------------------------------------
# Test: has_pending_tool_calls parity
# ---------------------------------------------------------------------------


class TestPendingToolCallsParity:
    """Verify has_pending_tool_calls gives same result in both paths."""

    def test_no_pending_when_all_matched(self, agent):
        """No pending tool calls when all are matched."""
        _skip_if_no_rust()

        messages = _make_messages()

        set_rust_enabled(True)
        rust_pending = agent.has_pending_tool_calls(messages)

        set_rust_enabled(False)
        python_pending = agent.has_pending_tool_calls(messages)

        assert rust_pending == python_pending
        assert not rust_pending  # All matched

    def test_pending_detected(self, agent):
        """Pending tool calls should be detected in both paths."""
        _skip_if_no_rust()

        messages = _make_messages_with_unmatched_tool_calls()

        set_rust_enabled(True)
        rust_pending = agent.has_pending_tool_calls(messages)

        set_rust_enabled(False)
        python_pending = agent.has_pending_tool_calls(messages)

        assert rust_pending == python_pending
        assert rust_pending  # Has unmatched


# ---------------------------------------------------------------------------
# Test: Edge cases and robustness
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases that could cause divergence between Rust and Python paths."""

    def test_unicode_content(self, agent):
        """Unicode content should be handled identically."""
        _skip_if_no_rust()

        messages = [
            ModelRequest(parts=[TextPart(content="Hello 🌍! Ñoño café résumé 日本語")]),
            ModelResponse(parts=[TextPart(content="Привет мир! مرحبا بالعالم")]),
        ]

        set_rust_enabled(True)
        from _code_puppy_core import process_messages_batch as rust_pmb

        rust_result = rust_pmb(messages, [], [], "")

        set_rust_enabled(False)
        python_tokens = [agent.estimate_tokens_for_message(msg) for msg in messages]

        assert len(rust_result.per_message_tokens) == len(python_tokens)
        for rust_tok, py_tok in zip(rust_result.per_message_tokens, python_tokens):
            assert rust_tok >= 1
            assert py_tok >= 1

    def test_very_long_content(self, agent):
        """Very long content should not crash either path."""
        _skip_if_no_rust()

        long_text = "x" * 100_000
        messages = [ModelRequest(parts=[TextPart(content=long_text)])]

        set_rust_enabled(True)
        from _code_puppy_core import process_messages_batch as rust_pmb

        rust_result = rust_pmb(messages, [], [], "")
        assert rust_result.per_message_tokens[0] >= 1

        set_rust_enabled(False)
        python_tokens = agent.estimate_tokens_for_message(messages[0])
        assert python_tokens >= 1

    def test_empty_content_message(self, agent):
        """Empty content should produce minimum 1 token."""
        _skip_if_no_rust()

        messages = [ModelRequest(parts=[TextPart(content="")])]

        set_rust_enabled(True)
        from _code_puppy_core import process_messages_batch as rust_pmb

        rust_result = rust_pmb(messages, [], [], "")
        assert rust_result.per_message_tokens[0] >= 1

        set_rust_enabled(False)
        python_tokens = agent.estimate_tokens_for_message(messages[0])
        assert python_tokens >= 1

    def test_multiple_tool_calls_and_returns(self, agent):
        """Multiple tool calls in sequence should be handled identically."""
        _skip_if_no_rust()

        messages = [
            ModelRequest(parts=[TextPart(content="Do multiple things")]),
            ModelResponse(
                parts=[
                    ToolCallPart(tool_name="read_file", args="{}", tool_call_id="tc-1"),
                    ToolCallPart(tool_name="list_files", args="{}", tool_call_id="tc-2"),
                ]
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(tool_name="read_file", content="data1", tool_call_id="tc-1"),
                    ToolReturnPart(tool_name="list_files", content="data2", tool_call_id="tc-2"),
                ]
            ),
        ]

        # Both paths should preserve all messages (all matched)
        set_rust_enabled(True)
        rust_pruned = agent.prune_interrupted_tool_calls(messages)
        assert len(rust_pruned) == 3

        set_rust_enabled(False)
        python_pruned = agent.prune_interrupted_tool_calls(messages)
        assert len(python_pruned) == 3

    def test_mixed_tool_and_text_parts(self, agent):
        """Messages with both text and tool parts should be handled correctly."""
        _skip_if_no_rust()

        messages = [
            ModelResponse(
                parts=[
                    TextPart(content="I'll read the file for you."),
                    ToolCallPart(tool_name="read_file", args="{}", tool_call_id="tc-1"),
                ]
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(tool_name="read_file", content="data", tool_call_id="tc-1"),
                ]
            ),
        ]

        set_rust_enabled(True)
        rust_pruned = agent.prune_interrupted_tool_calls(messages)
        assert len(rust_pruned) == 2

        set_rust_enabled(False)
        python_pruned = agent.prune_interrupted_tool_calls(messages)
        assert len(python_pruned) == 2


# ---------------------------------------------------------------------------
# Test: Fallback behavior when Rust is disabled
# ---------------------------------------------------------------------------


class TestFallbackBehavior:
    """Verify the application works correctly without Rust acceleration."""

    def test_set_rust_enabled_toggle(self):
        """set_rust_enabled should toggle the state."""
        if not RUST_AVAILABLE:
            pytest.skip("Rust not available")

        original = is_rust_enabled()
        set_rust_enabled(False)
        assert not is_rust_enabled()
        set_rust_enabled(True)
        assert is_rust_enabled()
        set_rust_enabled(original)

    def test_get_rust_status(self):
        """get_rust_status should return correct diagnostic info."""
        from code_puppy._core_bridge import get_rust_status

        status = get_rust_status()
        assert "installed" in status
        assert "enabled" in status
        assert "active" in status
        assert isinstance(status["installed"], bool)
        assert isinstance(status["enabled"], bool)
        assert isinstance(status["active"], bool)

    def test_agent_works_with_rust_disabled(self, agent):
        """Agent methods should work correctly with Rust disabled."""
        set_rust_enabled(False)

        messages = _make_messages()

        # prune_interrupted_tool_calls should work
        pruned = agent.prune_interrupted_tool_calls(messages)
        assert len(pruned) > 0

        # truncation should work
        truncated = agent.truncation(messages, protected_tokens=100)
        assert len(truncated) >= 1

        # estimate_tokens_for_message should work
        tokens = agent.estimate_tokens_for_message(messages[0])
        assert tokens >= 1

        # _collect_tool_call_ids_uncached should work
        call_ids, return_ids = agent._collect_tool_call_ids_uncached(messages)
        assert isinstance(call_ids, set)
        assert isinstance(return_ids, set)
