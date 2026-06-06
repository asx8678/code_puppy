"""
Consolidated tests for message renderer implementations.

Covers MessageRenderer lifecycle, InteractiveRenderer (async),
SynchronousInteractiveRenderer (production path), styling, complex Rich
content, human-input handling, flush behavior, and error paths.

Source under test: code_puppy/messaging/renderers.py
"""
from __future__ import annotations

import asyncio
import sys
import time
from io import StringIO
from unittest.mock import patch

import pytest
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text

from code_puppy.messaging.message_queue import MessageQueue, MessageType, UIMessage
from code_puppy.messaging.renderers import (
    InteractiveRenderer,
    MessageRenderer,
    SynchronousInteractiveRenderer,
)


class _NoopRenderer(MessageRenderer):
    async def render_message(self, message):
        pass


def _term_console():
    """Return (output, console) with a forced-terminal console over StringIO."""
    output = StringIO()
    return output, Console(file=output, force_terminal=True)


# =============================================================================
# MessageRenderer base class lifecycle
# =============================================================================


class TestMessageRenderer:
    @pytest.mark.asyncio
    async def test_renderer_initialization(self):
        queue = MessageQueue()
        renderer = _NoopRenderer(queue)
        assert renderer.queue is queue
        assert renderer._running is False
        assert renderer._task is None

    @pytest.mark.asyncio
    async def test_renderer_start_marks_running_and_queue_state(self):
        queue = MessageQueue()
        assert not queue._has_active_renderer

        renderer = _NoopRenderer(queue)
        await renderer.start()
        assert renderer._running is True
        assert renderer._task is not None
        assert queue._has_active_renderer

        await renderer.stop()
        assert renderer._running is False
        assert not queue._has_active_renderer
        await asyncio.sleep(0.1)  # give task time to cancel

    @pytest.mark.asyncio
    async def test_renderer_double_start_is_idempotent(self):
        queue = MessageQueue()
        renderer = _NoopRenderer(queue)
        await renderer.start()
        task1 = renderer._task
        await renderer.start()
        assert renderer._task == task1
        await renderer.stop()

    @pytest.mark.asyncio
    async def test_renderer_repeated_start_stop_cycles(self):
        queue = MessageQueue()
        renderer = _NoopRenderer(queue)
        for _ in range(3):
            await renderer.start()
            assert renderer._running is True
            await asyncio.sleep(0.05)
            await renderer.stop()
            assert renderer._running is False
            await asyncio.sleep(0.05)

    @pytest.mark.asyncio
    async def test_renderer_cancellation(self):
        queue = MessageQueue()

        class SlowRenderer(MessageRenderer):
            async def render_message(self, message):
                await asyncio.sleep(1.0)

        renderer = SlowRenderer(queue)
        await renderer.start()
        assert renderer._task is not None
        assert not renderer._task.cancelled()

        await renderer.stop()
        await asyncio.sleep(0.1)
        assert renderer._task.cancelled() or renderer._task.done()

    @pytest.mark.asyncio
    async def test_renderer_with_buffered_messages(self):
        queue = MessageQueue()
        queue.emit(UIMessage(type=MessageType.INFO, content="Buffered1"))
        queue.emit(UIMessage(type=MessageType.INFO, content="Buffered2"))
        assert len(queue.get_buffered_messages()) == 2

        renderer = _NoopRenderer(queue)
        await renderer.start()
        assert queue._has_active_renderer
        await renderer.stop()

    @pytest.mark.asyncio
    async def test_renderer_timeout_on_empty_queue(self):
        """Consume loop survives the wait_for timeout path with no messages."""
        queue = MessageQueue()
        _, console = _term_console()
        renderer = InteractiveRenderer(queue, console)
        await renderer.start()
        await asyncio.sleep(0.2)
        await renderer.stop()

    @pytest.mark.asyncio
    async def test_consume_messages_handles_render_error(self):
        """Render errors are caught and written to stderr; loop keeps running."""
        queue = MessageQueue()
        error_written = []

        class FailingRenderer(MessageRenderer):
            async def render_message(self, message):
                raise ValueError("Render failed!")

        renderer = FailingRenderer(queue)
        original_stderr_write = sys.stderr.write

        def capture_stderr(text):
            error_written.append(text)
            return original_stderr_write(text)

        try:
            await renderer.start()
            queue.emit(UIMessage(type=MessageType.INFO, content="Will fail"))
            with patch.object(sys.stderr, "write", side_effect=capture_stderr):
                await asyncio.sleep(0.3)
            assert renderer._running is True
        finally:
            await renderer.stop()

    @pytest.mark.asyncio
    async def test_multiple_renderers_same_queue(self):
        queue = MessageQueue()
        renderer_a = _NoopRenderer(queue)
        renderer_b = _NoopRenderer(queue)

        await renderer_a.start()
        assert queue._has_active_renderer
        await renderer_b.start()
        assert queue._has_active_renderer

        await renderer_a.stop()
        assert not queue._has_active_renderer
        await renderer_b.stop()


# =============================================================================
# InteractiveRenderer (async)
# =============================================================================


class TestInteractiveRenderer:
    def test_init_with_explicit_console(self):
        queue = MessageQueue()
        _, console = _term_console()
        renderer = InteractiveRenderer(queue, console)
        assert renderer.queue is queue
        assert renderer.console is console

    def test_init_with_default_console(self):
        queue = MessageQueue()
        renderer = InteractiveRenderer(queue)
        assert isinstance(renderer.console, Console)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "msg_type, content, expected",
        [
            # Styled string types (ERROR=bold red, WARNING, SUCCESS, TOOL_OUTPUT,
            # SYSTEM=dim) all flow through the `style` branch.
            (MessageType.ERROR, "Error with style", "Error with style"),
            (MessageType.WARNING, "Warning!", "Warning"),
            (MessageType.SUCCESS, "Success!", "Success"),
            (MessageType.TOOL_OUTPUT, "Tool output text", "Tool output text"),
            (MessageType.SYSTEM, "System message", "System message"),
            (MessageType.INFO, "Plain text", "Plain text"),
            # No-style branches (style is None)
            (MessageType.AGENT_REASONING, "No style text", "No style text"),
            (MessageType.PLANNED_NEXT_STEPS, "1. Do this\n2. Do that", "Do this"),
            # else-branch type (DIVIDER) still prints its content
            (MessageType.DIVIDER, "---", "---"),
            # Version messages forced to dim still render their content
            (MessageType.INFO, "Current version: 1.0.0", "Current version"),
            (MessageType.INFO, "Latest version: 2.0.0", "Latest version"),
        ],
    )
    async def test_render_string_content(self, msg_type, content, expected):
        queue = MessageQueue()
        output, console = _term_console()
        renderer = InteractiveRenderer(queue, console)
        await renderer.render_message(UIMessage(type=msg_type, content=content))
        assert expected in output.getvalue()

    @pytest.mark.asyncio
    async def test_render_agent_response_markdown(self):
        queue = MessageQueue()
        output, console = _term_console()
        renderer = InteractiveRenderer(queue, console)
        msg = UIMessage(
            type=MessageType.AGENT_RESPONSE, content="# Header\n\nParagraph text"
        )
        await renderer.render_message(msg)
        assert len(output.getvalue()) > 0

    @pytest.mark.asyncio
    async def test_render_agent_response_markdown_fallback(self):
        """AGENT_RESPONSE falls back to escaped plain text when Markdown raises."""
        queue = MessageQueue()
        output, console = _term_console()
        renderer = InteractiveRenderer(queue, console)
        msg = UIMessage(type=MessageType.AGENT_RESPONSE, content="Simple text")
        with patch(
            "code_puppy.messaging.renderers.Markdown",
            side_effect=Exception("Markdown error"),
        ):
            await renderer.render_message(msg)
        assert "Simple text" in output.getvalue()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "content_factory, expected",
        [
            (lambda: Text("Styled text", style="bold red"), "Styled text"),
            (lambda: Markdown("**Bold text**"), "Bold"),
        ],
    )
    async def test_render_rich_object_content(self, content_factory, expected):
        queue = MessageQueue()
        output, console = _term_console()
        renderer = InteractiveRenderer(queue, console)
        msg = UIMessage(type=MessageType.INFO, content=content_factory())
        await renderer.render_message(msg)
        assert expected in output.getvalue()

    @pytest.mark.asyncio
    async def test_render_table_content(self):
        queue = MessageQueue()
        output, console = _term_console()
        renderer = InteractiveRenderer(queue, console)
        table = Table(title="Test Table")
        table.add_column("Name")
        table.add_row("Alice")
        await renderer.render_message(UIMessage(type=MessageType.INFO, content=table))
        assert "Alice" in output.getvalue()

    @pytest.mark.asyncio
    async def test_render_none_content(self):
        queue = MessageQueue()
        output, console = _term_console()
        renderer = InteractiveRenderer(queue, console)
        # Should not raise
        await renderer.render_message(UIMessage(type=MessageType.INFO, content=None))

    @pytest.mark.asyncio
    async def test_handle_human_input_request(self):
        queue = MessageQueue()
        output, console = _term_console()
        renderer = InteractiveRenderer(queue, console)
        msg = UIMessage(
            type=MessageType.HUMAN_INPUT_REQUEST,
            content="Please enter your name:",
            metadata={"prompt_id": "test-123"},
        )
        await renderer.render_message(msg)
        out = output.getvalue()
        assert "INPUT REQUESTED" in out
        assert "Please enter your name" in out

    @pytest.mark.asyncio
    async def test_console_flush_called(self):
        queue = MessageQueue()
        output, console = _term_console()
        renderer = InteractiveRenderer(queue, console)

        flush_called = [False]
        original_flush = output.flush

        def mock_flush():
            flush_called[0] = True
            original_flush()

        output.flush = mock_flush
        await renderer.render_message(UIMessage(type=MessageType.INFO, content="Test"))
        assert flush_called[0] is True


# =============================================================================
# SynchronousInteractiveRenderer (production path)
# =============================================================================


class TestSynchronousInteractiveRenderer:
    def test_init_with_explicit_console(self):
        queue = MessageQueue()
        _, console = _term_console()
        renderer = SynchronousInteractiveRenderer(queue, console)
        assert renderer.queue is queue
        assert renderer.console is console
        assert renderer._running is False
        assert renderer._thread is None

    def test_init_with_default_console(self):
        queue = MessageQueue()
        renderer = SynchronousInteractiveRenderer(queue)
        assert isinstance(renderer.console, Console)

    def test_start_registers_listener_and_marks_active(self):
        """start() drives delivery via the queue's processing thread/listener,
        not its own consume thread."""
        queue = MessageQueue()
        _, console = _term_console()
        renderer = SynchronousInteractiveRenderer(queue, console)
        renderer.start()
        try:
            assert renderer._running is True
            assert queue._running is True
            assert renderer._render_message in queue._listeners
            assert queue._has_active_renderer
        finally:
            renderer.stop()

    def test_double_start_registers_listener_once(self):
        queue = MessageQueue()
        _, console = _term_console()
        renderer = SynchronousInteractiveRenderer(queue, console)
        renderer.start()
        renderer.start()  # no-op
        try:
            assert renderer._running is True
            assert queue._listeners.count(renderer._render_message) == 1
        finally:
            renderer.stop()

    def test_stop_unregisters_listener_and_marks_inactive(self):
        queue = MessageQueue()
        _, console = _term_console()
        renderer = SynchronousInteractiveRenderer(queue, console)
        renderer.start()
        assert renderer._running is True

        renderer.stop()
        assert renderer._running is False
        assert not queue._has_active_renderer
        assert renderer._render_message not in queue._listeners

    def test_stop_without_start_is_safe(self):
        queue = MessageQueue()
        _, console = _term_console()
        renderer = SynchronousInteractiveRenderer(queue, console)
        renderer.stop()  # should not raise
        assert renderer._running is False

    @pytest.mark.parametrize(
        "msg_type, content, expected",
        [
            (MessageType.ERROR, "Error occurred", "Error occurred"),
            (MessageType.WARNING, "Warning!", "Warning"),
            (MessageType.SUCCESS, "Success!", "Success"),
            (MessageType.TOOL_OUTPUT, "Tool result", "Tool result"),
            (MessageType.SYSTEM, "System info", "System info"),
            (MessageType.AGENT_REASONING, "Thinking about it...", "Thinking about it"),
            (MessageType.DIVIDER, "---", "---"),
            (MessageType.INFO, "Current version: 1.2.3", "Current version"),
            (MessageType.INFO, "Latest version: 3.0.0", "Latest version"),
        ],
    )
    def test_render_string_content(self, msg_type, content, expected):
        queue = MessageQueue()
        output, console = _term_console()
        renderer = SynchronousInteractiveRenderer(queue, console)
        renderer._render_message(UIMessage(type=msg_type, content=content))
        assert expected in output.getvalue()

    def test_render_agent_response_as_markdown(self):
        queue = MessageQueue()
        output, console = _term_console()
        renderer = SynchronousInteractiveRenderer(queue, console)
        renderer._render_message(
            UIMessage(type=MessageType.AGENT_RESPONSE, content="# Title\n\nBody")
        )
        assert len(output.getvalue()) > 0

    def test_render_agent_response_markdown_fallback(self):
        queue = MessageQueue()
        output, console = _term_console()
        renderer = SynchronousInteractiveRenderer(queue, console)
        msg = UIMessage(type=MessageType.AGENT_RESPONSE, content="Plain fallback")
        with patch(
            "code_puppy.messaging.renderers.Markdown",
            side_effect=Exception("Parse error"),
        ):
            renderer._render_message(msg)
        assert "Plain fallback" in output.getvalue()

    @pytest.mark.parametrize(
        "content_factory, expected",
        [
            (lambda: _make_table(), "Value1"),
            (lambda: Text("Styled content", style="bold"), "Styled content"),
        ],
    )
    def test_render_rich_object_content(self, content_factory, expected):
        queue = MessageQueue()
        output, console = _term_console()
        renderer = SynchronousInteractiveRenderer(queue, console)
        renderer._render_message(
            UIMessage(type=MessageType.INFO, content=content_factory())
        )
        assert expected in output.getvalue()

    @pytest.mark.parametrize("metadata", [{}, None])
    def test_human_input_missing_prompt_id_shows_error(self, metadata):
        queue = MessageQueue()
        output, console = _term_console()
        renderer = SynchronousInteractiveRenderer(queue, console)
        msg = UIMessage(
            type=MessageType.HUMAN_INPUT_REQUEST,
            content="Enter something:",
            metadata=metadata,
        )
        renderer._render_message(msg)
        out = output.getvalue()
        assert "Error" in out or "Invalid" in out

    def test_human_input_with_valid_prompt_id(self):
        queue = MessageQueue()
        output, console = _term_console()
        renderer = SynchronousInteractiveRenderer(queue, console)
        msg = UIMessage(
            type=MessageType.HUMAN_INPUT_REQUEST,
            content="Enter your name:",
            metadata={"prompt_id": "prompt-abc"},
        )
        with patch("builtins.input", return_value="Claude"):
            with patch(
                "code_puppy.messaging.message_queue.provide_prompt_response"
            ) as mock_provide:
                renderer._render_message(msg)
                mock_provide.assert_called_once_with("prompt-abc", "Claude")
        assert "Enter your name" in output.getvalue()

    def test_human_input_flush_called(self):
        queue = MessageQueue()
        output, console = _term_console()
        renderer = SynchronousInteractiveRenderer(queue, console)
        msg = UIMessage(
            type=MessageType.HUMAN_INPUT_REQUEST,
            content="Enter:",
            metadata={"prompt_id": "test"},
        )
        flush_count = [0]
        original_flush = output.flush

        def mock_flush():
            flush_count[0] += 1
            original_flush()

        output.flush = mock_flush
        with patch("builtins.input", return_value="x"):
            with patch("code_puppy.messaging.message_queue.provide_prompt_response"):
                renderer._render_message(msg)
        assert flush_count[0] >= 1

    def test_consume_messages_processes_queue(self):
        """End-to-end: emitted message is delivered to the registered listener."""
        queue = MessageQueue()
        output, console = _term_console()
        renderer = SynchronousInteractiveRenderer(queue, console)
        renderer.start()
        try:
            queue.emit(UIMessage(type=MessageType.INFO, content="Hello from queue!"))
            time.sleep(0.1)
            assert "Hello from queue" in output.getvalue()
        finally:
            renderer.stop()

    def test_render_flush_called(self):
        queue = MessageQueue()
        output, console = _term_console()
        renderer = SynchronousInteractiveRenderer(queue, console)
        flush_called = [False]
        original_flush = output.flush

        def mock_flush():
            flush_called[0] = True
            original_flush()

        output.flush = mock_flush
        renderer._render_message(UIMessage(type=MessageType.INFO, content="Test"))
        assert flush_called[0] is True


def _make_table():
    table = Table()
    table.add_column("Col1")
    table.add_row("Value1")
    return table
