"""Tests for tool return truncation in compaction.tool_arg_truncation."""

from pydantic_ai.messages import ModelRequest, ToolReturnPart

from code_puppy.compaction.tool_arg_truncation import (
    DEFAULT_RETURN_TAIL_CHARS,
    DEFAULT_RETURN_TRUNCATION_TEXT,
    _truncate_message_tool_returns,
    pretruncate_messages,
    truncate_tool_return_content,
)


class TestTruncateToolReturnContent:
    """Tests for truncate_tool_return_content function."""

    def test_short_string_unchanged(self):
        content = "short result"
        result, modified = truncate_tool_return_content(content, max_length=5000)
        assert result == content
        assert modified is False

    def test_long_string_truncated(self):
        content = "a" * 10000
        result, modified = truncate_tool_return_content(content, max_length=5000)
        assert modified is True
        assert "[Truncated: tool return was 10000 chars]" in result
        assert result.startswith("[Truncated:")
        # Result should be much shorter than original
        assert len(result) < 1000
        # Head and tail sections should be present
        assert result.endswith("a" * DEFAULT_RETURN_TAIL_CHARS)

    def test_preserves_head_and_tail(self):
        head = "HEAD_START_"
        tail = "_TAIL_END"
        middle = "x" * 10000
        content = head + middle + tail
        result, modified = truncate_tool_return_content(content, max_length=100)
        assert modified is True
        assert head in result
        assert tail in result
        assert DEFAULT_RETURN_TRUNCATION_TEXT in result

    def test_exactly_at_limit_unchanged(self):
        content = "a" * 5000
        result, modified = truncate_tool_return_content(content, max_length=5000)
        assert result == content
        assert modified is False

    def test_non_string_unchanged(self):
        content = {"key": "value"}
        result, modified = truncate_tool_return_content(content, max_length=100)
        assert result == content
        assert modified is False

    def test_custom_head_tail(self):
        content = "A" * 100 + "B" * 10000 + "C" * 100
        result, modified = truncate_tool_return_content(
            content, max_length=200, head_chars=50, tail_chars=50
        )
        assert modified is True
        assert result.count("A") == 50
        assert result.count("C") == 50

    def test_none_content_unchanged(self):
        result, modified = truncate_tool_return_content(None, max_length=100)
        assert result is None
        assert modified is False


class TestTruncateMessageToolReturns:
    """Tests for _truncate_message_tool_returns function."""

    def test_model_request_with_tool_return(self):
        long_content = "a" * 10000
        msg = ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="read_file",
                    content=long_content,
                    tool_call_id="call_001",
                )
            ]
        )
        result = _truncate_message_tool_returns(msg, max_length=100)
        assert isinstance(result, ModelRequest)
        assert "[Truncated:" in result.parts[0].content
        assert result.parts[0].tool_name == "read_file"
        assert result.parts[0].tool_call_id == "call_001"

    def test_short_tool_return_unchanged(self):
        msg = ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="read_file",
                    content="short",
                    tool_call_id="call_001",
                )
            ]
        )
        result = _truncate_message_tool_returns(msg, max_length=5000)
        assert result is msg

    def test_non_request_message_unchanged(self):
        from pydantic_ai.messages import ModelResponse, TextPart

        msg = ModelResponse(parts=[TextPart(content="hello")])
        result = _truncate_message_tool_returns(msg, max_length=100)
        assert result is msg

    def test_mixed_parts_only_returns_truncated(self):
        long_content = "a" * 10000
        from pydantic_ai.messages import TextPart

        msg = ModelRequest(
            parts=[
                TextPart(content="some text"),
                ToolReturnPart(
                    tool_name="read_file",
                    content=long_content,
                    tool_call_id="call_001",
                ),
                ToolReturnPart(
                    tool_name="list_files",
                    content="short result",
                    tool_call_id="call_002",
                ),
            ]
        )
        result = _truncate_message_tool_returns(msg, max_length=100)
        # TextPart unchanged
        assert isinstance(result.parts[0], type(msg.parts[0]))
        # Long return truncated
        assert "[Truncated:" in result.parts[1].content
        # Short return unchanged
        assert result.parts[2].content == "short result"

    def test_all_fields_preserved_after_truncation(self):
        long_content = "a" * 10000
        msg = ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="read_file",
                    content=long_content,
                    tool_call_id="call_12345",
                )
            ]
        )
        result = _truncate_message_tool_returns(msg, max_length=100)
        assert result.parts[0].tool_name == "read_file"
        assert result.parts[0].tool_call_id == "call_12345"
        assert result.parts[0].part_kind == "tool-return"

    def test_unmodified_returns_original(self):
        msg = ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="read_file",
                    content="short",
                    tool_call_id="call_001",
                )
            ]
        )
        result = _truncate_message_tool_returns(msg, max_length=5000)
        assert result is msg


class TestPretruncateMessagesWithReturns:
    """Tests for pretruncate_messages with tool return truncation."""

    def test_tool_returns_in_older_messages_truncated(self):
        long_content = "a" * 10000
        msgs = [
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="read_file",
                        content=long_content,
                        tool_call_id="call_001",
                    )
                ]
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="read_file",
                        content="short",
                        tool_call_id="call_002",
                    )
                ]
            ),
        ]
        result, count = pretruncate_messages(
            msgs, keep_recent=1, max_return_length=100
        )
        assert count == 1
        assert "[Truncated:" in result[0].parts[0].content
        assert result[1] is msgs[1]

    def test_recent_messages_not_truncated(self):
        long_content = "a" * 10000
        msgs = [
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="read_file",
                        content=long_content,
                        tool_call_id="call_001",
                    )
                ]
            ),
        ]
        result, count = pretruncate_messages(
            msgs, keep_recent=10, max_return_length=100
        )
        assert count == 0
        assert result[0] is msgs[0]

    def test_original_not_mutated(self):
        long_content = "a" * 10000
        old_msg = ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="read_file",
                    content=long_content,
                    tool_call_id="call_001",
                )
            ]
        )
        msgs = [old_msg]
        result, _ = pretruncate_messages(
            msgs, keep_recent=0, max_return_length=100
        )
        assert old_msg.parts[0].content == long_content
        assert "[Truncated:" in result[0].parts[0].content
