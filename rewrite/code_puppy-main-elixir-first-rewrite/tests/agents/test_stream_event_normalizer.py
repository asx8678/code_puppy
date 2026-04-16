"""Tests for stream_event_normalizer module."""

import pytest
from code_puppy.agents.stream_event_normalizer import (
    normalize_stream_event,
    get_stream_content_for_token_estimation,
    _extract_part_kind_from_start,
    _map_delta_type_to_part_kind,
    _extract_tool_name,
)


class MockDelta:
    """Mock delta object for testing main agent format."""

    def __init__(self, content_delta=None, args_delta=None, tool_name_delta=None, tool_name=None):
        self.content_delta = content_delta
        self.args_delta = args_delta
        self.tool_name_delta = tool_name_delta
        self.tool_name = tool_name


class TestNormalizeStreamEvent:
    """Test cases for normalize_stream_event function."""

    def test_part_start_text(self):
        """Test normalizing part_start event for text part."""
        event_data = {
            "index": 0,
            "part_type": "TextPart",
            "part": None,  # Would be actual part object
        }

        result = normalize_stream_event("part_start", event_data)

        assert result["index"] == 0
        assert result["part_kind"] == "text"
        assert result["content_delta"] is None
        assert result["args_delta"] is None
        assert result["tool_name"] is None
        assert "raw" in result

    def test_part_start_thinking(self):
        """Test normalizing part_start event for thinking part."""
        event_data = {
            "index": 1,
            "part_type": "ThinkingPart",
            "part": None,
        }

        result = normalize_stream_event("part_start", event_data)

        assert result["index"] == 1
        assert result["part_kind"] == "thinking"

    def test_part_start_tool_call(self):
        """Test normalizing part_start event for tool call part."""
        event_data = {
            "index": 2,
            "part_type": "ToolCallPart",
            "tool_name": "my_tool",
            "part": None,
        }

        result = normalize_stream_event("part_start", event_data)

        assert result["index"] == 2
        assert result["part_kind"] == "tool_call"
        assert result["tool_name"] == "my_tool"

    def test_part_start_with_content(self):
        """Test normalizing part_start event that includes initial content."""
        event_data = {
            "index": 0,
            "part_type": "TextPart",
            "content": "Hello world",
            "part": None,
        }

        result = normalize_stream_event("part_start", event_data)

        assert result["content_delta"] == "Hello world"

    def test_part_delta_text_subagent_format(self):
        """Test normalizing part_delta for text in subagent format."""
        event_data = {
            "index": 0,
            "delta_type": "TextPartDelta",
            "content_delta": "Hello ",
        }

        result = normalize_stream_event("part_delta", event_data)

        assert result["index"] == 0
        assert result["part_kind"] == "text"
        assert result["content_delta"] == "Hello "
        assert result["args_delta"] is None

    def test_part_delta_thinking_subagent_format(self):
        """Test normalizing part_delta for thinking in subagent format."""
        event_data = {
            "index": 1,
            "delta_type": "ThinkingPartDelta",
            "content_delta": "Analyzing...",
        }

        result = normalize_stream_event("part_delta", event_data)

        assert result["part_kind"] == "thinking"
        assert result["content_delta"] == "Analyzing..."

    def test_part_delta_tool_call_subagent_format(self):
        """Test normalizing part_delta for tool call in subagent format."""
        event_data = {
            "index": 2,
            "delta_type": "ToolCallPartDelta",
            "args_delta": '{"arg": "value"}',
            "tool_name_delta": "my_to",
        }

        result = normalize_stream_event("part_delta", event_data)

        assert result["part_kind"] == "tool_call"
        assert result["args_delta"] == '{"arg": "value"}'
        assert result["tool_name_delta"] == "my_to"

    def test_part_delta_text_main_agent_format(self):
        """Test normalizing part_delta for text in main agent format (with delta object)."""
        delta = MockDelta(content_delta="World!")
        event_data = {
            "index": 0,
            "delta_type": "TextPartDelta",
            "delta": delta,
        }

        result = normalize_stream_event("part_delta", event_data)

        assert result["index"] == 0
        assert result["part_kind"] == "text"
        assert result["content_delta"] == "World!"

    def test_part_delta_tool_call_main_agent_format(self):
        """Test normalizing part_delta for tool call in main agent format."""
        delta = MockDelta(args_delta='{"key": "val"}', tool_name_delta="ol")
        event_data = {
            "index": 2,
            "delta_type": "ToolCallPartDelta",
            "delta": delta,
        }

        result = normalize_stream_event("part_delta", event_data)

        assert result["part_kind"] == "tool_call"
        assert result["args_delta"] == '{"key": "val"}'
        assert result["tool_name_delta"] == "ol"

    def test_part_end(self):
        """Test normalizing part_end event."""
        event_data = {
            "index": 0,
            "next_part_kind": "text",
        }

        result = normalize_stream_event("part_end", event_data)

        assert result["index"] == 0
        assert result["part_kind"] == "text"

    def test_unknown_delta_type(self):
        """Test handling unknown delta type."""
        event_data = {
            "index": 0,
            "delta_type": "UnknownDelta",
        }

        result = normalize_stream_event("part_delta", event_data)

        assert result["part_kind"] == "unknown"

    def test_preserves_raw_event(self):
        """Test that raw event data is preserved."""
        event_data = {
            "index": 5,
            "delta_type": "TextPartDelta",
            "content_delta": "test",
            "extra_field": "preserved",
        }

        result = normalize_stream_event("part_delta", event_data)

        assert "raw" in result
        assert result["raw"]["index"] == 5
        assert result["raw"]["extra_field"] == "preserved"


class TestGetStreamContentForTokenEstimation:
    """Test cases for get_stream_content_for_token_estimation function."""

    def test_content_delta_only(self):
        """Test extracting content from content_delta field."""
        event_data = {
            "content_delta": "Hello world",
            "args_delta": None,
            "tool_name_delta": None,
        }

        result = get_stream_content_for_token_estimation(event_data)

        assert result == "Hello world"

    def test_args_delta_only(self):
        """Test extracting content from args_delta field."""
        event_data = {
            "content_delta": None,
            "args_delta": '{"arg": "value"}',
            "tool_name_delta": None,
        }

        result = get_stream_content_for_token_estimation(event_data)

        assert result == '{"arg": "value"}'

    def test_multiple_deltas(self):
        """Test extracting content from multiple delta fields."""
        event_data = {
            "content_delta": "Thinking... ",
            "args_delta": '{"key": "val"}',
            "tool_name_delta": "tool",
        }

        result = get_stream_content_for_token_estimation(event_data)

        assert result == 'Thinking... {"key": "val"}tool'

    def test_all_none(self):
        """Test handling when all delta fields are None."""
        event_data = {
            "content_delta": None,
            "args_delta": None,
            "tool_name_delta": None,
        }

        result = get_stream_content_for_token_estimation(event_data)

        assert result == ""

    def test_empty_event_data(self):
        """Test handling empty event data."""
        result = get_stream_content_for_token_estimation({})

        assert result == ""


class TestExtractPartKindFromStart:
    """Test cases for _extract_part_kind_from_start function."""

    def test_text_part(self):
        """Test extracting kind for TextPart."""
        result = _extract_part_kind_from_start({"part_type": "TextPart"})
        assert result == "text"

    def test_thinking_part(self):
        """Test extracting kind for ThinkingPart."""
        result = _extract_part_kind_from_start({"part_type": "ThinkingPart"})
        assert result == "thinking"

    def test_tool_call_part(self):
        """Test extracting kind for ToolCallPart."""
        result = _extract_part_kind_from_start({"part_type": "ToolCallPart"})
        assert result == "tool_call"

    def test_unknown_part(self):
        """Test extracting kind for unknown part type."""
        result = _extract_part_kind_from_start({"part_type": "UnknownPart"})
        assert result == "unknown"

    def test_missing_part_type(self):
        """Test handling missing part_type field."""
        result = _extract_part_kind_from_start({})
        assert result == "unknown"


class TestMapDeltaTypeToPartKind:
    """Test cases for _map_delta_type_to_part_kind function."""

    def test_text_delta(self):
        """Test mapping TextPartDelta."""
        result = _map_delta_type_to_part_kind("TextPartDelta")
        assert result == "text"

    def test_thinking_delta(self):
        """Test mapping ThinkingPartDelta."""
        result = _map_delta_type_to_part_kind("ThinkingPartDelta")
        assert result == "thinking"

    def test_tool_call_delta(self):
        """Test mapping ToolCallPartDelta."""
        result = _map_delta_type_to_part_kind("ToolCallPartDelta")
        assert result == "tool_call"

    def test_unknown_delta(self):
        """Test mapping unknown delta type."""
        result = _map_delta_type_to_part_kind("UnknownDelta")
        assert result == "unknown"


class TestExtractToolName:
    """Test cases for _extract_tool_name function."""

    def test_direct_field(self):
        """Test extracting tool_name from direct field."""
        result = _extract_tool_name({"tool_name": "my_tool"})
        assert result == "my_tool"

    def test_from_delta_object(self):
        """Test extracting tool_name from delta object."""
        delta = MockDelta(tool_name="delta_tool")
        result = _extract_tool_name({"delta": delta})
        assert result == "delta_tool"

    def test_direct_field_priority(self):
        """Test that direct field takes priority over delta object."""
        delta = MockDelta(tool_name="delta_tool")
        result = _extract_tool_name({"tool_name": "direct_tool", "delta": delta})
        assert result == "direct_tool"

    def test_missing_tool_name(self):
        """Test handling when tool_name is not present."""
        result = _extract_tool_name({"other_field": "value"})
        assert result is None

    def test_none_delta(self):
        """Test handling when delta is None."""
        result = _extract_tool_name({"delta": None})
        assert result is None
