"""Tests for tool-call sanitization in session storage."""

import pytest
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from code_puppy.session_storage import load_session, save_session


@pytest.fixture()
def token_estimator():
    return lambda message: len(str(message))


class TestSessionStorageSanitization:
    """Test that session storage sanitizes messages on load."""

    def test_load_session_sanitizes_malformed_tool_calls(self, tmp_path, token_estimator):
        """Messages with malformed tool calls should be sanitized on load."""
        history = [
            ModelRequest(parts=[UserPromptPart(content="hello")]),
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="bad_tool",
                        args=["bad"],
                        tool_call_id="tc-bad",
                    ),
                ],
                model_name="test",
            ),
        ]

        save_session(
            history=history,
            session_name="test_session",
            base_dir=tmp_path,
            timestamp="2024-01-01T00:00:00",
            token_estimator=token_estimator,
        )

        loaded = load_session("test_session", tmp_path)

        assert len(loaded) == 1
        assert loaded[0].parts[0].content == "hello"

    def test_load_session_sanitizes_orphaned_returns(self, tmp_path, token_estimator):
        """Orphaned tool returns should be cleaned up on load."""
        history = [
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="bad_tool",
                        args=["bad"],
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
                        tool_call_id="tc-bad",
                    ),
                ],
            ),
        ]

        save_session(
            history=history,
            session_name="test_session",
            base_dir=tmp_path,
            timestamp="2024-01-01T00:00:00",
            token_estimator=token_estimator,
        )

        loaded = load_session("test_session", tmp_path)
        assert len(loaded) == 0

    def test_load_session_preserves_valid_messages(self, tmp_path, token_estimator):
        """Valid messages should be preserved on load."""
        history = [
            ModelRequest(parts=[UserPromptPart(content="hello")]),
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="valid_tool",
                        args={"key": "value"},
                        tool_call_id="tc-valid",
                    ),
                ],
                model_name="test",
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="valid_tool",
                        content="result",
                        tool_call_id="tc-valid",
                    ),
                ],
            ),
        ]

        save_session(
            history=history,
            session_name="test_session",
            base_dir=tmp_path,
            timestamp="2024-01-01T00:00:00",
            token_estimator=token_estimator,
        )

        loaded = load_session("test_session", tmp_path)
        assert len(loaded) == 3
        assert loaded[1].parts[0].args == {"key": "value"}
        assert loaded[2].parts[0].content == "result"

    def test_load_session_repairs_json_string_args(self, tmp_path, token_estimator):
        """JSON string args should be parsed on load."""
        history = [
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="test_tool",
                        args='{"directory": "."}',
                        tool_call_id="tc-1",
                    ),
                ],
                model_name="test",
            ),
        ]

        save_session(
            history=history,
            session_name="test_session",
            base_dir=tmp_path,
            timestamp="2024-01-01T00:00:00",
            token_estimator=token_estimator,
        )

        loaded = load_session("test_session", tmp_path)
        assert len(loaded) == 1
        assert loaded[0].parts[0].args == {"directory": "."}

    def test_load_session_handles_mixed_valid_and_invalid(self, tmp_path, token_estimator):
        """Mix of valid and invalid should be sanitized correctly."""
        history = [
            ModelRequest(parts=[UserPromptPart(content="hello")]),
            ModelResponse(
                parts=[
                    TextPart(content="I'll help"),
                    ToolCallPart(
                        tool_name="valid_tool",
                        args={"key": "value"},
                        tool_call_id="tc-valid",
                    ),
                    ToolCallPart(
                        tool_name="bad_tool",
                        args=[1, 2, 3],
                        tool_call_id="tc-bad",
                    ),
                ],
                model_name="test",
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="valid_tool",
                        content="good result",
                        tool_call_id="tc-valid",
                    ),
                    ToolReturnPart(
                        tool_name="bad_tool",
                        content="orphaned result",
                        tool_call_id="tc-bad",
                    ),
                ],
            ),
        ]

        save_session(
            history=history,
            session_name="test_session",
            base_dir=tmp_path,
            timestamp="2024-01-01T00:00:00",
            token_estimator=token_estimator,
        )

        loaded = load_session("test_session", tmp_path)
        assert len(loaded) == 3

        # Request prompt remains
        assert loaded[0].parts[0].content == "hello"

        # Response keeps text + valid tool call, bad call removed
        assert len(loaded[1].parts) == 2
        assert loaded[1].parts[0].part_kind == "text"
        assert loaded[1].parts[1].tool_call_id == "tc-valid"

        # Return message keeps only valid return
        assert len(loaded[2].parts) == 1
        assert loaded[2].parts[0].tool_call_id == "tc-valid"
