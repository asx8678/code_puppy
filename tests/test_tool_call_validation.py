"""Tests for the tool_call_validation module."""

from unittest.mock import patch

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from code_puppy.tool_call_validation import (
    _normalize_args,
    sanitize_messages,
)


class TestNormalizeArgs:
    """Tests for the _normalize_args helper."""

    def test_dict_is_returned_unchanged(self):
        """Valid dict should be returned unchanged."""
        args = {"directory": ".", "recursive": True}
        result = _normalize_args(args)
        assert result == args

    def test_none_returns_empty_dict(self):
        """None should return empty dict."""
        result = _normalize_args(None)
        assert result == {}

    def test_empty_string_returns_empty_dict(self):
        """Empty string should return empty dict."""
        result = _normalize_args("")
        assert result == {}

    def test_list_returns_none(self):
        """List args should be unrecoverable."""
        result = _normalize_args(["arg1", "arg2"])
        assert result is None

    def test_tuple_returns_none(self):
        """Tuple args should be unrecoverable."""
        result = _normalize_args(("arg1", "arg2"))
        assert result is None

    def test_scalar_returns_none(self):
        """Scalar args should be unrecoverable."""
        assert _normalize_args(42) is None
        assert _normalize_args(3.14) is None
        assert _normalize_args(True) is None

    def test_valid_json_object_string_returns_dict(self):
        """JSON object string should be parsed to dict."""
        result = _normalize_args('{"directory": ".", "recursive": true}')
        assert result == {"directory": ".", "recursive": True}

    def test_valid_json_list_string_returns_none(self):
        """JSON list string should be unrecoverable."""
        result = _normalize_args('["arg1", "arg2"]')
        assert result is None

    def test_valid_json_scalar_string_returns_none(self):
        """JSON scalar string should be unrecoverable."""
        assert _normalize_args('"just a string"') is None
        assert _normalize_args("42") is None
        assert _normalize_args("true") is None

    def test_invalid_json_string_returns_none(self):
        """Invalid JSON string should be unrecoverable."""
        result = _normalize_args("{malformed json")
        assert result is None

    def test_pretty_printed_json_object(self):
        """Pretty-printed JSON object should parse correctly."""
        json_str = '{\n  "directory": ".",\n  "recursive": true\n}'
        result = _normalize_args(json_str)
        assert result == {"directory": ".", "recursive": True}


class TestSanitizeMessages:
    """Tests for the sanitize_messages function."""

    def test_empty_messages_return_unchanged(self):
        """Empty message list should return unchanged."""
        assert sanitize_messages([]) == []

    def test_messages_without_tool_calls_return_unchanged(self):
        """Messages without tool calls should pass through."""
        msgs = [
            ModelRequest(parts=[UserPromptPart(content="hello")]),
            ModelResponse(parts=[TextPart(content="hi")], model_name="test"),
        ]
        result = sanitize_messages(msgs)
        assert len(result) == 2
        assert result == msgs

    def test_valid_tool_call_part_passes_through(self):
        """Valid tool call parts should pass through."""
        msgs = [
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="list_files",
                        args={"directory": "."},
                        tool_call_id="tc-1",
                    ),
                ],
                model_name="test",
            ),
        ]
        result = sanitize_messages(msgs)
        assert len(result) == 1
        assert result[0].parts[0].args == {"directory": "."}

    def test_list_args_are_removed(self):
        """Tool calls with list args should be removed."""
        msgs = [
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read_file",
                        args=["path/to/file"],  # Invalid: list
                        tool_call_id="tc-1",
                    ),
                ],
                model_name="test",
            ),
        ]
        result = sanitize_messages(msgs)
        # The malformed tool call is removed, leaving empty message
        assert len(result) == 0

    def test_scalar_args_are_removed(self):
        """Tool calls with scalar args should be removed."""
        msgs = [
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="grep",
                        args=123,  # Invalid: scalar
                        tool_call_id="tc-1",
                    ),
                ],
                model_name="test",
            ),
        ]
        result = sanitize_messages(msgs)
        assert len(result) == 0

    def test_none_args_are_converted_to_empty_dict(self):
        """Tool calls with None args should become empty dict."""
        msgs = [
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="list_files",
                        args=None,
                        tool_call_id="tc-1",
                    ),
                ],
                model_name="test",
            ),
        ]
        result = sanitize_messages(msgs)
        assert len(result) == 1
        assert result[0].parts[0].args == {}

    def test_json_object_string_is_parsed(self):
        """Tool call args as JSON object string should be parsed."""
        msgs = [
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read_file",
                        args='{"file_path": "test.py"}',
                        tool_call_id="tc-1",
                    ),
                ],
                model_name="test",
            ),
        ]
        result = sanitize_messages(msgs)
        assert len(result) == 1
        assert result[0].parts[0].args == {"file_path": "test.py"}

    def test_json_list_string_is_removed(self):
        """Tool call args as JSON list string should be removed."""
        msgs = [
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read_files",
                        args='["file1.py", "file2.py"]',  # JSON list
                        tool_call_id="tc-1",
                    ),
                ],
                model_name="test",
            ),
        ]
        result = sanitize_messages(msgs)
        assert len(result) == 0

    def test_orphaned_tool_returns_are_removed(self):
        """Tool returns matching removed tool calls should be cleaned up."""
        msgs = [
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="bad_tool",
                        args=["bad", "args"],  # Will be removed
                        tool_call_id="tc-bad",
                    ),
                ],
                model_name="test",
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="bad_tool",
                        content="result",
                        tool_call_id="tc-bad",  # Orphaned
                    ),
                ],
            ),
        ]
        result = sanitize_messages(msgs)
        # Both messages become empty and are dropped
        assert len(result) == 0

    def test_valid_tool_returns_preserve(self):
        """Valid tool calls with their returns should be preserved."""
        msgs = [
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read_file",
                        args={"file_path": "test.py"},
                        tool_call_id="tc-valid",
                    ),
                ],
                model_name="test",
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="read_file",
                        content="print('hello')",
                        tool_call_id="tc-valid",
                    ),
                ],
            ),
        ]
        result = sanitize_messages(msgs)
        assert len(result) == 2
        assert result[0].parts[0].tool_call_id == "tc-valid"
        assert result[1].parts[0].tool_call_id == "tc-valid"

    def test_mixed_valid_and_invalid_tool_calls(self):
        """Mix of valid and invalid tool calls should sanitize correctly."""
        msgs = [
            ModelResponse(
                parts=[
                    TextPart(content="I'll help you"),
                    ToolCallPart(
                        tool_name="valid_tool",
                        args={"key": "value"},
                        tool_call_id="tc-1",
                    ),
                    ToolCallPart(
                        tool_name="bad_tool",
                        args=[1, 2, 3],  # Will be removed
                        tool_call_id="tc-2",
                    ),
                ],
                model_name="test",
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="valid_tool",
                        content="good result",
                        tool_call_id="tc-1",
                    ),
                    ToolReturnPart(
                        tool_name="bad_tool",
                        content="orphaned result",
                        tool_call_id="tc-2",
                    ),
                ],
            ),
        ]
        result = sanitize_messages(msgs)
        assert len(result) == 2
        # First message should have text part and valid tool call
        assert len(result[0].parts) == 2
        assert result[0].parts[0].part_kind == "text"
        assert result[0].parts[1].tool_call_id == "tc-1"
        # Second message should only have the valid return
        assert len(result[1].parts) == 1
        assert result[1].parts[0].tool_call_id == "tc-1"

    def test_partial_message_cleanup(self):
        """Messages with remaining parts after cleanup should be kept."""
        msgs = [
            ModelResponse(
                parts=[
                    TextPart(content="Some text"),
                    ToolCallPart(
                        tool_name="bad_tool",
                        args=["bad"],  # Will be removed
                        tool_call_id="tc-1",
                    ),
                ],
                model_name="test",
            ),
        ]
        result = sanitize_messages(msgs)
        # Message still has text part, so it should be kept
        assert len(result) == 1
        assert len(result[0].parts) == 1
        assert result[0].parts[0].part_kind == "text"

    def test_logs_when_fixing_args(self):
        """Sanitizer should log when repairing args."""
        with patch("code_puppy.tool_call_validation.logger") as mock_logger:
            msgs = [
                ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="test_tool",
                            args='{"key": "value"}',  # Will be repaired
                            tool_call_id="tc-1",
                        ),
                    ],
                    model_name="test",
                ),
            ]
            sanitize_messages(msgs)
            mock_logger.debug.assert_called()

    def test_logs_when_removing_parts(self):
        """Sanitizer should log when removing parts."""
        with patch("code_puppy.tool_call_validation.logger") as mock_logger:
            msgs = [
                ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="bad_tool",
                            args=["bad"],  # Will be removed
                            tool_call_id="tc-1",
                        ),
                    ],
                    model_name="test",
                ),
            ]
            sanitize_messages(msgs)
            mock_logger.debug.assert_called()

    def test_info_log_on_cleanup(self):
        """Sanitizer should log info when parts are cleaned."""
        with patch("code_puppy.tool_call_validation.logger") as mock_logger:
            msgs = [
                ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="bad_tool",
                            args=["bad"],
                            tool_call_id="tc-1",
                        ),
                    ],
                    model_name="test",
                ),
            ]
            sanitize_messages(msgs)
            mock_logger.info.assert_called()


class TestSanitizeMessagesEdgeCases:
    """Edge case tests for sanitize_messages."""

    def test_empty_string_args_become_empty_dict(self):
        """Empty string args should be normalized to empty dict."""
        msgs = [
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="test",
                        args="",
                        tool_call_id="tc-1",
                    ),
                ],
                model_name="test",
            ),
        ]
        result = sanitize_messages(msgs)
        assert len(result) == 1
        assert result[0].parts[0].args == {}

    def test_whitespace_only_string_args_become_empty_dict(self):
        """Whitespace-only string args should be normalized to empty dict."""
        msgs = [
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="test",
                        args="   \n  ",
                        tool_call_id="tc-1",
                    ),
                ],
                model_name="test",
            ),
        ]
        result = sanitize_messages(msgs)
        assert len(result) == 1
        assert result[0].parts[0].args == {}

    def test_nested_json_object_string(self):
        """Nested JSON object should parse correctly."""
        msgs = [
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="turbo_execute",
                        args='{"plan_json": "{\\"id\\": \\"plan1\\"}"}',
                        tool_call_id="tc-1",
                    ),
                ],
                model_name="test",
            ),
        ]
        result = sanitize_messages(msgs)
        assert len(result) == 1
        assert result[0].parts[0].args["plan_json"] == '{"id": "plan1"}'

    def test_preserves_message_with_no_parts(self):
        """Messages with no parts (edge case) should pass through."""
        msgs = [
            ModelResponse(parts=[], model_name="test"),
        ]
        result = sanitize_messages(msgs)
        assert len(result) == 1
        assert result[0].parts == []

    def test_non_pydantic_messages_pass_through(self):
        """Non-pydantic messages should pass through unchanged."""
        class CustomMessage:
            pass

        msgs = [CustomMessage(), "string message", {"dict": "message"}]
        result = sanitize_messages(msgs)
        assert len(result) == 3
        assert isinstance(result[0], CustomMessage)
        assert result[1] == "string message"
        assert result[2] == {"dict": "message"}
