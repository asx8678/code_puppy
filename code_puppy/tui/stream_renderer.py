"""Streaming output renderer for the Textual TUI.

Adapts pydantic-ai streaming events (PartStartEvent, PartDeltaEvent, PartEndEvent)
into Rich-formatted output written to the CodePuppyApp's RichLog widget.

This replaces the Rich Console-based rendering in event_stream_handler.py
for the Textual TUI context.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from rich.markup import escape

# Module-level import for patching in tests; guarded so missing config doesn't crash.
try:
    from code_puppy.config import get_banner_color
except Exception:  # pragma: no cover

    def get_banner_color(name: str) -> str:  # type: ignore[misc]
        return "blue"


# Hoist pydantic_ai imports to module top with guard (Issue SR-H2)
_PYDANTIC_AI_OK = False
try:
    from pydantic_ai import PartDeltaEvent, PartEndEvent, PartStartEvent
    from pydantic_ai.messages import (
        TextPart,
        TextPartDelta,
        ThinkingPart,
        ThinkingPartDelta,
        ToolCallPart,
        ToolCallPartDelta,
    )

    _PYDANTIC_AI_OK = True
except ImportError:
    PartDeltaEvent = None  # type: ignore[misc,assignment]
    PartEndEvent = None  # type: ignore[misc,assignment]
    PartStartEvent = None  # type: ignore[misc,assignment]
    TextPart = None  # type: ignore[misc,assignment]
    TextPartDelta = None  # type: ignore[misc,assignment]
    ThinkingPart = None  # type: ignore[misc,assignment]
    ThinkingPartDelta = None  # type: ignore[misc,assignment]
    ToolCallPart = None  # type: ignore[misc,assignment]
    ToolCallPartDelta = None  # type: ignore[misc,assignment]


if TYPE_CHECKING:
    from code_puppy.tui.app import CodePuppyApp

from typing import Protocol, runtime_checkable


@runtime_checkable
class TUIHost(Protocol):
    """Protocol that any TUI app must satisfy to host a StreamRenderer.

    This decouples the renderer from the concrete CodePuppyApp class,
    making it testable and enforcing the contract at the type level.
    """

    def write_to_chat(self, content: str, **kwargs) -> None: ...
    def set_working(self, working: bool, message: str = "") -> None: ...
    def update_token_rate(self, rate: float) -> None: ...


logger = logging.getLogger(__name__)

# Tool name to banner display name mapping
TOOL_BANNER_MAP = {
    "cp_agent_run_shell_command": ("SHELL COMMAND", "shell_command", "🚀"),
    "cp_read_file": ("READ FILE", "read_file", "📂"),
    "cp_create_file": ("CREATE FILE", "create_file", "📝"),
    "cp_grep": ("GREP", "grep", "📂"),
    "cp_list_files": ("DIRECTORY LISTING", "directory_listing", "📂"),
    "cp_invoke_agent": ("INVOKE AGENT", "invoke_agent", "🤖"),
}

# Loading messages for status bar rotation
LOADING_MESSAGES = [
    "Sniffing around...",
    "Wagging tail...",
    "Digging up results...",
    "Chewing on it...",
    "Puppy pondering...",
    "Bounding through data...",
    "Howling at the code...",
]

# Rate update throttle interval (5 Hz max) (Issue SR-H1)
_RATE_UPDATE_INTERVAL = 0.2


class StreamRenderer:
    """Renders streaming LLM events into a Textual CodePuppyApp.

    Usage::

        renderer = StreamRenderer(app)
        async for event in agent_stream:
            renderer.handle_event(event)
        renderer.finalize()
    """

    # Add __slots__ for faster attribute access (Issue SR-M2)
    __slots__ = (
        "app",
        "_streaming_parts",
        "_thinking_parts",
        "_text_parts",
        "_tool_parts",
        "_banner_printed",
        "_token_count",
        "_start_time",
        "_message_index",
        "_text_buffer",
        "_last_rate_update",
        "_last_spinner_update",
    )

    def __init__(self, app: "CodePuppyApp | TUIHost") -> None:
        self.app = app
        self._streaming_parts: set[int] = set()
        self._thinking_parts: set[int] = set()
        self._text_parts: set[int] = set()
        self._tool_parts: set[int] = set()
        self._banner_printed: set[int] = set()
        self._token_count: int = 0
        self._start_time: float = time.monotonic()
        self._message_index: int = 0
        self._text_buffer: dict[int, str] = {}
        # Throttling timestamps for rate updates and spinner rotation (Issue SR-H1)
        self._last_rate_update: float = 0.0
        self._last_spinner_update: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def handle_event(self, event: Any) -> None:
        """Handle a single streaming event.

        Dispatches to the appropriate handler based on event type.
        """
        if not _PYDANTIC_AI_OK:
            logger.debug("pydantic_ai not available; skipping event")
            return

        if isinstance(event, PartStartEvent):
            self._handle_part_start(event)
        elif isinstance(event, PartDeltaEvent):
            self._handle_part_delta(event)
        elif isinstance(event, PartEndEvent):
            self._handle_part_end(event)

    def finalize(self) -> None:
        """Called when streaming is complete.

        Flushes remaining buffers and prints completion stats.
        """
        # Flush all remaining buffers
        for idx, buf in self._text_buffer.items():
            if buf:
                self.app.write_to_chat(buf)
        self._text_buffer.clear()

        # Print completion stats only when tokens were actually streamed
        elapsed = time.monotonic() - self._start_time
        if elapsed > 0 and self._token_count > 0:
            avg_rate = self._token_count / elapsed
            self.app.write_to_chat(
                f"\n[dim]Completed: {self._token_count} tokens "
                f"in {elapsed:.1f}s ({avg_rate:.1f} t/s avg)[/dim]"
            )
            self.app.update_token_rate(avg_rate)

        # Reset working state
        self.app.set_working(False)

    def reset(self) -> None:
        """Reset state for a new streaming session."""
        self._streaming_parts.clear()
        self._thinking_parts.clear()
        self._text_parts.clear()
        self._tool_parts.clear()
        self._banner_printed.clear()
        self._text_buffer.clear()
        self._token_count = 0
        self._start_time = time.monotonic()
        self._message_index = 0
        # Reset throttling timestamps (Issue SR-H1)
        self._last_rate_update = 0.0
        self._last_spinner_update = 0.0

    # ------------------------------------------------------------------
    # Private event handlers
    # ------------------------------------------------------------------

    def _handle_part_start(self, event: Any) -> None:
        """Handle the start of a new part."""
        if not _PYDANTIC_AI_OK:
            logger.debug("pydantic_ai.messages not available")
            return

        part = event.part

        if isinstance(part, ThinkingPart):
            self._streaming_parts.add(event.index)
            self._thinking_parts.add(event.index)
            self._print_banner("THINKING", "thinking", "⚡")
            self._banner_printed.add(event.index)
            if part.content and part.content.strip():
                self.app.write_to_chat(f"[dim]{escape(part.content)}[/dim]")

        elif isinstance(part, TextPart):
            self._streaming_parts.add(event.index)
            self._text_parts.add(event.index)
            self._text_buffer[event.index] = ""
            self._print_banner("AGENT RESPONSE", "agent_response", "")
            self._banner_printed.add(event.index)
            if part.content and part.content.strip():
                self._text_buffer[event.index] = part.content

        elif isinstance(part, ToolCallPart):
            self._streaming_parts.add(event.index)
            self._tool_parts.add(event.index)
            tool_name = part.tool_name
            banner_info = TOOL_BANNER_MAP.get(
                tool_name, (tool_name, "mcp_tool_call", "🔧")
            )
            self._print_banner(*banner_info)
            self._banner_printed.add(event.index)

    def _handle_part_delta(self, event: Any) -> None:
        """Handle a streaming delta (incremental content)."""
        if not _PYDANTIC_AI_OK:
            logger.debug("pydantic_ai.messages not available")
            return

        delta = event.delta

        if isinstance(delta, ThinkingPartDelta):
            if delta.content_delta:
                self.app.write_to_chat(f"[dim]{escape(delta.content_delta)}[/dim]")

        elif isinstance(delta, TextPartDelta):
            if delta.content_delta:
                self._token_count += 1
                self._update_rate()

                # Buffer text and flush periodically
                if event.index in self._text_buffer:
                    self._text_buffer[event.index] += delta.content_delta
                else:
                    self._text_buffer[event.index] = delta.content_delta

                # Flush on newlines or every ~20 chars for responsiveness
                buf = self._text_buffer[event.index]
                if "\n" in buf or len(buf) > 20:
                    self.app.write_to_chat(buf)
                    self._text_buffer[event.index] = ""

        elif isinstance(delta, ToolCallPartDelta):
            # Tool call deltas contain args JSON fragments — usually not shown
            pass

    def _handle_part_end(self, event: Any) -> None:
        """Handle the end of a part — flush any buffered content."""
        idx = event.index

        # Flush any remaining text buffer
        if idx in self._text_buffer and self._text_buffer[idx]:
            self.app.write_to_chat(self._text_buffer[idx])
            self._text_buffer[idx] = ""

        # Clean up tracking sets
        self._streaming_parts.discard(idx)
        self._thinking_parts.discard(idx)
        self._text_parts.discard(idx)
        self._tool_parts.discard(idx)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _print_banner(self, label: str, config_name: str, icon: str) -> None:
        """Print a styled banner to the chat log."""
        try:
            color = get_banner_color(config_name)
        except Exception:
            color = "blue"

        icon_str = f" {icon}" if icon else ""
        banner = f"[bold white on {color}] {label} [/bold white on {color}]{icon_str}"
        self.app.write_to_chat("")  # Blank line before banner
        self.app.write_to_chat(banner)

    def _update_rate(self) -> None:
        """Update the token rate in the status bar.

        Throttled to 5 Hz for rate updates to avoid DOM query cascade.
        Spinner rotation is decoupled to 2 Hz.
        """
        now = time.monotonic()

        # Throttle rate updates to 5 Hz (Issue SR-H1)
        if now - self._last_rate_update >= _RATE_UPDATE_INTERVAL:
            self._last_rate_update = now
            elapsed = now - self._start_time
            if elapsed > 0:
                rate = self._token_count / elapsed
                self.app.update_token_rate(rate)

        # Decouple spinner rotation to 2 Hz (every 0.5s)
        if now - self._last_spinner_update >= 0.5:
            self._last_spinner_update = now
            self._message_index = (self._message_index + 1) % len(LOADING_MESSAGES)
            self.app.set_working(True, LOADING_MESSAGES[self._message_index])
