"""Tests for agent_helpers module.

Tests the invert_conversation_roles function which implements the Orion pattern
for reviewer agents — swapping user↔assistant roles to put the reviewer in a
critique stance.
"""

from datetime import datetime, timezone

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from code_puppy.utils.agent_helpers import invert_conversation_roles


class TestInvertConversationRoles:
    """Tests for invert_conversation_roles function."""

    def test_basic_inversion_user_assistant(self):
        """Test basic inversion: 1 user + 1 assistant → roles swapped."""
        original = [
            ModelRequest(parts=[UserPromptPart(content="What's 2+2?")]),
            ModelResponse(parts=[TextPart(content="4")]),
        ]

        inverted = invert_conversation_roles(original)

        assert len(inverted) == 2
        # User request → becomes assistant response
        assert isinstance(inverted[0], ModelResponse)
        assert isinstance(inverted[0].parts[0], TextPart)
        assert inverted[0].parts[0].content == "What's 2+2?"
        # Assistant response → becomes user request
        assert isinstance(inverted[1], ModelRequest)
        assert isinstance(inverted[1].parts[0], UserPromptPart)
        assert inverted[1].parts[0].content == "4"

    def test_empty_list(self):
        """Test empty message list returns empty list."""
        original: list[ModelMessage] = []
        inverted = invert_conversation_roles(original)
        assert inverted == []

    def test_single_user_message(self):
        """Test single user message returns single inverted message."""
        original = [
            ModelRequest(parts=[UserPromptPart(content="Hello")]),
        ]

        inverted = invert_conversation_roles(original)

        assert len(inverted) == 1
        assert isinstance(inverted[0], ModelResponse)
        assert isinstance(inverted[0].parts[0], TextPart)
        assert inverted[0].parts[0].content == "Hello"

    def test_single_assistant_message(self):
        """Test single assistant message returns single inverted message."""
        original = [
            ModelResponse(parts=[TextPart(content="Hi there!")]),
        ]

        inverted = invert_conversation_roles(original)

        assert len(inverted) == 1
        assert isinstance(inverted[0], ModelRequest)
        assert isinstance(inverted[0].parts[0], UserPromptPart)
        assert inverted[0].parts[0].content == "Hi there!"

    def test_interleaved_conversation(self):
        """Test interleaved conversation stays in order but roles flipped."""
        original = [
            ModelRequest(parts=[UserPromptPart(content="Q1")]),
            ModelResponse(parts=[TextPart(content="A1")]),
            ModelRequest(parts=[UserPromptPart(content="Q2")]),
            ModelResponse(parts=[TextPart(content="A2")]),
        ]

        inverted = invert_conversation_roles(original)

        assert len(inverted) == 4
        # Order preserved, but each role flipped
        assert isinstance(inverted[0], ModelResponse)  # was Request
        assert isinstance(inverted[1], ModelRequest)  # was Response
        assert isinstance(inverted[2], ModelResponse)  # was Request
        assert isinstance(inverted[3], ModelRequest)  # was Response
        # Content preserved
        assert inverted[0].parts[0].content == "Q1"
        assert inverted[1].parts[0].content == "A1"
        assert inverted[2].parts[0].content == "Q2"
        assert inverted[3].parts[0].content == "A2"

    def test_system_prompt_preserved(self):
        """Test preserve_system=True keeps system messages."""
        original = [
            ModelRequest(parts=[SystemPromptPart(content="Be helpful")]),
            ModelResponse(parts=[TextPart(content="I will!")]),
        ]

        inverted = invert_conversation_roles(original, preserve_system=True)

        assert len(inverted) == 2
        # System message converted to TextPart in response
        assert isinstance(inverted[0], ModelResponse)
        assert isinstance(inverted[0].parts[0], TextPart)
        assert "Be helpful" in inverted[0].parts[0].content

    def test_system_prompt_dropped(self):
        """Test preserve_system=False drops system messages."""
        original = [
            ModelRequest(parts=[SystemPromptPart(content="Be helpful")]),
            ModelResponse(parts=[TextPart(content="I will!")]),
        ]

        inverted = invert_conversation_roles(original, preserve_system=False)

        # First message (system only) has no parts after filtering, so it's dropped
        # Second message is present
        assert len(inverted) == 1
        assert isinstance(inverted[0], ModelRequest)

    def test_tool_calls_preserved(self):
        """Test preserve_tool_calls=True keeps tool calls and returns."""
        original = [
            ModelRequest(parts=[UserPromptPart(content="Get the weather")]),
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="get_weather",
                        args={"city": "NYC"},
                        tool_call_id="call_1",
                    )
                ]
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="get_weather",
                        content='{"temp": 72}',
                        tool_call_id="call_1",
                    )
                ]
            ),
        ]

        inverted = invert_conversation_roles(original, preserve_tool_calls=True)

        assert len(inverted) == 3
        # User request converted
        assert isinstance(inverted[0], ModelResponse)
        # Tool call preserved as user prompt text
        assert isinstance(inverted[1], ModelRequest)
        assert "get_weather" in inverted[1].parts[0].content
        # Tool return preserved as assistant text
        assert isinstance(inverted[2], ModelResponse)
        assert "get_weather" in inverted[2].parts[0].content

    def test_tool_calls_stripped(self):
        """Test preserve_tool_calls=False removes tool calls and returns.

        When tool calls/returns are the only parts in a message, and they're
        stripped, the entire message is dropped (no empty messages).
        """
        original = [
            ModelRequest(parts=[UserPromptPart(content="Get the weather")]),
            ModelResponse(
                parts=[
                    TextPart(content="I'll help"),
                    ToolCallPart(
                        tool_name="get_weather",
                        args={"city": "NYC"},
                        tool_call_id="call_1",
                    ),
                ]
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="get_weather",
                        content='{"temp": 72}',
                        tool_call_id="call_1",
                    )
                ]
            ),
        ]

        inverted = invert_conversation_roles(original, preserve_tool_calls=False)

        # Third message had only tool return (stripped) → message dropped entirely
        assert len(inverted) == 2
        # First message unchanged (user content)
        assert isinstance(inverted[0], ModelResponse)
        assert inverted[0].parts[0].content == "Get the weather"
        # Second message has only TextPart now (tool call stripped)
        assert isinstance(inverted[1], ModelRequest)
        assert len(inverted[1].parts) == 1
        assert inverted[1].parts[0].content == "I'll help"

    def test_input_immutability(self):
        """Test original list is unchanged after inversion."""
        original = [
            ModelRequest(parts=[UserPromptPart(content="Question")]),
            ModelResponse(parts=[TextPart(content="Answer")]),
        ]
        original_copy = [
            ModelRequest(parts=[UserPromptPart(content="Question")]),
            ModelResponse(parts=[TextPart(content="Answer")]),
        ]

        _ = invert_conversation_roles(original)

        # Original unchanged
        assert len(original) == len(original_copy)
        assert original[0].parts[0].content == original_copy[0].parts[0].content
        assert original[1].parts[0].content == original_copy[1].parts[0].content

    def test_type_preservation(self):
        """Test output is list of ModelMessage objects."""
        original = [
            ModelRequest(parts=[UserPromptPart(content="Q")]),
            ModelResponse(parts=[TextPart(content="A")]),
        ]

        inverted = invert_conversation_roles(original)

        assert isinstance(inverted, list)
        for msg in inverted:
            assert isinstance(msg, (ModelRequest, ModelResponse))

    def test_round_trip(self):
        """Test inverting twice returns to original structure (for system/tool-free conversation)."""
        original = [
            ModelRequest(parts=[UserPromptPart(content="Hello")]),
            ModelResponse(parts=[TextPart(content="Hi!")]),
            ModelRequest(parts=[UserPromptPart(content="How are you?")]),
        ]

        inverted = invert_conversation_roles(original)
        double_inverted = invert_conversation_roles(inverted)

        assert len(double_inverted) == len(original)
        # Structure restored
        assert isinstance(double_inverted[0], ModelRequest)
        assert isinstance(double_inverted[1], ModelResponse)
        assert isinstance(double_inverted[2], ModelRequest)
        # Content preserved
        assert double_inverted[0].parts[0].content == "Hello"
        assert double_inverted[1].parts[0].content == "Hi!"
        assert double_inverted[2].parts[0].content == "How are you?"

    def test_multi_part_message_inversion(self):
        """Test messages with multiple parts are inverted correctly."""
        original = [
            ModelResponse(
                parts=[
                    TextPart(content="First sentence."),
                    TextPart(content="Second sentence."),
                ]
            ),
        ]

        inverted = invert_conversation_roles(original)

        assert len(inverted) == 1
        assert isinstance(inverted[0], ModelRequest)
        # Both text parts become user prompt parts
        assert len(inverted[0].parts) == 2
        assert isinstance(inverted[0].parts[0], UserPromptPart)
        assert isinstance(inverted[0].parts[1], UserPromptPart)
        assert inverted[0].parts[0].content == "First sentence."
        assert inverted[0].parts[1].content == "Second sentence."

    def test_complex_conversation_with_all_part_types(self):
        """Test complex conversation with all part types handled correctly."""
        original = [
            ModelRequest(
                parts=[
                    SystemPromptPart(content="System instruction"),
                    UserPromptPart(content="User question"),
                ]
            ),
            ModelResponse(
                parts=[
                    TextPart(content="Response text"),
                    ToolCallPart(
                        tool_name="search",
                        args={"query": "test"},
                        tool_call_id="call_1",
                    ),
                ]
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="search",
                        content='{"results": []}',
                        tool_call_id="call_1",
                    ),
                ]
            ),
            ModelResponse(
                parts=[TextPart(content="Final answer")],
            ),
        ]

        inverted = invert_conversation_roles(
            original, preserve_system=True, preserve_tool_calls=True
        )

        assert len(inverted) == 4

        # First message: System + User → Response with both
        assert isinstance(inverted[0], ModelResponse)
        assert len(inverted[0].parts) == 2
        assert "System:" in inverted[0].parts[0].content
        assert inverted[0].parts[1].content == "User question"

        # Second message: Text + ToolCall → Request with both
        assert isinstance(inverted[1], ModelRequest)
        assert len(inverted[1].parts) == 2
        assert inverted[1].parts[0].content == "Response text"
        assert "search" in inverted[1].parts[1].content

        # Third message: ToolReturn → Response with tool info
        assert isinstance(inverted[2], ModelResponse)
        assert len(inverted[2].parts) == 1
        assert "search" in inverted[2].parts[0].content

        # Fourth message: Text → Request with user prompt
        assert isinstance(inverted[3], ModelRequest)
        assert len(inverted[3].parts) == 1
        assert inverted[3].parts[0].content == "Final answer"

    def test_timestamp_is_updated(self):
        """Test that inverted messages get new timestamps."""
        past = datetime(2020, 1, 1, tzinfo=timezone.utc)
        original = [
            ModelRequest(
                parts=[UserPromptPart(content="Old message")],
                timestamp=past,
            ),
        ]

        inverted = invert_conversation_roles(original)

        assert len(inverted) == 1
        assert isinstance(inverted[0], ModelResponse)
        # Timestamp should be updated (not the original past date)
        assert inverted[0].timestamp > past

    def test_iterable_input_accepted(self):
        """Test that function accepts any Iterable, not just list."""

        def message_generator():
            yield ModelRequest(parts=[UserPromptPart(content="From generator")])
            yield ModelResponse(parts=[TextPart(content="Response")])

        inverted = invert_conversation_roles(message_generator())

        assert len(inverted) == 2
        assert isinstance(inverted[0], ModelResponse)
        assert isinstance(inverted[1], ModelRequest)


class TestInvertConversationRolesEdgeCases:
    """Edge case tests for invert_conversation_roles."""

    def test_message_with_only_system_prompt(self):
        """Test message with only system prompt (dropped if preserve_system=False)."""
        original = [
            ModelRequest(parts=[SystemPromptPart(content="System only")]),
        ]

        inverted_with = invert_conversation_roles(original, preserve_system=True)
        inverted_without = invert_conversation_roles(original, preserve_system=False)

        # With preserve: converted to text
        assert len(inverted_with) == 1
        assert isinstance(inverted_with[0], ModelResponse)

        # Without preserve: empty parts, message dropped
        assert len(inverted_without) == 0

    def test_message_with_only_tool_call(self):
        """Test message with only tool call."""
        original = [
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="test_tool",
                        args={},
                        tool_call_id="call_1",
                    ),
                ]
            ),
        ]

        inverted_with = invert_conversation_roles(original, preserve_tool_calls=True)
        inverted_without = invert_conversation_roles(
            original, preserve_tool_calls=False
        )

        # With preserve: converted to user prompt
        assert len(inverted_with) == 1
        assert isinstance(inverted_with[0], ModelRequest)

        # Without preserve: empty parts, message dropped
        assert len(inverted_without) == 0

    def test_message_with_only_tool_return(self):
        """Test message with only tool return."""
        original = [
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="test_tool",
                        content="result",
                        tool_call_id="call_1",
                    ),
                ]
            ),
        ]

        inverted_with = invert_conversation_roles(original, preserve_tool_calls=True)
        inverted_without = invert_conversation_roles(
            original, preserve_tool_calls=False
        )

        # With preserve: converted to text in response
        assert len(inverted_with) == 1
        assert isinstance(inverted_with[0], ModelResponse)

        # Without preserve: empty parts, message dropped
        assert len(inverted_without) == 0
