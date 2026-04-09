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
