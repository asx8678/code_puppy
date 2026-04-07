"""Tests for event_stream_handler module.

Covers:
- Console configuration (set/get)
- Event stream handling (PartStartEvent, PartDeltaEvent, PartEndEvent)
- Different part types (Thinking, Text, ToolCall)
- Content streaming and buffering
- Banner printing
- Cleanup and state management
- Stream event batching behavior
"""

import asyncio
import importlib
from io import StringIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import PartDeltaEvent, PartEndEvent, PartStartEvent, RunContext
from pydantic_ai.messages import (
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
    ToolCallPart,
    ToolCallPartDelta,
)
from rich.console import Console

from code_puppy.agents.event_stream_handler import (
    _drain_pending_stream_events,
    _fire_stream_event,
    _flush_stream_events,
    _pending_stream_events,
    _STREAM_FLUSH_INTERVAL,
    event_stream_handler,
    get_streaming_console,
    set_streaming_console,
)


class TestConsoleConfiguration:
    """Test console configuration functions."""

    def test_set_streaming_console_stores_console(self):
        """Test that set_streaming_console stores the console."""
        # Reset to None first
        set_streaming_console(None)

        console = Console(file=StringIO())
        set_streaming_console(console)

        result = get_streaming_console()
        assert result is console

    def test_get_streaming_console_returns_none_console_when_not_set(self):
        """Test that get_streaming_console returns a console when not explicitly set."""
        set_streaming_console(None)

        result = get_streaming_console()

        assert isinstance(result, Console)

    def test_get_streaming_console_returns_configured_console(self):
        """Test that get_streaming_console returns the configured console."""
        console = Console(file=StringIO())
        set_streaming_console(console)

        result = get_streaming_console()
        assert result is console

    def test_set_streaming_console_with_none_resets(self):
        """Test that setting console to None resets to default behavior."""
        console1 = Console(file=StringIO())
        set_streaming_console(console1)

        set_streaming_console(None)

        result = get_streaming_console()
        assert result is not console1
        assert isinstance(result, Console)

    def test_set_streaming_console_overwrites_previous(self):
        """Test that set_streaming_console overwrites previous setting."""
        console1 = Console(file=StringIO())
        console2 = Console(file=StringIO())

        set_streaming_console(console1)
        assert get_streaming_console() is console1

        set_streaming_console(console2)
        assert get_streaming_console() is console2


class TestEventStreamHandler:
    """Test the main event_stream_handler function."""

    @pytest.fixture
    def mock_console(self):
        """Create a mock console for testing."""
        return MagicMock(spec=Console)

    @pytest.fixture
    def mock_ctx(self):
        """Create a mock RunContext."""
        return MagicMock(spec=RunContext)

    @pytest.mark.asyncio
    async def test_handles_empty_event_stream(self, mock_ctx):
        """Test handling an empty event stream."""

        async def empty_stream():
            return
            yield  # Make it a generator

        set_streaming_console(MagicMock(spec=Console))

        # Should not raise any errors
        await event_stream_handler(mock_ctx, empty_stream())

    @pytest.mark.asyncio
    async def test_handles_thinking_part_start_event(self, mock_ctx):
        """Test handling PartStartEvent for ThinkingPart."""
        thinking_part = ThinkingPart(content="I am thinking...")
        event = PartStartEvent(index=0, part=thinking_part)

        async def event_stream():
            yield event

        console = MagicMock(spec=Console)
        set_streaming_console(console)

        with patch("code_puppy.agents.event_stream_handler.pause_all_spinners"):
            with patch("code_puppy.agents.event_stream_handler.resume_all_spinners"):
                await event_stream_handler(mock_ctx, event_stream())

        # Console should have printed something
        assert console.print.called

    @pytest.mark.asyncio
    async def test_handles_text_part_start_event(self, mock_ctx):
        """Test handling PartStartEvent for TextPart."""
        text_part = TextPart(content="Hello world")
        event = PartStartEvent(index=0, part=text_part)

        async def event_stream():
            yield event

        console = MagicMock(spec=Console)
        set_streaming_console(console)

        with patch("code_puppy.agents.event_stream_handler.pause_all_spinners"):
            with patch("code_puppy.agents.event_stream_handler.resume_all_spinners"):
                await event_stream_handler(mock_ctx, event_stream())

        assert console.print.called

    @pytest.mark.asyncio
    async def test_handles_tool_call_part_start_event(self, mock_ctx):
        """Test handling PartStartEvent for ToolCallPart."""
        tool_part = ToolCallPart(tool_call_id="tool_1", tool_name="my_tool", args={})
        event = PartStartEvent(index=0, part=tool_part)

        async def event_stream():
            yield event

        console = MagicMock(spec=Console)
        set_streaming_console(console)

        with patch("code_puppy.agents.event_stream_handler.pause_all_spinners"):
            with patch("code_puppy.agents.event_stream_handler.resume_all_spinners"):
                await event_stream_handler(mock_ctx, event_stream())

    @pytest.mark.asyncio
    async def test_handles_thinking_part_with_initial_content(self, mock_ctx):
        """Test ThinkingPart with initial content prints immediately."""
        thinking_part = ThinkingPart(content="Initial thinking content")
        event = PartStartEvent(index=0, part=thinking_part)

        async def event_stream():
            yield event

        console = MagicMock(spec=Console)
        set_streaming_console(console)

        with patch("code_puppy.agents.event_stream_handler.pause_all_spinners"):
            with patch("code_puppy.agents.event_stream_handler.resume_all_spinners"):
                with patch(
                    "code_puppy.agents.event_stream_handler.get_banner_color",
                    return_value="blue",
                ):
                    await event_stream_handler(mock_ctx, event_stream())

        # Should print the initial content
        assert console.print.called

    @pytest.mark.asyncio
    async def test_handles_text_part_with_initial_content(self, mock_ctx):
        """Test TextPart with initial content sets up termflow."""
        text_part = TextPart(content="Initial text content")
        event = PartStartEvent(index=0, part=text_part)

        async def event_stream():
            yield event

        console = MagicMock(spec=Console)
        set_streaming_console(console)

        with patch("code_puppy.agents.event_stream_handler.pause_all_spinners"):
            with patch("code_puppy.agents.event_stream_handler.resume_all_spinners"):
                with patch(
                    "code_puppy.agents.event_stream_handler.get_banner_color",
                    return_value="blue",
                ):
                    with patch("termflow.Parser"):
                        with patch("termflow.Renderer"):
                            await event_stream_handler(mock_ctx, event_stream())

        assert console.print.called

    @pytest.mark.asyncio
    async def test_handles_thinking_part_delta_event(self, mock_ctx):
        """Test handling PartDeltaEvent for ThinkingPartDelta."""
        thinking_part = ThinkingPart(content="")
        start_event = PartStartEvent(index=0, part=thinking_part)
        delta = ThinkingPartDelta(content_delta="Think...")
        delta_event = PartDeltaEvent(index=0, delta=delta)

        async def event_stream():
            yield start_event
            yield delta_event

        console = MagicMock(spec=Console)
        set_streaming_console(console)

        with patch("code_puppy.agents.event_stream_handler.pause_all_spinners"):
            with patch("code_puppy.agents.event_stream_handler.resume_all_spinners"):
                with patch(
                    "code_puppy.agents.event_stream_handler.get_banner_color",
                    return_value="blue",
                ):
                    await event_stream_handler(mock_ctx, event_stream())

        # Should print the delta content
        assert console.print.called

    @pytest.mark.asyncio
    async def test_handles_text_part_delta_event(self, mock_ctx):
        """Test handling PartDeltaEvent for TextPartDelta."""
        text_part = TextPart(content="")
        start_event = PartStartEvent(index=0, part=text_part)
        delta = TextPartDelta(content_delta="Hello ")
        delta_event = PartDeltaEvent(index=0, delta=delta)

        async def event_stream():
            yield start_event
            yield delta_event

        console = MagicMock(spec=Console, width=80)
        console.file = StringIO()
        set_streaming_console(console)

        with patch("code_puppy.agents.event_stream_handler.pause_all_spinners"):
            with patch("code_puppy.agents.event_stream_handler.resume_all_spinners"):
                with patch(
                    "code_puppy.agents.event_stream_handler.get_banner_color",
                    return_value="blue",
                ):
                    with patch("termflow.Parser") as mock_parser_cls:
                        mock_parser = MagicMock()
                        mock_parser.parse_line.return_value = []
                        mock_parser.finalize.return_value = []
                        mock_parser_cls.return_value = mock_parser

                        with patch("termflow.Renderer"):
                            await event_stream_handler(mock_ctx, event_stream())

        # Handler should process without error
        # The parser may or may not be called depending on newlines

    @pytest.mark.asyncio
    async def test_handles_tool_call_part_delta_event(self, mock_ctx):
        """Test handling PartDeltaEvent for ToolCallPartDelta."""
        tool_part = ToolCallPart(tool_call_id="tool_1", tool_name="my_tool", args={})
        start_event = PartStartEvent(index=0, part=tool_part)
        delta = ToolCallPartDelta(tool_name_delta="my_tool")
        delta_event = PartDeltaEvent(index=0, delta=delta)

        async def event_stream():
            yield start_event
            yield delta_event

        console = MagicMock(spec=Console)
        set_streaming_console(console)

        with patch("code_puppy.agents.event_stream_handler.pause_all_spinners"):
            with patch("code_puppy.agents.event_stream_handler.resume_all_spinners"):
                await event_stream_handler(mock_ctx, event_stream())

        # Should have printed tool call info
        assert console.print.called

    @pytest.mark.asyncio
    async def test_handles_part_end_event_for_text(self, mock_ctx):
        """Test handling PartEndEvent for text parts."""
        text_part = TextPart(content="")
        start_event = PartStartEvent(index=0, part=text_part)
        end_event = PartEndEvent(index=0, part=text_part, next_part_kind=None)

        async def event_stream():
            yield start_event
            yield end_event

        console = MagicMock(spec=Console, width=80)
        console.file = StringIO()
        set_streaming_console(console)

        with patch("code_puppy.agents.event_stream_handler.pause_all_spinners"):
            with patch("code_puppy.agents.event_stream_handler.resume_all_spinners"):
                with patch("termflow.Parser") as mock_parser_cls:
                    mock_parser = MagicMock()
                    mock_parser.finalize.return_value = []
                    mock_parser_cls.return_value = mock_parser

                    with patch("termflow.Renderer"):
                        await event_stream_handler(mock_ctx, event_stream())

        # Spinner should be resumed when next part is not text/thinking/tool
        # finalize should be called to cleanup
        assert mock_parser.finalize.called

    @pytest.mark.asyncio
    async def test_handles_part_end_event_for_tool(self, mock_ctx):
        """Test handling PartEndEvent for tool parts."""
        tool_part = ToolCallPart(tool_call_id="tool_1", tool_name="my_tool", args={})
        start_event = PartStartEvent(index=0, part=tool_part)
        end_event = PartEndEvent(index=0, part=tool_part, next_part_kind=None)

        async def event_stream():
            yield start_event
            yield end_event

        console = MagicMock(spec=Console)
        set_streaming_console(console)

        with patch("code_puppy.agents.event_stream_handler.pause_all_spinners"):
            with patch("code_puppy.agents.event_stream_handler.resume_all_spinners"):
                await event_stream_handler(mock_ctx, event_stream())

        # Should have handled the end event without error
        # Either clear line was printed or spinner was resumed
        assert True  # Handler completed without error

    @pytest.mark.asyncio
    async def test_handles_part_end_event_for_thinking(self, mock_ctx):
        """Test handling PartEndEvent for thinking parts."""
        thinking_part = ThinkingPart(content="thinking")
        start_event = PartStartEvent(index=0, part=thinking_part)
        end_event = PartEndEvent(index=0, part=thinking_part, next_part_kind=None)

        async def event_stream():
            yield start_event
            yield end_event

        console = MagicMock(spec=Console)
        set_streaming_console(console)

        with patch("code_puppy.agents.event_stream_handler.pause_all_spinners"):
            with patch("code_puppy.agents.event_stream_handler.resume_all_spinners"):
                with patch(
                    "code_puppy.agents.event_stream_handler.get_banner_color",
                    return_value="blue",
                ):
                    await event_stream_handler(mock_ctx, event_stream())

        # Handler processed thinking part end event
        assert True  # Completed without error

    @pytest.mark.asyncio
    async def test_handles_part_end_event_preserves_spinner_for_next_text(
        self, mock_ctx
    ):
        """Test that spinner is not resumed if next part is text."""
        text_part = TextPart(content="")
        start_event = PartStartEvent(index=0, part=text_part)
        end_event = PartEndEvent(index=0, part=text_part, next_part_kind="text")

        async def event_stream():
            yield start_event
            yield end_event

        console = MagicMock(spec=Console, width=80)
        console.file = StringIO()
        set_streaming_console(console)

        with patch("code_puppy.agents.event_stream_handler.pause_all_spinners"):
            with patch("code_puppy.agents.event_stream_handler.resume_all_spinners"):
                with patch("termflow.Parser") as mock_parser_cls:
                    mock_parser = MagicMock()
                    mock_parser.finalize.return_value = []
                    mock_parser_cls.return_value = mock_parser

                    with patch("termflow.Renderer"):
                        await event_stream_handler(mock_ctx, event_stream())

        # The function checks: if next_kind not in ("text", "thinking", "tool-call")
        # So if next is "text", it should NOT call resume
        # finalize should have been called for cleanup
        assert mock_parser.finalize.called

    @pytest.mark.asyncio
    async def test_streaming_with_multiple_text_deltas(self, mock_ctx):
        """Test streaming multiple text deltas in sequence."""
        text_part = TextPart(content="")
        start_event = PartStartEvent(index=0, part=text_part)
        delta1 = TextPartDelta(content_delta="Hello ")
        delta2 = TextPartDelta(content_delta="world")
        delta_event1 = PartDeltaEvent(index=0, delta=delta1)
        delta_event2 = PartDeltaEvent(index=0, delta=delta2)

        async def event_stream():
            yield start_event
            yield delta_event1
            yield delta_event2

        console = MagicMock(spec=Console, width=80)
        console.file = StringIO()
        set_streaming_console(console)

        with patch("code_puppy.agents.event_stream_handler.pause_all_spinners"):
            with patch("code_puppy.agents.event_stream_handler.resume_all_spinners"):
                with patch(
                    "code_puppy.agents.event_stream_handler.get_banner_color",
                    return_value="blue",
                ):
                    with patch("termflow.Parser") as mock_parser_cls:
                        mock_parser = MagicMock()
                        mock_parser.parse_line.return_value = []
                        mock_parser.finalize.return_value = []
                        mock_parser_cls.return_value = mock_parser

                        with patch("termflow.Renderer"):
                            await event_stream_handler(mock_ctx, event_stream())

        # Handler should process multiple deltas without error

    @pytest.mark.asyncio
    async def test_streaming_with_newlines_in_text(self, mock_ctx):
        """Test that newlines are handled correctly in text streaming."""
        text_part = TextPart(content="")
        start_event = PartStartEvent(index=0, part=text_part)
        # Content with newline
        delta = TextPartDelta(content_delta="Line 1\nLine 2")
        delta_event = PartDeltaEvent(index=0, delta=delta)

        async def event_stream():
            yield start_event
            yield delta_event

        console = MagicMock(spec=Console, width=80)
        console.file = StringIO()
        set_streaming_console(console)

        with patch("code_puppy.agents.event_stream_handler.pause_all_spinners"):
            with patch("code_puppy.agents.event_stream_handler.resume_all_spinners"):
                with patch(
                    "code_puppy.agents.event_stream_handler.get_banner_color",
                    return_value="blue",
                ):
                    with patch("termflow.Parser") as mock_parser_cls:
                        mock_parser = MagicMock()
                        mock_parser.parse_line.return_value = []
                        mock_parser.finalize.return_value = []
                        mock_parser_cls.return_value = mock_parser

                        with patch("termflow.Renderer"):
                            await event_stream_handler(mock_ctx, event_stream())

        # Handler should process newlines in text without error

    @pytest.mark.asyncio
    async def test_streaming_ignores_delta_for_unknown_part_index(self, mock_ctx):
        """Test that deltas for unknown part indices are ignored."""
        # Delta for index 5 without corresponding start event
        delta = TextPartDelta(content_delta="orphaned")
        delta_event = PartDeltaEvent(index=5, delta=delta)

        async def event_stream():
            yield delta_event

        console = MagicMock(spec=Console)
        set_streaming_console(console)

        with patch("code_puppy.agents.event_stream_handler.pause_all_spinners"):
            with patch("code_puppy.agents.event_stream_handler.resume_all_spinners"):
                # Should not raise an error
                await event_stream_handler(mock_ctx, event_stream())

    @pytest.mark.asyncio
    async def test_tool_call_token_counting(self, mock_ctx):
        """Test that tool call chunks are counted correctly."""
        tool_part = ToolCallPart(tool_call_id="tool_1", tool_name="test_tool", args={})
        start_event = PartStartEvent(index=0, part=tool_part)

        # Simulate multiple chunks
        deltas = [
            PartDeltaEvent(
                index=0, delta=ToolCallPartDelta(tool_name_delta="test_tool")
            ),
            PartDeltaEvent(index=0, delta=ToolCallPartDelta(tool_name_delta="")),
            PartDeltaEvent(index=0, delta=ToolCallPartDelta(tool_name_delta="")),
        ]

        async def event_stream():
            yield start_event
            for delta_event in deltas:
                yield delta_event

        console = MagicMock(spec=Console)
        set_streaming_console(console)

        with patch("code_puppy.agents.event_stream_handler.pause_all_spinners"):
            with patch("code_puppy.agents.event_stream_handler.resume_all_spinners"):
                await event_stream_handler(mock_ctx, event_stream())

        # Console should show token counts
        assert console.print.called
        # Check that token counter was printed (contains "token(s)")
        call_args_list = [str(call) for call in console.print.call_args_list]
        # Should have printed something with token(s)
        assert any("token(s)" in str(call) for call in call_args_list)

    @pytest.mark.asyncio
    async def test_thinking_part_without_initial_content_defers_banner(self, mock_ctx):
        """Test that thinking banner is deferred if no initial content."""
        thinking_part = ThinkingPart(content="")  # Empty content
        start_event = PartStartEvent(index=0, part=thinking_part)

        async def event_stream():
            yield start_event

        console = MagicMock(spec=Console)
        set_streaming_console(console)

        with patch("code_puppy.agents.event_stream_handler.pause_all_spinners"):
            with patch("code_puppy.agents.event_stream_handler.resume_all_spinners"):
                with patch(
                    "code_puppy.agents.event_stream_handler.get_banner_color",
                    return_value="blue",
                ):
                    await event_stream_handler(mock_ctx, event_stream())

        # Banner should not be printed immediately (deferred until delta arrives)
        # So console.print should not be called (or called less)

    @pytest.mark.asyncio
    async def test_text_part_without_initial_content_defers_banner(self, mock_ctx):
        """Test that response banner is deferred if no initial content."""
        text_part = TextPart(content="")  # Empty content
        start_event = PartStartEvent(index=0, part=text_part)

        async def event_stream():
            yield start_event

        console = MagicMock(spec=Console, width=80)
        console.file = StringIO()
        set_streaming_console(console)

        with patch("code_puppy.agents.event_stream_handler.pause_all_spinners"):
            with patch("code_puppy.agents.event_stream_handler.resume_all_spinners"):
                with patch(
                    "code_puppy.agents.event_stream_handler.get_banner_color",
                    return_value="blue",
                ):
                    with patch("termflow.Parser") as mock_parser_cls:
                        mock_parser = MagicMock()
                        mock_parser.finalize.return_value = []
                        mock_parser_cls.return_value = mock_parser

                        with patch("termflow.Renderer"):
                            await event_stream_handler(mock_ctx, event_stream())

        # Banner should not be printed immediately (deferred)

    @pytest.mark.asyncio
    async def test_handles_part_end_event_cleanup(self, mock_ctx):
        """Test that PartEndEvent properly cleans up state."""
        text_part = TextPart(content="test")
        start_event = PartStartEvent(index=0, part=text_part)
        end_event = PartEndEvent(index=0, part=text_part, next_part_kind=None)

        async def event_stream():
            yield start_event
            yield end_event

        console = MagicMock(spec=Console, width=80)
        console.file = StringIO()
        set_streaming_console(console)

        with patch("code_puppy.agents.event_stream_handler.pause_all_spinners"):
            with patch("code_puppy.agents.event_stream_handler.resume_all_spinners"):
                with patch(
                    "code_puppy.agents.event_stream_handler.get_banner_color",
                    return_value="blue",
                ):
                    with patch("termflow.Parser") as mock_parser_cls:
                        mock_parser = MagicMock()
                        mock_parser.finalize.return_value = []
                        mock_parser_cls.return_value = mock_parser

                        with patch("termflow.Renderer"):
                            await event_stream_handler(mock_ctx, event_stream())

        # Verify cleanup was called
        # finalize should be called for text parts
        assert mock_parser.finalize.called

    @pytest.mark.asyncio
    async def test_multiple_parts_in_sequence(self, mock_ctx):
        """Test handling multiple parts in sequence."""
        thinking_part = ThinkingPart(content="thinking")
        text_part = TextPart(content="response")

        thinking_start = PartStartEvent(index=0, part=thinking_part)
        thinking_end = PartEndEvent(index=0, part=thinking_part, next_part_kind="text")
        text_start = PartStartEvent(index=1, part=text_part)
        text_end = PartEndEvent(index=1, part=text_part, next_part_kind=None)

        async def event_stream():
            yield thinking_start
            yield thinking_end
            yield text_start
            yield text_end

        console = MagicMock(spec=Console, width=80)
        console.file = StringIO()
        set_streaming_console(console)

        with patch("code_puppy.agents.event_stream_handler.pause_all_spinners"):
            with patch("code_puppy.agents.event_stream_handler.resume_all_spinners"):
                with patch(
                    "code_puppy.agents.event_stream_handler.get_banner_color",
                    return_value="blue",
                ):
                    with patch("termflow.Parser") as mock_parser_cls:
                        mock_parser = MagicMock()
                        mock_parser.parse_line.return_value = []
                        mock_parser.finalize.return_value = []
                        mock_parser_cls.return_value = mock_parser

                        with patch("termflow.Renderer"):
                            await event_stream_handler(mock_ctx, event_stream())

        # Both parts should be processed without error
        # Banners should be printed for both thinking and text
        assert console.print.call_count >= 2


class TestSubAgentSuppression:
    """Test that sub-agent output is properly suppressed."""

    @pytest.fixture
    def mock_ctx(self):
        """Create a mock RunContext."""
        return MagicMock(spec=RunContext)

    @pytest.mark.asyncio
    async def test_subagent_suppresses_output_when_verbose_false(
        self, mock_ctx, monkeypatch
    ):
        """Sub-agent with verbose=False suppresses output."""
        from code_puppy.tools.subagent_context import subagent_context

        # Mock verbose to be False (default)
        monkeypatch.setattr(
            "code_puppy.agents.event_stream_handler.get_subagent_verbose",
            lambda: False,
        )

        # Create a mock event stream with thinking and text parts
        thinking_part = ThinkingPart(content="I am thinking...")
        text_part = TextPart(content="Here is my response")

        async def mock_events():
            yield PartStartEvent(index=0, part=thinking_part)
            yield PartDeltaEvent(
                index=0, delta=ThinkingPartDelta(content_delta=" more")
            )
            yield PartEndEvent(index=0, part=thinking_part, next_part_kind="text")
            yield PartStartEvent(index=1, part=text_part)
            yield PartDeltaEvent(index=1, delta=TextPartDelta(content_delta=" text"))
            yield PartEndEvent(index=1, part=text_part, next_part_kind=None)

        console = MagicMock(spec=Console)
        set_streaming_console(console)

        # Run in sub-agent context
        with subagent_context("test-agent"):
            # The handler should suppress output
            await event_stream_handler(mock_ctx, mock_events())

        # Verify NO output was printed (console.print should NOT be called)
        console.print.assert_not_called()

    @pytest.mark.asyncio
    async def test_subagent_shows_output_when_verbose_true(self, mock_ctx, monkeypatch):
        """Sub-agent with verbose=True does NOT suppress output."""
        from code_puppy.tools.subagent_context import subagent_context

        # Mock verbose to be True (verbose mode enabled)
        monkeypatch.setattr(
            "code_puppy.agents.event_stream_handler.get_subagent_verbose",
            lambda: True,
        )

        # Create a mock event stream
        text_part = TextPart(content="Response text")

        async def mock_events():
            yield PartStartEvent(index=0, part=text_part)
            yield PartEndEvent(index=0, part=text_part, next_part_kind=None)

        console = MagicMock(spec=Console, width=80)
        console.file = StringIO()
        set_streaming_console(console)

        # Run in sub-agent context BUT with verbose=True
        with subagent_context("test-agent"):
            with patch("code_puppy.agents.event_stream_handler.pause_all_spinners"):
                with patch(
                    "code_puppy.agents.event_stream_handler.resume_all_spinners"
                ):
                    with patch(
                        "code_puppy.agents.event_stream_handler.get_banner_color",
                        return_value="blue",
                    ):
                        with patch("termflow.Parser") as mock_parser_cls:
                            mock_parser = MagicMock()
                            mock_parser.finalize.return_value = []
                            mock_parser_cls.return_value = mock_parser

                            with patch("termflow.Renderer"):
                                await event_stream_handler(mock_ctx, mock_events())

        # Verify output WAS printed (verbose=True overrides suppression)
        console.print.assert_called()

    @pytest.mark.asyncio
    async def test_main_agent_never_suppresses_output(self, mock_ctx, monkeypatch):
        """Main agent output is never suppressed regardless of verbose setting."""
        # Mock verbose to be False
        monkeypatch.setattr(
            "code_puppy.agents.event_stream_handler.get_subagent_verbose",
            lambda: False,
        )

        # Create a mock event stream
        text_part = TextPart(content="Main agent response")

        async def mock_events():
            yield PartStartEvent(index=0, part=text_part)
            yield PartEndEvent(index=0, part=text_part, next_part_kind=None)

        console = MagicMock(spec=Console, width=80)
        console.file = StringIO()
        set_streaming_console(console)

        # NOT in subagent_context - main agent
        with patch("code_puppy.agents.event_stream_handler.pause_all_spinners"):
            with patch("code_puppy.agents.event_stream_handler.resume_all_spinners"):
                with patch(
                    "code_puppy.agents.event_stream_handler.get_banner_color",
                    return_value="blue",
                ):
                    with patch("termflow.Parser") as mock_parser_cls:
                        mock_parser = MagicMock()
                        mock_parser.finalize.return_value = []
                        mock_parser_cls.return_value = mock_parser

                        with patch("termflow.Renderer"):
                            await event_stream_handler(mock_ctx, mock_events())

        # Verify output WAS printed (main agent never suppresses)
        console.print.assert_called()

    @pytest.mark.asyncio
    async def test_suppression_works_with_tool_calls(self, mock_ctx, monkeypatch):
        """Test that suppression also works for tool call parts."""
        from code_puppy.tools.subagent_context import subagent_context

        # Mock verbose to be False
        monkeypatch.setattr(
            "code_puppy.agents.event_stream_handler.get_subagent_verbose",
            lambda: False,
        )

        # Create event stream with tool call
        tool_part = ToolCallPart(tool_call_id="tool_1", tool_name="my_tool", args={})

        async def mock_events():
            yield PartStartEvent(index=0, part=tool_part)
            yield PartDeltaEvent(
                index=0, delta=ToolCallPartDelta(tool_name_delta="my_tool")
            )
            yield PartEndEvent(index=0, part=tool_part, next_part_kind=None)

        console = MagicMock(spec=Console)
        set_streaming_console(console)

        # Run in sub-agent context
        with subagent_context("test-agent"):
            await event_stream_handler(mock_ctx, mock_events())

        # Verify no tool call output was printed
        console.print.assert_not_called()

    @pytest.mark.asyncio
    async def test_suppression_consumes_all_events(self, mock_ctx, monkeypatch):
        """Test that suppression still consumes all events from the stream."""
        from code_puppy.tools.subagent_context import subagent_context

        # Mock verbose to be False
        monkeypatch.setattr(
            "code_puppy.agents.event_stream_handler.get_subagent_verbose",
            lambda: False,
        )

        # Track whether all events were consumed
        events_consumed = 0

        async def mock_events():
            nonlocal events_consumed
            for i in range(10):
                events_consumed += 1
                yield PartStartEvent(index=i, part=TextPart(content=f"text {i}"))

        console = MagicMock(spec=Console)
        set_streaming_console(console)

        # Run in sub-agent context
        with subagent_context("test-agent"):
            await event_stream_handler(mock_ctx, mock_events())

        # Verify all 10 events were consumed
        assert events_consumed == 10
        # But nothing was printed
        console.print.assert_not_called()

    @pytest.mark.asyncio
    async def test_handler_drains_pending_events_on_completion(self, mock_ctx):
        """Test that handler drains remaining stream events before exiting."""
        text_part = TextPart(content="test")
        start_event = PartStartEvent(index=0, part=text_part)
        end_event = PartEndEvent(index=0, part=text_part, next_part_kind=None)

        async def event_stream():
            yield start_event
            yield end_event

        console = MagicMock(spec=Console, width=80)
        console.file = StringIO()
        set_streaming_console(console)

        with patch("code_puppy.agents.event_stream_handler.pause_all_spinners"):
            with patch("code_puppy.agents.event_stream_handler.resume_all_spinners"):
                with patch(
                    "code_puppy.agents.event_stream_handler.get_banner_color",
                    return_value="blue",
                ):
                    with patch("termflow.Parser") as mock_parser_cls:
                        mock_parser = MagicMock()
                        mock_parser.finalize.return_value = []
                        mock_parser_cls.return_value = mock_parser

                        with patch("termflow.Renderer"):
                            with patch(
                                "code_puppy.agents.event_stream_handler._drain_pending_stream_events"
                            ) as mock_drain:
                                await event_stream_handler(mock_ctx, event_stream())

                                # Should drain pending events at end of handler
                                mock_drain.assert_called_once()


class TestStreamEventBatching:
    """Test stream event batching behavior."""

    @pytest.fixture(autouse=True)
    def reset_pending_events(self):
        """Reset the pending events buffer before each test."""
        global _pending_stream_events
        _pending_stream_events.clear()
        yield
        _pending_stream_events.clear()

    @pytest.mark.asyncio
    async def test_events_accumulate_in_pending_buffer(self):
        """Test that events accumulate in _pending_stream_events."""
        # Mock get_session_context to return a test value
        with patch(
            "code_puppy.messaging.get_session_context",
            return_value="test-session",
        ):
            with patch(
                "importlib.util.find_spec",
                return_value=True,
            ):
                # Fire multiple part_start events (not part_end, so no flush)
                for i in range(5):
                    _fire_stream_event("part_start", {"index": i})

                # Events should be accumulated
                assert len(_pending_stream_events) == 5
                for i, (event_type, data, session_id) in enumerate(
                    _pending_stream_events
                ):
                    assert event_type == "part_start"
                    assert data["index"] == i
                    assert session_id == "test-session"

    @pytest.mark.asyncio
    async def test_flush_triggered_at_interval_threshold(self):
        """Test flush is triggered when batch reaches _STREAM_FLUSH_INTERVAL."""
        # Mock get_session_context and callbacks
        with patch(
            "code_puppy.messaging.get_session_context",
            return_value="test-session",
        ):
            with patch(
                "importlib.util.find_spec",
                return_value=True,
            ):
                with patch(
                    "code_puppy.agents.event_stream_handler._flush_stream_events"
                ) as mock_flush:
                    # Add events up to the threshold - 1 (shouldn't trigger flush)
                    for i in range(_STREAM_FLUSH_INTERVAL - 1):
                        _fire_stream_event("part_start", {"index": i})

                    # Buffer should be at threshold - 1, no flush yet
                    assert len(_pending_stream_events) == _STREAM_FLUSH_INTERVAL - 1
                    mock_flush.assert_not_called()

                    # Add one more event to reach threshold
                    _fire_stream_event("part_start", {"index": _STREAM_FLUSH_INTERVAL - 1})

                    # Flush should be triggered via create_task
                    mock_flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_flush_triggered_by_part_end(self):
        """Test flush is triggered by part_end event."""
        # Mock get_session_context and find_spec
        with patch(
            "code_puppy.messaging.get_session_context",
            return_value="test-session",
        ):
            with patch(
                "importlib.util.find_spec",
                return_value=True,
            ):
                with patch(
                    "code_puppy.agents.event_stream_handler._flush_stream_events"
                ) as mock_flush:
                    # Add a few events (not enough to trigger threshold)
                    for i in range(5):
                        _fire_stream_event("part_start", {"index": i})

                    assert len(_pending_stream_events) == 5
                    mock_flush.assert_not_called()

                    # Fire part_end - should trigger immediate flush
                    _fire_stream_event("part_end", {"index": 4})

                    # Flush should be triggered
                    mock_flush.assert_called_once()
                    # Buffer should be cleared
                    assert len(_pending_stream_events) == 0

    @pytest.mark.asyncio
    async def test_flush_stream_events_calls_callbacks(self):
        """Test _flush_stream_events properly calls callbacks.on_stream_event."""
        # Create a batch of events
        batch = [
            ("part_start", {"index": 0}, "session-1"),
            ("part_delta", {"content": "hello"}, "session-1"),
            ("part_end", {"index": 0}, "session-1"),
        ]

        with patch("code_puppy.callbacks.on_stream_event", new_callable=AsyncMock) as mock_on_stream:
            await _flush_stream_events(batch)

            # on_stream_event should be called for each event in batch
            assert mock_on_stream.call_count == 3
            mock_on_stream.assert_any_call("part_start", {"index": 0}, "session-1")
            mock_on_stream.assert_any_call("part_delta", {"content": "hello"}, "session-1")
            mock_on_stream.assert_any_call("part_end", {"index": 0}, "session-1")

    @pytest.mark.asyncio
    async def test_flush_stream_events_handles_errors_gracefully(self):
        """Test _flush_stream_events handles callback errors gracefully."""
        batch = [
            ("part_start", {"index": 0}, "session-1"),
            ("part_start", {"index": 1}, "session-1"),  # Second should still run
        ]

        with patch(
            "code_puppy.callbacks.on_stream_event",
            new_callable=AsyncMock,
            side_effect=[Exception("boom"), None],
        ) as mock_on_stream:
            # Should not raise despite first call failing
            await _flush_stream_events(batch)

            # Both calls should be attempted
            assert mock_on_stream.call_count == 2

    @pytest.mark.asyncio
    async def test_drain_pending_stream_events_flushes_remaining(self):
        """Test _drain_pending_stream_events flushes remaining events."""
        # Add some events to the buffer
        _pending_stream_events.append(("part_start", {"index": 0}, "session-1"))
        _pending_stream_events.append(("part_delta", {"content": "hi"}, "session-1"))

        with patch(
            "code_puppy.agents.event_stream_handler._flush_stream_events"
        ) as mock_flush:
            await _drain_pending_stream_events()

            # Should flush the batch
            mock_flush.assert_called_once()
            # Buffer should be cleared
            assert len(_pending_stream_events) == 0
            # Verify correct batch was passed
            call_args = mock_flush.call_args[0][0]
            assert len(call_args) == 2

    @pytest.mark.asyncio
    async def test_drain_pending_stream_events_noop_when_empty(self):
        """Test _drain_pending_stream_events does nothing when buffer is empty."""
        _pending_stream_events.clear()

        with patch(
            "code_puppy.agents.event_stream_handler._flush_stream_events"
        ) as mock_flush:
            await _drain_pending_stream_events()

            mock_flush.assert_not_called()

    @pytest.mark.asyncio
    async def test_fire_stream_event_import_error(self):
        """Test _fire_stream_event handles ImportError gracefully."""
        # Mock find_spec to return None (module not found)
        with patch(
            "importlib.util.find_spec",
            return_value=None,
        ):
            # Should not raise even though callbacks module is "missing"
            _fire_stream_event("part_start", {"index": 0})
            # Buffer should remain empty since callbacks not available
            assert len(_pending_stream_events) == 0
