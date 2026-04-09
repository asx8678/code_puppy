"""Tests for compaction.tool_arg_truncation module."""

from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart

from code_puppy.compaction.tool_arg_truncation import (
    DEFAULT_TRUNCATION_TEXT,
    _truncate_message_tool_calls,
    pretruncate_messages,
    truncate_tool_arg,
    truncate_tool_call_args,
)


class TestTruncateToolArg:
    """Tests for truncate_tool_arg function."""

    def test_short_string_unchanged(self):
        """Short strings are not truncated."""
        value = "short text"
        result, modified = truncate_tool_arg(value, max_length=100)
        assert result == value
        assert modified is False

    def test_long_string_truncated(self):
        """Long strings are truncated with marker."""
        value = "a" * 1000
        result, modified = truncate_tool_arg(value, max_length=100)
        assert len(result) == 100 + len(DEFAULT_TRUNCATION_TEXT)
        assert result.endswith(DEFAULT_TRUNCATION_TEXT)
        assert modified is True

    def test_exactly_at_limit_unchanged(self):
        """String exactly at limit is not truncated."""
        value = "a" * 100
        result, modified = truncate_tool_arg(value, max_length=100)
        assert result == value
        assert modified is False

    def test_non_string_unchanged(self):
        """Non-string values are passed through."""
        value = 12345
        result, modified = truncate_tool_arg(value, max_length=100)
        assert result == value
        assert modified is False

    def test_custom_truncation_text(self):
        """Custom truncation text is applied."""
        value = "a" * 1000
        result, modified = truncate_tool_arg(
            value, max_length=100, truncation_text="[CUT]"
        )
        assert result.endswith("[CUT]")


class TestTruncateToolCallArgs:
    """Tests for truncate_tool_call_args function."""

    def test_target_tool_truncates_target_keys(self):
        """Target tool has target keys truncated."""
        args = {
            "content": "a" * 1000,
            "path": "/tmp/file",
        }
        result, modified = truncate_tool_call_args("write_file", args, max_length=100)
        assert modified is True
        assert len(result["content"]) <= 100 + len(DEFAULT_TRUNCATION_TEXT)
        assert result["path"] == "/tmp/file"  # path is not a target key

    def test_non_target_tool_unchanged(self):
        """Non-target tools are not modified."""
        args = {
            "content": "a" * 1000,
            "path": "/tmp/file",
        }
        result, modified = truncate_tool_call_args("read_file", args, max_length=100)
        assert modified is False
        assert result["content"] == args["content"]  # unchanged

    def test_custom_target_tools(self):
        """Custom target_tools set is respected."""
        args = {"content": "a" * 1000}
        result, modified = truncate_tool_call_args(
            "custom_writer",
            args,
            max_length=100,
            target_tools={"custom_writer"},
        )
        assert modified is True

    def test_custom_target_keys(self):
        """Custom target_keys set is respected."""
        args = {"custom_key": "a" * 1000, "content": "short"}
        result, modified = truncate_tool_call_args(
            "write_file",
            args,
            max_length=100,
            target_keys={"custom_key"},
        )
        assert modified is True
        assert result["custom_key"].endswith(DEFAULT_TRUNCATION_TEXT)
        assert result["content"] == "short"  # unchanged - not a target key

    def test_empty_args_unchanged(self):
        """Empty args dict is unchanged."""
        result, modified = truncate_tool_call_args("write_file", {}, max_length=100)
        assert modified is False
        assert result == {}


class TestTruncateMessageToolCalls:
    """Tests for _truncate_message_tool_calls function."""

    def test_model_response_with_tool_calls(self):
        """ModelResponse with tool calls has args truncated."""
        long_content = "a" * 1000
        msg = ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="write_file",
                    args={"content": long_content, "path": "/tmp/file"},
                )
            ]
        )
        result = _truncate_message_tool_calls(msg, max_length=100)

        assert isinstance(result, ModelResponse)
        assert len(result.parts) == 1
        assert isinstance(result.parts[0], ToolCallPart)
        assert result.parts[0].args["content"].endswith(DEFAULT_TRUNCATION_TEXT)
        assert result.parts[0].args["path"] == "/tmp/file"  # not truncated

    def test_model_response_no_tool_calls_unchanged(self):
        """ModelResponse without tool calls is unchanged."""
        msg = ModelResponse(parts=[TextPart(content="Hello")])
        result = _truncate_message_tool_calls(msg, max_length=100)
        assert result is msg  # Same object returned

    def test_model_request_with_tool_calls(self):
        """ModelRequest with tool calls has args truncated."""
        long_content = "a" * 1000
        msg = ModelRequest(
            parts=[
                ToolCallPart(
                    tool_name="edit_file",
                    args={"old_string": long_content, "new_string": "replacement"},
                )
            ]
        )
        result = _truncate_message_tool_calls(msg, max_length=100)

        assert isinstance(result, ModelRequest)
        assert result.parts[0].args["old_string"].endswith(DEFAULT_TRUNCATION_TEXT)
        assert result.parts[0].args["new_string"] == "replacement"  # not truncated

    def test_unmodified_returns_original(self):
        """When nothing is modified, original message is returned."""
        msg = ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="read_file",  # Not a target tool
                    args={"path": "/tmp/file"},
                )
            ]
        )
        result = _truncate_message_tool_calls(msg, max_length=100)
        assert result is msg  # Same object returned


class TestPretruncateMessages:
    """Tests for pretruncate_messages function."""

    def test_messages_below_keep_recent_untouched(self):
        """Messages at or below keep_recent are not truncated."""
        msgs = [
            ModelResponse(parts=[TextPart(content="msg1")]),
            ModelResponse(parts=[TextPart(content="msg2")]),
        ]
        result, count = pretruncate_messages(msgs, keep_recent=10)
        assert len(result) == 2
        assert count == 0
        # Original messages returned (not new objects)
        assert result[0] is msgs[0]
        assert result[1] is msgs[1]

    def test_older_messages_truncated(self):
        """Messages older than keep_recent are truncated."""
        long_content = "a" * 1000
        msgs = [
            ModelResponse(  # Oldest - should be truncated
                parts=[
                    ToolCallPart(
                        tool_name="write_file",
                        args={"content": long_content},
                    )
                ]
            ),
            ModelResponse(parts=[TextPart(content="recent")]),  # Recent - protected
        ]
        result, count = pretruncate_messages(msgs, keep_recent=1, max_length=100)
        assert count == 1
        # Oldest message was truncated
        assert result[0].parts[0].args["content"].endswith(DEFAULT_TRUNCATION_TEXT)
        # Recent message unchanged
        assert result[1] is msgs[1]

    def test_keep_recent_zero_truncates_all(self):
        """keep_recent=0 means all messages can be truncated."""
        long_content = "a" * 1000
        msgs = [
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="write_file",
                        args={"content": long_content},
                    )
                ]
            ),
        ]
        result, count = pretruncate_messages(msgs, keep_recent=0, max_length=100)
        assert count == 1

    def test_empty_messages_returns_empty(self):
        """Empty message list returns empty with 0 count."""
        result, count = pretruncate_messages([], keep_recent=10)
        assert result == []
        assert count == 0

    def test_original_not_mutated(self):
        """Original message list is not mutated."""
        long_content = "a" * 1000
        old_msg = ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="write_file",
                    args={"content": long_content},
                )
            ]
        )
        msgs = [old_msg]

        result, _ = pretruncate_messages(msgs, keep_recent=0, max_length=100)

        # Original unchanged
        assert old_msg.parts[0].args["content"] == long_content
        # Result has truncated version
        assert result[0].parts[0].args["content"].endswith(DEFAULT_TRUNCATION_TEXT)

    def test_mixed_tools_only_targets_truncated(self):
        """Only target tools have args truncated."""
        long_content = "a" * 1000
        msgs = [
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="write_file",  # Target
                        args={"content": long_content},
                    ),
                    ToolCallPart(
                        tool_name="read_file",  # Not target
                        args={"path": "/tmp/file"},
                    ),
                ]
            ),
        ]
        result, count = pretruncate_messages(msgs, keep_recent=0, max_length=100)
        assert count == 1
        # write_file content truncated
        assert result[0].parts[0].args["content"].endswith(DEFAULT_TRUNCATION_TEXT)
        # read_file path unchanged
        assert result[0].parts[1].args["path"] == "/tmp/file"

    def test_truncate_count_matches_modified_messages(self):
        """truncation_count equals number of modified messages."""
        long_content = "a" * 1000
        msgs = [
            ModelResponse(  # Modified
                parts=[
                    ToolCallPart(
                        tool_name="write_file",
                        args={"content": long_content},
                    )
                ]
            ),
            ModelResponse(  # Modified
                parts=[
                    ToolCallPart(
                        tool_name="edit_file",
                        args={"content": long_content},
                    )
                ]
            ),
            ModelResponse(  # Not modified (not a target tool)
                parts=[
                    ToolCallPart(
                        tool_name="read_file",
                        args={"path": "/tmp/file"},
                    )
                ]
            ),
        ]
        result, count = pretruncate_messages(msgs, keep_recent=0, max_length=100)
        assert count == 2  # Two messages were modified

    def test_tool_call_part_all_fields_preserved_after_truncation(self):
        """All ToolCallPart fields (id, provider_name, provider_details) are preserved after truncation.

        Regression test for code_puppy-lg9: Truncation should use model_copy/update
        to preserve all fields, not just tool_name, args, and tool_call_id.
        """
        long_content = "a" * 1000
        original_part = ToolCallPart(
            tool_name="write_file",
            args={"content": long_content},
            tool_call_id="call_12345",
            id="unique-part-id",
            provider_name="test_provider",
            provider_details={"key": "value"},
        )
        msg = ModelResponse(parts=[original_part])

        result = _truncate_message_tool_calls(msg, max_length=100)

        assert isinstance(result, ModelResponse)
        assert len(result.parts) == 1
        truncated_part = result.parts[0]

        # Args should be truncated
        assert truncated_part.args["content"].endswith(DEFAULT_TRUNCATION_TEXT)

        # All other fields should be preserved (code_puppy-lg9)
        assert truncated_part.tool_name == "write_file"
        assert truncated_part.tool_call_id == "call_12345"
        assert truncated_part.id == "unique-part-id"
        assert truncated_part.provider_name == "test_provider"
        assert truncated_part.provider_details == {"key": "value"}
        assert truncated_part.part_kind == "tool-call"

    def test_tool_call_return_pair_integrity_maintained(self):
        """Tool call/return pairs maintain integrity when older messages are compacted.

        Regression test for code_puppy-4eu: When messages are truncated/compacted,
        the keep_recent window should ensure that tool calls and their corresponding
        returns are either both in the 'old' section (to be compacted) or both in
        the 'recent' section (to be preserved).

        The invariant: tool_call_id values appearing in the compacted section will
        not have matching tool_return parts in the preserved section, and vice versa.
        """
        from pydantic_ai.messages import ToolReturnPart

        long_content = "a" * 1000

        # Create a sequence: tool call -> tool return -> tool call (recent, protected)
        msgs = [
            ModelResponse(  # Oldest: tool call (to be compacted)
                parts=[
                    ToolCallPart(
                        tool_name="write_file",
                        args={"content": long_content},
                        tool_call_id="call_001",
                    )
                ]
            ),
            ModelRequest(  # Middle: tool return (to be compacted)
                parts=[
                    ToolReturnPart(
                        tool_name="write_file",
                        content="success",
                        tool_call_id="call_001",
                    )
                ]
            ),
            ModelResponse(  # Recent: new tool call (protected)
                parts=[
                    ToolCallPart(
                        tool_name="read_file",
                        args={"path": "/tmp/file"},
                        tool_call_id="call_002",
                    )
                ]
            ),
        ]

        # With keep_recent=1, only the last message should be protected
        result, count = pretruncate_messages(msgs, keep_recent=1, max_length=100)

        # The first two messages (call_001 and its return) should be in the old section
        # and the first message should be truncated
        assert count == 1  # First message (write_file call) was truncated

        # Verify pair integrity: call_001 and its return are both in result
        # (they weren't split across the boundary in a way that causes issues)
        old_section = result[:-1]  # All but the last (protected) message

        # Collect all tool_call_ids in the old section
        old_call_ids = set()
        old_return_ids = set()
        for msg in old_section:
            for part in msg.parts:
                if isinstance(part, ToolCallPart):
                    old_call_ids.add(part.tool_call_id)
                elif isinstance(part, ToolReturnPart):
                    old_return_ids.add(part.tool_call_id)

        # Verify the pair is intact: call_001 has both a call and return in old section
        assert "call_001" in old_call_ids, "Tool call should be in old section"
        assert "call_001" in old_return_ids, "Tool return should be in old section"

        # Verify the recent message is protected and unchanged
        assert result[-1] is msgs[2], "Recent message should be the original object"
