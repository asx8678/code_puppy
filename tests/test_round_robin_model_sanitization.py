"""Tests for tool-call sanitization integration in RoundRobinModel."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from code_puppy.round_robin_model import RoundRobinModel


class MockModel:
    """A mock model for testing sanitization."""

    def __init__(self, name):
        self._name = name
        self.request = AsyncMock(return_value=MagicMock())
        self.request_stream = MagicMock()

    @property
    def model_name(self):
        return self._name

    @property
    def system(self):
        return f"system_{self._name}"

    @property
    def base_url(self):
        return f"https://api.{self._name}.com"

    def model_attributes(self, model):
        return {"model_name": self._name}

    def prepare_request(self, model_settings, model_request_parameters):
        return model_settings, model_request_parameters

    @property
    def _stream_response(self):
        return MagicMock()


class TestRoundRobinModelSanitization:
    """Test that RoundRobinModel sanitizes messages before sending."""

    @pytest.mark.asyncio
    async def test_request_sanitizes_messages(self):
        """Messages should be sanitized before being sent to the model."""
        m1 = MockModel("model1")
        rrm = RoundRobinModel(m1)

        # Messages with a malformed tool call (list args)
        messages = [
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="bad_tool",
                        args=["bad"],  # List args - will be removed
                        tool_call_id="tc-bad",
                    ),
                ],
                model_name="test",
            ),
        ]

        # Mock the internal request to capture the actual messages sent
        captured_messages = []

        async def capture_request(msgs, settings, params):
            captured_messages.extend(msgs)
            return MagicMock()

        m1.request.side_effect = capture_request

        # Patch the availability service to avoid external calls
        with patch("code_puppy.model_availability.availability_service"):
            await rrm.request(messages, None, MagicMock())

        # The message with malformed tool call should have been sanitized away
        assert len(captured_messages) == 0

    @pytest.mark.asyncio
    async def test_request_preserves_valid_messages(self):
        """Valid messages should pass through unchanged."""
        m1 = MockModel("model1")
        rrm = RoundRobinModel(m1)

        messages = [
            ModelRequest(parts=[UserPromptPart(content="hello")]),
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="valid_tool",
                        args={"key": "value"},
                        tool_call_id="tc-1",
                    ),
                ],
                model_name="test",
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="valid_tool",
                        content="result",
                        tool_call_id="tc-1",
                    ),
                ],
            ),
        ]

        captured_messages = []

        async def capture_request(msgs, settings, params):
            captured_messages.extend(msgs)
            return MagicMock()

        m1.request.side_effect = capture_request

        with patch("code_puppy.model_availability.availability_service"):
            await rrm.request(messages, None, MagicMock())

        # All valid messages should be preserved
        assert len(captured_messages) == 3

    @pytest.mark.asyncio
    async def test_request_sanitizes_json_string_args(self):
        """JSON string args should be parsed to dict."""
        m1 = MockModel("model1")
        rrm = RoundRobinModel(m1)

        messages = [
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="test_tool",
                        args='{"directory": "."}',  # JSON string - will be parsed
                        tool_call_id="tc-1",
                    ),
                ],
                model_name="test",
            ),
        ]

        captured_messages = []

        async def capture_request(msgs, settings, params):
            captured_messages.extend(msgs)
            return MagicMock()

        m1.request.side_effect = capture_request

        with patch("code_puppy.model_availability.availability_service"):
            await rrm.request(messages, None, MagicMock())

        # Message should be preserved with parsed args
        assert len(captured_messages) == 1
        assert captured_messages[0].parts[0].args == {"directory": "."}


class TestRoundRobinModelRequestStreamSanitization:
    """Test that RoundRobinModel.request_stream sanitizes messages."""

    @pytest.mark.anyio
    async def test_request_stream_sanitizes_messages(self):
        """Messages should be sanitized before streaming request."""
        m1 = MockModel("model1")
        rrm = RoundRobinModel(m1)

        messages = [
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="bad_tool",
                        args=["bad"],  # List args - will be removed
                        tool_call_id="tc-bad",
                    ),
                ],
                model_name="test",
            ),
        ]

        captured_messages = []

        @asynccontextmanager
        async def capture_stream(msgs, settings, params, run_context=None):
            captured_messages.extend(msgs)
            yield MagicMock()

        m1.request_stream = capture_stream

        with patch("code_puppy.model_availability.availability_service"):
            async with rrm.request_stream(messages, None, MagicMock()) as _:
                pass

        # Malformed messages should be sanitized
        assert len(captured_messages) == 0

    @pytest.mark.anyio
    async def test_request_stream_preserves_valid_messages(self):
        """Valid messages should pass through request_stream."""
        m1 = MockModel("model1")
        rrm = RoundRobinModel(m1)

        messages = [
            ModelRequest(parts=[UserPromptPart(content="hello")]),
            ModelResponse(
                parts=[TextPart(content="response")],
                model_name="test",
            ),
        ]

        captured_messages = []

        @asynccontextmanager
        async def capture_stream(msgs, settings, params, run_context=None):
            captured_messages.extend(msgs)
            yield MagicMock()

        m1.request_stream = capture_stream

        with patch("code_puppy.model_availability.availability_service"):
            async with rrm.request_stream(messages, None, MagicMock()) as _:
                pass

        assert len(captured_messages) == 2
