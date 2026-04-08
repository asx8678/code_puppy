"""Tests for the TUI streaming output renderer."""

import pytest
from unittest.mock import MagicMock, patch
from code_puppy.tui.stream_renderer import (
    StreamRenderer,
    TOOL_BANNER_MAP,
    LOADING_MESSAGES,
)


class MockApp:
    """Mock CodePuppyApp for testing."""

    def __init__(self):
        self.chat_log: list[str] = []
        self.working_state: bool = False
        self.working_message: str = ""
        self.token_rate: float = 0.0

    def write_to_chat(self, content: str, **kwargs) -> None:
        self.chat_log.append(content)

    def set_working(self, working: bool, message: str = "") -> None:
        self.working_state = working
        self.working_message = message

    def update_token_rate(self, rate: float) -> None:
        self.token_rate = rate


def test_renderer_creation():
    """Test StreamRenderer can be created."""
    app = MockApp()
    renderer = StreamRenderer(app)
    assert renderer._token_count == 0
    assert renderer._streaming_parts == set()


def test_renderer_reset():
    """Test reset clears all state."""
    app = MockApp()
    renderer = StreamRenderer(app)
    renderer._token_count = 42
    renderer._streaming_parts.add(1)
    renderer._text_buffer[0] = "hello"

    renderer.reset()

    assert renderer._token_count == 0
    assert renderer._streaming_parts == set()
    assert renderer._text_buffer == {}


def test_renderer_finalize_prints_stats():
    """Test finalize prints completion stats."""
    app = MockApp()
    renderer = StreamRenderer(app)
    renderer._token_count = 100

    renderer.finalize()

    assert not app.working_state
    # Should have printed stats
    stats = [msg for msg in app.chat_log if "Completed" in msg]
    assert len(stats) == 1
    assert "100 tokens" in stats[0]


def test_renderer_finalize_flushes_buffers():
    """Test finalize flushes remaining text buffers."""
    app = MockApp()
    renderer = StreamRenderer(app)
    renderer._text_buffer[0] = "remaining text"

    renderer.finalize()

    assert "remaining text" in app.chat_log


def test_renderer_finalize_no_stats_when_no_tokens():
    """Test finalize doesn't print stats when no tokens were streamed."""
    app = MockApp()
    renderer = StreamRenderer(app)

    renderer.finalize()

    assert not app.working_state
    stats = [msg for msg in app.chat_log if "Completed" in msg]
    assert len(stats) == 0


def test_tool_banner_map():
    """Test tool banner map has expected entries."""
    assert "cp_agent_run_shell_command" in TOOL_BANNER_MAP
    assert "cp_read_file" in TOOL_BANNER_MAP
    assert "cp_create_file" in TOOL_BANNER_MAP
    assert "cp_grep" in TOOL_BANNER_MAP

    # Each entry should be (display_name, config_name, icon)
    for key, (display, config, icon) in TOOL_BANNER_MAP.items():
        assert isinstance(display, str)
        assert isinstance(config, str)
        assert isinstance(icon, str)


def test_loading_messages():
    """Test loading messages list is populated."""
    assert len(LOADING_MESSAGES) > 0
    assert all(isinstance(m, str) for m in LOADING_MESSAGES)


def test_print_banner_uses_config_color():
    """Test _print_banner reads color from config."""
    app = MockApp()
    renderer = StreamRenderer(app)

    with patch(
        "code_puppy.tui.stream_renderer.get_banner_color", return_value="dark_orange3"
    ) as mock:
        renderer._print_banner("TEST BANNER", "shell_command", "🚀")

    # Should have written a banner with the color
    banners = [msg for msg in app.chat_log if "TEST BANNER" in msg]
    assert len(banners) == 1
    assert "dark_orange3" in banners[0]


def test_print_banner_fallback_on_error():
    """Test _print_banner falls back to blue on config error."""
    app = MockApp()
    renderer = StreamRenderer(app)

    with patch(
        "code_puppy.tui.stream_renderer.get_banner_color",
        side_effect=Exception("no config"),
    ):
        renderer._print_banner("FALLBACK", "nonexistent", "")

    banners = [msg for msg in app.chat_log if "FALLBACK" in msg]
    assert len(banners) == 1
    assert "blue" in banners[0]


def test_print_banner_empty_icon():
    """Test _print_banner with empty icon omits icon_str."""
    app = MockApp()
    renderer = StreamRenderer(app)

    with patch("code_puppy.tui.stream_renderer.get_banner_color", return_value="blue"):
        renderer._print_banner("NO ICON", "thinking", "")

    banners = [msg for msg in app.chat_log if "NO ICON" in msg]
    assert len(banners) == 1
    # The banner should not have trailing icon space
    assert banners[0].endswith("[/bold white on blue]")


def test_handle_event_unknown_type_is_ignored():
    """Test handle_event silently ignores unrecognized event types."""
    app = MockApp()
    renderer = StreamRenderer(app)
    renderer.handle_event("not_an_event")
    assert app.chat_log == []


def test_renderer_reset_clears_all_sets():
    """Test that reset clears all internal tracking sets."""
    app = MockApp()
    renderer = StreamRenderer(app)
    renderer._streaming_parts.add(1)
    renderer._thinking_parts.add(1)
    renderer._text_parts.add(2)
    renderer._tool_parts.add(3)
    renderer._banner_printed.add(4)
    renderer._message_index = 5

    renderer.reset()

    assert renderer._streaming_parts == set()
    assert renderer._thinking_parts == set()
    assert renderer._text_parts == set()
    assert renderer._tool_parts == set()
    assert renderer._banner_printed == set()
    assert renderer._message_index == 0


def test_finalize_calls_set_working_false():
    """Test that finalize always calls set_working(False)."""
    app = MockApp()
    app.working_state = True
    renderer = StreamRenderer(app)

    renderer.finalize()

    assert app.working_state is False


def test_update_rate_rotates_messages():
    """Test that _update_rate rotates through LOADING_MESSAGES."""
    app = MockApp()
    renderer = StreamRenderer(app)
    renderer._token_count = 1  # Ensure elapsed > 0 check passes

    # Force elapsed time to be > 0
    import time

    renderer._start_time = time.monotonic() - 1.0

    first_index = renderer._message_index
    renderer._update_rate()
    second_index = renderer._message_index
    assert second_index == (first_index + 1) % len(LOADING_MESSAGES)
    assert app.working_state is True
    assert app.working_message == LOADING_MESSAGES[second_index]
